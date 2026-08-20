"""Referral Document Classifier — was "pdf classifier"."""

import logging

from app.agents.base import Agent, AgentSpec, AgentState

logger = logging.getLogger(__name__)

# STUB OUTPUT — a state update rather than a message, since the workflow
# routes on these values.
SAMPLE_OUTPUT: dict = {
    "document_type": "referral_letter",
    "is_referral": True,
    "classification_confidence": 0.94,
}


class ReferralDocumentClassifier(Agent):
    """Decides what the uploaded document actually is.

    Confirms it is a referral letter (rather than a discharge summary, lab
    report, or unrelated file) so the pipeline can stop early on documents it
    should not triage.
    """

    spec = AgentSpec(
        name="referral_document_classifier",
        title="Referral Document Classifier",
        purpose="Classify the document type and confirm it is a clinical referral.",
        consumes=("referral_transcription",),
        produces=("document_type", "is_referral", "classification_confidence"),
    )

    async def run(self, state: AgentState) -> dict:
        """Return the classification as a state update.

        STUB: returns `SAMPLE_OUTPUT` regardless of input — note it always
        says the document *is* a referral, so this gate lets everything
        through until the real classifier lands.
        """
        logger.warning(
            "%s: stub execution — returning sample output.", self.spec.name
        )
        return dict(SAMPLE_OUTPUT)
