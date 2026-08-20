"""Urgency Assessor — was "urgency identifier".

Backed by a **Corti agentic agent** rather than text generation: the agent is
created and configured in the Corti Console (prompt, connectors, MCP tools),
and this class only sends it the case and reads the reply. Change how urgency
is judged by editing the agent in Corti, not this file.

**Currently stubbed.** `USE_DUMMY_RESPONSE` short-circuits the Corti call and
returns `DUMMY_RESPONSE`, so the pipeline runs end to end while the agent is
unreachable from these credentials. Set `CORTI_URGENCY_AGENT_DUMMY=false` (or
flip the constant) to call the real agent — `send_agent_message` below is the
live path and is left intact.
"""

import logging

from app.agents.base import Agent, AgentSpec, AgentState
from app.core.config import settings
from app.services.corti_agents import send_agent_message
from app.services.corti_textgen import case_context_blocks

logger = logging.getLogger(__name__)

# Testing switch: skip the Corti agent and answer from `DUMMY_RESPONSE`.
USE_DUMMY_RESPONSE = settings.corti_urgency_agent_dummy

# Fixed content, deliberately generic — it is not derived from the case in
# front of it, and must never be mistaken for a real assessment.
DUMMY_RESPONSE = (
    "Urgent. [DUMMY RESPONSE — the Corti urgency agent was not called.] The "
    "referral describes a persistent complaint that has not responded to "
    "conservative management, alongside a flag that is not explained by the "
    "presenting problem. Recommend review within two weeks rather than the "
    "routine wait."
)

# What the agent is asked to do. The agent's own system prompt lives in Corti;
# this is the per-case instruction that accompanies the record.
TASK_INSTRUCTION = (
    "Assess how urgently this referral needs to be seen. State whether it is "
    "urgent or routine, give the clinical reason in one or two sentences, and "
    "suggest a timeframe for review."
)


class UrgencyAssessor(Agent):
    """Decides how fast this case needs to be seen.

    Determines whether the referral needs review sooner than a routine
    appointment, and states the clinical reason for that decision.
    """

    spec = AgentSpec(
        name="urgency_assessor",
        title="Urgency Assessor",
        purpose="Assess triage urgency and give the reason behind it.",
        consumes=("case_summary", "flags", "corti_access_token"),
        produces=("urgency_summary",),
    )

    def build_context(self, state: AgentState) -> str:
        """Assemble the message sent to the Corti agent.

        Always starts with the case, appointment and surgery records the
        orchestrator loaded, so the agent reasons over the same source as the
        rest of the pipeline.
        """
        parts = [*case_context_blocks(state)]
        if state.get("case_summary"):
            parts.append(f"Case summary: {state['case_summary']}")
        if state.get("flags"):
            parts.append(f"Clinical flags: {state['flags']}")
        if not parts:
            parts.append(
                state.get("referral_transcription") or state.get("referral_text") or ""
            )
        parts.append(TASK_INSTRUCTION)
        return "\n\n".join(p for p in parts if p)

    async def run(self, state: AgentState) -> dict:
        """Ask the Corti agent and return its answer as a text message."""
        context = self.build_context(state)
        if not context.strip():
            logger.warning("%s: no context to work from.", self.spec.name)
            return {"text": ""}

        if USE_DUMMY_RESPONSE:
            logger.warning(
                "%s: DUMMY response — Corti agent %s not called.",
                self.spec.name,
                settings.corti_urgency_agent_id,
            )
            return {
                "text": DUMMY_RESPONSE,
                # Recorded like a real exchange so `corti_logs` still shows
                # what would have been sent, and that nothing was.
                "corti_call": {
                    "agent_name": self.spec.name,
                    "corti_request": {
                        "stubbed": True,
                        "agent_id": settings.corti_urgency_agent_id,
                        "message": context,
                    },
                    "corti_response": {"stubbed": True, "text": DUMMY_RESPONSE},
                },
            }

        result = await send_agent_message(
            agent_id=settings.corti_urgency_agent_id,
            text=context,
            # The token the run already holds; a 401 routes back through the
            # authenticator and resumes here.
            access_token=state.get("corti_access_token"),
            # Keeps a multi-turn conversation on one Corti context when the
            # workflow revisits this agent.
            context_id=state.get("urgency_context_id") or None,
        )

        logger.info("%s: agent replied with %d chars.", self.spec.name, len(result.text))
        return {
            "text": result.text,
            "corti_call": result.as_call(self.spec.name),
        }
