"""Case Summariser — was "summary creator"."""

import logging

from app.agents.base import Agent, AgentSpec, AgentState
from app.services.corti_textgen import case_context_blocks, generate_text

logger = logging.getLogger(__name__)

# The prompts behind this agent's Corti text generation call.
TEMPLATE_NAME = "Referral case summary"
SECTION_HEADING = "Case summary"
TEMPLATE_PROMPT = (
    "You summarise clinical referral letters, case details, consultation details for a consultant who is "
    "triaging them. Use only what the letter states — never infer a "
    "diagnosis, finding, or history that is not written down."
)
CONTENT_PROMPT = (
    "Write the case summary. Open with a single title line naming the "
    "presenting problem and its duration, then a blank line, then two to "
    "four sentences covering: who the patient is, the presenting "
    "complaint and how long it has been going on, relevant background "
    "and medications, and what has already been tried."
)
WRITING_STYLE_PROMPT = (
    "Clinical prose a consultant can read at a glance. No headings, no "
    "bullet points, no preamble."
)


class CaseSummariser(Agent):
    """Writes the clinician-facing summary of the case.

    Produces a short case title and a concise narrative a consultant can read
    at a glance, grounded only in what the referral states.
    """

    spec = AgentSpec(
        name="case_summariser",
        title="Case Summariser",
        purpose="Write the case title and a concise clinical summary of the referral.",
        consumes=("referral_transcription", "patient_name", "patient_age"),
        produces=("case_summary",),
    )

    def build_context(self, state: AgentState) -> str:
        """Assemble what this agent needs Corti to reason over.

        Always starts with the case, appointment and surgery records the
        orchestrator loaded, so every agent reasons over the same source.
        """
        parts = [*case_context_blocks(state), state.get("referral_transcription") or state.get("referral_text") or ""]
        patient = ", ".join(
            str(state.get(f) or "") for f in ("patient_name", "patient_age", "patient_gender")
        ).strip(", ")
        if patient.strip(", "):
            parts.append(f"Known patient details: {patient}")
        return "\n\n".join(p for p in parts if p)

    async def run(self, state: AgentState) -> dict:
        """Generate the section and return it as a text message."""
        context = self.build_context(state)
        if not context.strip():
            logger.warning("%s: no context to work from.", self.spec.name)
            return {"text": ""}

        result = await generate_text(
            name=TEMPLATE_NAME,
            heading=SECTION_HEADING,
            prompt=TEMPLATE_PROMPT,
            content_prompt=CONTENT_PROMPT,
            writing_style_prompt=WRITING_STYLE_PROMPT,
            context_text=context,
            access_token=state.get("corti_access_token"),
        )

        logger.info("%s: generated %d chars.", self.spec.name, len(result.text))
        # `text` is the agent's message; `corti_call` is lifted into
        # `corti_logs` by the node wrapper.
        return {"text": result.text, "corti_call": result.as_call(self.spec.name)}
