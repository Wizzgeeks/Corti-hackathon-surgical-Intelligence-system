"""Corti text generation and fact extraction, shared by the skilled agents.

Two Corti surfaces are wrapped here so each agent only has to supply a prompt:

* `generate_text()` — `POST /v2/documents/` with an **inline dynamic
  template**: one string section, generated from the referral text. No stored
  template to maintain, which suits agents whose output is prose.
* `extract_facts()` — `POST /v2/tools/extract-facts`, stateless fact
  extraction used for the pre-consultation brief.

Both return the raw request and response alongside the result so agents can
record the exchange in `corti_logs`.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.services import corti_endpoints as urls
from app.services.corti_client import CortiClient

logger = logging.getLogger(__name__)

RETENTION_HEADER = {"X-Corti-Retention-Policy": settings.corti_retention_policy}


@dataclass
class CortiResult:
    """What an agent needs back from a Corti call."""

    text: str = ""
    facts: list[dict[str, Any]] = field(default_factory=list)
    request: Any = None
    response: Any = None

    def as_call(self, agent_name: str) -> dict:
        """The `corti_call` record the node wrapper lifts into `corti_logs`."""
        return {
            "agent_name": agent_name,
            "corti_request": self.request,
            "corti_response": self.response,
        }


def build_document_payload(
    *,
    name: str,
    heading: str,
    prompt: str,
    content_prompt: str,
    context_text: str,
    writing_style_prompt: str | None = None,
) -> dict[str, Any]:
    """An inline single-section document request.

    `context` rather than `interactionId`, so the call is stateless — nothing
    is stored against an interaction.
    """
    instructions: dict[str, Any] = {"contentPrompt": content_prompt}
    if writing_style_prompt:
        instructions["writingStylePrompt"] = writing_style_prompt

    return {
        "outputLanguage": settings.corti_output_language,
        "context": [{"type": "text", "text": context_text}],
        "dynamicTemplate": {
            "name": name,
            "generation": {
                "instructions": {"prompt": prompt},
                "sections": [
                    {
                        "heading": heading,
                        "instructions": instructions,
                        "outputSchema": {"type": "string"},
                    }
                ],
            },
        },
    }


def read_document_text(response: dict[str, Any]) -> str:
    """Pull the generated prose out of a document response.

    Prefers `stringDocument` (already rendered); falls back to
    `structuredDocument` for the single string section.
    """
    document = (response or {}).get("document") or response or {}

    strings = document.get("stringDocument") or {}
    text = "\n\n".join(str(v).strip() for v in strings.values() if v)
    if text:
        return text.strip()

    structured = document.get("structuredDocument") or {}
    parts: list[str] = []
    for section in structured.values():
        if isinstance(section, str):
            parts.append(section)
        elif isinstance(section, dict):
            parts.extend(str(v) for v in section.values() if isinstance(v, str))
    return "\n\n".join(p.strip() for p in parts if p).strip()


async def generate_text(
    *,
    name: str,
    heading: str,
    prompt: str,
    content_prompt: str,
    context_text: str,
    access_token: str | None,
    writing_style_prompt: str | None = None,
) -> CortiResult:
    """Generate one prose section from the referral text."""
    payload = build_document_payload(
        name=name,
        heading=heading,
        prompt=prompt,
        content_prompt=content_prompt,
        context_text=context_text,
        writing_style_prompt=writing_style_prompt,
    )

    response = await CortiClient().post(
        urls.api_url(urls.Paths.DOCUMENTS),
        json=payload,
        extra_headers=RETENTION_HEADER,
        access_token=access_token,
    )

    return CortiResult(
        text=read_document_text(response or {}), request=payload, response=response
    )


async def extract_facts(
    *, context_text: str, access_token: str | None
) -> CortiResult:
    """Extract clinical facts from text — stateless, nothing stored at Corti."""
    payload = {
        "context": [{"type": "text", "text": context_text}],
        "outputLanguage": settings.corti_output_language,
    }

    response = await CortiClient().post(
        urls.api_url(urls.Paths.EXTRACT_FACTS),
        json=payload,
        extra_headers=RETENTION_HEADER,
        access_token=access_token,
    )

    facts = (response or {}).get("facts") or []
    return CortiResult(facts=facts, request=payload, response=response)


def format_facts(facts: list[dict[str, Any]]) -> str:
    """Render extracted facts as a grouped, readable brief."""
    grouped: dict[str, list[str]] = {}
    for fact in facts:
        text = str(fact.get("text") or "").strip()
        if not text:
            continue
        grouped.setdefault(str(fact.get("group") or "other"), []).append(text)

    blocks = []
    for group, items in grouped.items():
        heading = group.replace("-", " ").replace("_", " ").strip().capitalize()
        lines = "\n".join(f"- {item}" for item in items)
        blocks.append(f"{heading}:\n{lines}")
    return "\n\n".join(blocks)


# --- Case record context ---------------------------------------------------

# Labels for the Mongo documents every agent receives. Sent as JSON so the
# model sees the record exactly as stored, rather than a lossy summary.
CASE_CONTEXT_LABELS: dict[str, str] = {
    "case_document": "Current case record (JSON)",
    "appointment_documents": "Appointments for this case (JSON)",
    "surgery_documents": "Surgeries for this case (JSON)",
}


def case_context_blocks(state: dict) -> list[str]:
    """Render the case, appointment and surgery records for a Corti prompt.

    The referral orchestrator loads these from Mongo once per run and puts
    them in state; every agent passes them to Corti so each one reasons over
    the same record. Absent or empty documents are skipped rather than sent
    as `null`, which would only invite the model to comment on them.
    """
    blocks: list[str] = []
    for key, label in CASE_CONTEXT_LABELS.items():
        value = state.get(key)
        if not value:
            continue
        blocks.append(f"{label}:\n{json.dumps(value, indent=2, default=str)}")
    return blocks
