"""Edges for the referral intake workflow.

The referral orchestrator is the entry point and control returns to it after
every agent:

    START -> referral_orchestrator -> <agent> -> referral_orchestrator -> ... -> END

The sequence itself is fixed and lives in the orchestrator (`STEP_ORDER`), so
the only branch point here is its `next_agent` choice.
"""

import logging

from langgraph.graph import END

from app.agents.orchestrators.referral_orchestrator import DONE
from app.graph_workflow.referral_intake.nodes import (
    DISPATCHABLE_NAMES,
    ORCHESTRATOR_NODE,
)
from app.graph_workflow.referral_intake.state import IntakeState

logger = logging.getLogger(__name__)

# Hard ceiling on agent hops per run, so a mis-routing orchestrator cannot
# loop forever: 8 agents plus re-auth detours and the orchestrator's own turns.
MAX_STEPS = 30


def route_next_agent(state: IntakeState) -> str:
    """Send the run to whichever agent the orchestrator named.

    Anything unexpected — no decision, an unknown name, `DONE`, or the step
    budget exhausted — ends the run rather than guessing.
    """
    if state.get("step_count", 0) >= MAX_STEPS:
        logger.warning("Step budget (%d) exhausted; ending run.", MAX_STEPS)
        return END

    next_agent = state.get("next_agent")

    if not next_agent or next_agent == DONE:
        return END

    if next_agent not in DISPATCHABLE_NAMES:
        logger.warning("Orchestrator returned unknown agent %r; ending run.", next_agent)
        return END

    return next_agent


# Every agent returns to the orchestrator so it can map the reply and decide
# again. START -> orchestrator is wired in graph.py.
EDGES: dict[str, str] = {name: ORCHESTRATOR_NODE for name in DISPATCHABLE_NAMES}

# The single branch point: orchestrator -> chosen agent, or END.
CONDITIONAL_EDGES: dict[str, tuple] = {
    ORCHESTRATOR_NODE: (
        route_next_agent,
        {name: name for name in DISPATCHABLE_NAMES} | {END: END},
    ),
}
