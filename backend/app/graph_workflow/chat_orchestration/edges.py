"""Edges — how control moves between nodes.

The graph is orchestrator-driven rather than a fixed chain. The orchestrator
is the entry point and control returns to it after every agent:

    START -> orchestrator -> <agent> -> orchestrator -> ... -> END

`EDGES` holds the fixed wiring (every agent returning to the orchestrator).
`CONDITIONAL_EDGES` holds the one branch point: the orchestrator's choice of
`next_agent`.
"""

import logging

from langgraph.graph import END

from app.agents import DISPATCHABLE_CLASSES, ROUTABLE_AGENTS
from app.agents.orchestrators import DONE
from app.graph_workflow.chat_orchestration.nodes import ORCHESTRATOR
from app.graph_workflow.chat_orchestration.state import TriageState

logger = logging.getLogger(__name__)

ORCHESTRATOR_NODE = ORCHESTRATOR.spec.name

# Hard ceiling on agent hops per run, so a mis-routing orchestrator cannot
# loop forever. Generous: ~10 agents plus re-auth detours.
MAX_STEPS = 30


def route_next_agent(state: TriageState) -> str:
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

    if next_agent not in ROUTABLE_AGENTS:
        logger.warning("Orchestrator returned unknown agent %r; ending run.", next_agent)
        return END

    return next_agent


def halt_on_error(state: TriageState) -> str:
    """Stop the run if a node has already recorded an error."""
    return END if state.get("errors") else "continue"


# Every agent the orchestrator can dispatch to (support agents first).
_DISPATCHABLE = DISPATCHABLE_CLASSES

# Fixed edges: every agent returns to the orchestrator so it decides again
# after each step. START -> orchestrator is wired in graph.py.
EDGES: dict[str, str] = {
    cls.spec.name: ORCHESTRATOR_NODE for cls in _DISPATCHABLE
}

# The single branch point: orchestrator -> chosen agent, or END.
CONDITIONAL_EDGES: dict[str, tuple] = {
    ORCHESTRATOR_NODE: (
        route_next_agent,
        {cls.spec.name: cls.spec.name for cls in _DISPATCHABLE} | {END: END},
    ),
}
