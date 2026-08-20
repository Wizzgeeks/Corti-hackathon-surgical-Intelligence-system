"""Pre-Consultation Briefer — the brief a consultant reads before the clinic.

Backed by Corti's fact extraction (`POST /v2/tools/extract-facts`) rather than
text generation: the value here is a grounded list of what the referral
actually states — demographics, complaint, history, findings — not prose about
it. The call is stateless, so nothing is stored against a Corti interaction.
"""

import logging

from app.agents.base import Agent, AgentSpec, AgentState
from app.services.corti_textgen import (
    case_context_blocks,
    extract_facts,
    format_facts,
)

logger = logging.getLogger(__name__)


class PreConsultationBriefer(Agent):
    """Turns the referral into the facts a consultant needs before the clinic.

    Each fact is grouped (demographics, chief complaint, history, and so on)
    and comes from the letter itself, so the brief can be checked line by line
    against the source.
    """

    spec = AgentSpec(
        name="pre_consultation_briefer",
        title="Pre-Consultation Briefer",
        purpose=(
            "Extract the clinical facts of the referral into a pre-consultation "
            "brief."
        ),
        consumes=("referral_transcription", "case_summary", "corti_access_token"),
        produces=("pre_consultation_notes", "pre_consultation_facts"),
    )

    def build_context(self, state: AgentState) -> str:
        """The source letter, plus the case records the orchestrator loaded.

        Fact extraction works from source material rather than summaries of
        it, so the referral text leads and the stored case, appointment and
        surgery records follow.
        """
        referral = (
            state.get("referral_transcription") or state.get("referral_text") or ""
        ).strip()
        return "\n\n".join([referral, *case_context_blocks(state)]).strip()

    async def run(self, state: AgentState) -> dict:
        """Extract facts and render them as the pre-consultation brief."""
        context = self.build_context(state)
        if not context:
            logger.warning("%s: no referral text to extract from.", self.spec.name)
            return {"text": ""}

        result = await extract_facts(
            context_text=context, access_token=state.get("corti_access_token")
        )

        brief = format_facts(result.facts)
        logger.info(
            "%s: %d facts extracted (%d chars).",
            self.spec.name,
            len(result.facts),
            len(brief),
        )

        return {
            "text": brief,
            # The raw facts are kept alongside the rendered brief so a caller
            # can group or filter them without re-parsing the text.
            "pre_consultation_facts": result.facts,
            "corti_call": result.as_call(self.spec.name),
        }
