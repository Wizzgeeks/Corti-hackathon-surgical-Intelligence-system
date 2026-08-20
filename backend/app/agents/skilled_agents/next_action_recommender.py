"""Next Action Recommender — unchanged."""

import logging

from app.agents.base import Agent, AgentSpec, AgentState
from app.services.corti_textgen import case_context_blocks, generate_text

logger = logging.getLogger(__name__)

# The prompts behind this agent's Corti text generation call.
TEMPLATE_NAME = "Referral next actions"
SECTION_HEADING = "Recommended next action"
TEMPLATE_PROMPT = (
    "You decide what happens next to a triaged referral. This is decision "
    "support for a clinician, who makes the final call."
)
CONTENT_PROMPT = (
    "Recommend the concrete next steps for this case: the investigations "
    "to arrange before the appointment, the clinic to book and by when, "
    "and any information to chase from the referrer. Recommend actions, "
    "not a restatement of the findings."
)
WRITING_STYLE_PROMPT = (
    "Two to four plain sentences, each an actionable step. No bullet "
    "points or headings."
)


class NextActionRecommender(Agent):
    """Recommends what should happen to this case next.

    Turns the summary, urgency, and flags into a concrete next step — the
    investigation to order, the clinic to book, the information to chase —
    rather than a restatement of the findings.
    """

    spec = AgentSpec(
        name="next_action_recommender",
        title="Next Action Recommender",
        purpose="Recommend the concrete next step for the case.",
        consumes=("case_summary", "flags", "urgency_summary"),
        produces=("recommendation",),
    )

    def build_context(self, state: AgentState) -> str:
        """Assemble what this agent needs Corti to reason over.

        Always starts with the case, appointment and surgery records the
        orchestrator loaded, so every agent reasons over the same source.
        """
        parts = [*case_context_blocks(state)]
        for label, key in (
            ("Case summary", "case_summary"),
            ("Clinical flags", "flags"),
            ("Urgency", "urgency_summary"),
        ):
            if state.get(key):
                parts.append(f"{label}: {state[key]}")
        return "\n\n".join(parts)

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
