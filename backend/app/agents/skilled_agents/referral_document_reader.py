"""Referral Document Reader — was "pdf reader"."""

import logging
from pathlib import Path

from app.agents.base import Agent, AgentSpec
from app.graph_workflow.chat_orchestration.state import TriageState
from app.core.config import settings
from app.services.pdf_reader import PdfExtractionError, read_pdf

logger = logging.getLogger(__name__)


def resolve_document_path(state: TriageState) -> Path:
    """Locate the referral PDF for this run.

    Prefers an explicit `document_path`; otherwise falls back to where the
    upload endpoint stores files, so a run started from a referral id alone
    still finds its document.
    """
    explicit = state.get("document_path")
    if explicit:
        return Path(explicit)

    referral_id = state.get("referral_id")
    if not referral_id:
        raise PdfExtractionError("No document_path or referral_id in state.")

    return Path(settings.upload_dir) / "referrals" / f"{referral_id}.pdf"


class ReferralDocumentReader(Agent):
    """Turns the uploaded referral PDF into usable text.

    Reads the stored document, extracts its text (and page structure), and
    flags scanned/image-only files that carry no extractable text.
    """

    spec = AgentSpec(
        name="referral_document_reader",
        title="Referral Document Reader",
        purpose="Extract raw text and page structure from the uploaded referral PDF.",
        consumes=("referral_id", "document_path"),
        produces=("referral_transcription", "page_count", "is_scanned"),
    )

    async def run(self, state: TriageState) -> dict:
        """Extract the PDF into `referral_transcription`.

        A missing or unreadable file raises: unlike an auth failure there is no
        recovery path, so the node wrapper records it in `last_error` and the
        run stops. A *scanned* PDF is not an error — it parses fine and simply
        yields no text, so it is reported via `is_scanned` for the orchestrator
        to route on (OCR, or ending the run) rather than being raised here.
        """
        # A run started from text alone has nothing to read; pass it straight
        # through so the rest of the pipeline still has its source.
        if not state.get("document_path") and state.get("referral_text"):
            text = state["referral_text"]
            logger.info(
                "Referral %s: using supplied text (%d chars); no PDF to read.",
                state.get("referral_id"),
                len(text),
            )
            return {
                "referral_transcription": text,
                "page_count": 0,
                "is_scanned": False,
            }

        path = resolve_document_path(state)
        if not path.is_file():
            raise PdfExtractionError(f"Referral PDF not found at {path}.")

        content = await read_pdf(path)

        if content.is_scanned:
            logger.warning(
                "Referral %s: %s has no extractable text (scanned?).",
                state.get("referral_id"),
                path.name,
            )
        else:
            logger.info(
                "Referral %s: extracted %d chars from %d page(s).",
                state.get("referral_id"),
                content.char_count,
                content.page_count,
            )

        return {
            "referral_transcription": content.text,
            "page_count": content.page_count,
            "is_scanned": content.is_scanned,
        }
