"""Clinical Flag Detector — was "flags identifier"."""

import logging

from app.agents.base import Agent, AgentSpec, AgentState
from app.services.corti_textgen import case_context_blocks, generate_text

logger = logging.getLogger(__name__)

# The prompts behind this agent's Corti text generation call.
TEMPLATE_NAME = "Referral clinical flags"
SECTION_HEADING = "Clinical flags"
TEMPLATE_PROMPT = (
    "You review clinical referrals for a triaging consultant and surface "
    "concerns they must not miss. This is decision support for a "
    "clinician, not a diagnosis."
)
CONTENT_PROMPT = (
    "List the clinical flags this referral raises. One flag per sentence: "
    "state the concern, give its severity in brackets as (low), "
    "(medium), (high) or (critical), and say in the same sentence why it "
    "matters. Cover red flags, safeguarding concerns, medication risks, "
    "and diagnostic uncertainty. Only raise what the letter supports; if "
    "there are no flags, say so plainly."
)
WRITING_STYLE_PROMPT = (
    "Plain sentences, no bullet points or headings."
)


class ClinicalFlagDetector(Agent):
    """Surfaces specific concerns a reviewing clinician must not miss.

    Raises individual flags — red flags, safeguarding concerns, medication
    risks, diagnostic uncertainty — each with a severity and a one-line
    rationale, rather than a single overall verdict.
    """

    spec = AgentSpec(
        name="clinical_flag_detector",
        title="Clinical Flag Detector",
        purpose="Detect and rate individual clinical flags raised by the referral.",
        consumes=("referral_transcription", "case_summary"),
        produces=("flags",),
    )

    def build_context(self, state: AgentState) -> str:
        """Assemble what this agent needs Corti to reason over.

        Always starts with the case, appointment and surgery records the
        orchestrator loaded, so every agent reasons over the same source.
        """
        parts = [*case_context_blocks(state), state.get("referral_transcription") or state.get("referral_text") or ""]
        if state.get("case_summary"):
            parts.append(f"Case summary: {state['case_summary']}")
        if state.get("allergies"):
            parts.append(f"Allergies: {state['allergies']}")
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
