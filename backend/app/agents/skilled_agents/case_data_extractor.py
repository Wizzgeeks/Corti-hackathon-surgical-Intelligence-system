"""Case Data Extractor — was "case_data_classifier".

Backed by Corti's guided document generation: the referral text is posted to
`POST /v2/documents/` against the case-extraction template, and Corti returns
a `structuredDocument` holding the patient and referrer details.
"""

import logging
from typing import Any

from app.agents.base import Agent, AgentSpec, AgentState
from app.core.config import settings
from app.services import corti_endpoints as urls
from app.services.corti_client import CortiClient
from app.services.corti_textgen import case_context_blocks

logger = logging.getLogger(__name__)

# The referrer keeps its object shape end to end, matching what Corti returns.
REFERRER_FIELDS: tuple[str, ...] = ("name", "current_role", "organization")


def empty_referrer() -> dict[str, str]:
    return {field: "" for field in REFERRER_FIELDS}


# Fields the extractor is responsible for.
def empty_result() -> dict:
    return {
        "patient_name": "",
        "patient_age": "",
        "patient_gender": "",
        "patient_contact": "",
        "referred_to_consultant": "",
        "referred_by": empty_referrer(),
    }


def build_payload(referral_text: str) -> dict[str, Any]:
    """Body for Corti's guided document generation."""
    return {
        "outputLanguage": settings.corti_output_language,
        "templateRef": {"templateId": settings.corti_case_extraction_template_id},
        "context": [{"type": "text", "text": referral_text}],
    }


def _flatten_sections(structured: dict[str, Any]) -> dict[str, Any]:
    """Merge the template's sections into one flat mapping.

    `structuredDocument` is keyed by section id, so the fields sit one level
    down. Merging keeps the agent working if the template is later split
    across several sections.
    """
    merged: dict[str, Any] = {}
    for section in structured.values():
        if isinstance(section, dict):
            merged.update(section)
    return merged


def normalise_referrer(referred_by: Any) -> dict[str, str]:
    """Return the referrer as a `{name, current_role, organization}` object.

    Corti sends this as an object with nullable members; nulls become empty
    strings so every key is always present. A bare string is accepted too and
    treated as the referrer's name.
    """
    referrer = empty_referrer()

    if isinstance(referred_by, str):
        referrer["name"] = referred_by.strip()
        return referrer

    if isinstance(referred_by, dict):
        for field in REFERRER_FIELDS:
            referrer[field] = str(referred_by.get(field) or "").strip()

    return referrer


def map_response(response: dict[str, Any]) -> dict[str, str]:
    """Map Corti's structured document onto the extractor's fields.

    The API wraps the result as `{"document": {...}, "usageInfo": {...}}`;
    the flat form is accepted too so a caller can pass the document directly.
    """
    document = response.get("document") or response
    fields = _flatten_sections(document.get("structuredDocument") or {})

    result = empty_result()
    result["patient_name"] = str(fields.get("name") or "").strip()
    # `age` comes back as a number.
    age = fields.get("age")
    result["patient_age"] = "" if age in (None, "") else str(age)
    result["patient_gender"] = str(fields.get("gender") or "").strip()
    result["patient_contact"] = str(fields.get("contact") or "").strip()
    result["referred_by"] = normalise_referrer(fields.get("referred_by"))
    # The consultant the letter is addressed to — distinct from the team the
    # assigner recommends later in the pipeline.
    result["referred_to_consultant"] = str(
        fields.get("referred_to_consultant") or ""
    ).strip()

    return result


class CaseDataExtractor(Agent):
    """Pulls the structured case out of the referral text.

    Identifies the patient, the referrer, the presenting symptoms, and the
    clinical background, mapping free text onto the Patient and Case models.
    """

    spec = AgentSpec(
        name="case_data_extractor",
        title="Case Data Extractor",
        purpose="Extract structured patient and case fields from the referral text.",
        consumes=("referral_transcription", "referral_text", "corti_access_token"),
        produces=(
            "patient_name",
            "patient_age",
            "patient_gender",
            "patient_contact",
            "referred_by",
            "contact"
        ),
    )

    async def run(self, state: AgentState) -> dict:
        """Generate the structured document and return the patient fields.

        Replies with a dict rather than a message — the referral orchestrator
        maps these keys straight onto the response contract.
        """
        referral_text = (
            state.get("referral_transcription") or state.get("referral_text") or ""
        ).strip()
        if not referral_text:
            logger.warning("%s: no referral text to extract from.", self.spec.name)
            return empty_result()

        # The stored case records travel with the referral text, so extraction
        # can reconcile the letter against what is already on file.
        context = "\n\n".join([referral_text, *case_context_blocks(state)])
        payload = build_payload(context)
        document = await CortiClient().post(
            urls.api_url(urls.Paths.DOCUMENTS),
            json=payload,
            extra_headers={
                "X-Corti-Retention-Policy": settings.corti_retention_policy
            },
            # Reuse the token the run already holds; a 401 sends the workflow
            # back through the authenticator and resumes here.
            access_token=state.get("corti_access_token"),
        )

        result = map_response(document or {})
        # Recorded so the API can return the raw exchange. The node wrapper
        # lifts this out of the reply into `corti_logs`.
        result["corti_call"] = {
            "agent_name": self.spec.name,
            "corti_request": payload,
            "corti_response": document,
        }

        credits = ((document or {}).get("usageInfo") or {}).get("creditsConsumed")
        logger.info(
            "%s: extracted patient=%r age=%r contact=%r (credits: %s)",
            self.spec.name,
            result["patient_name"],
            result["patient_age"],
            result["patient_contact"],
            credits,
        )
        return result
