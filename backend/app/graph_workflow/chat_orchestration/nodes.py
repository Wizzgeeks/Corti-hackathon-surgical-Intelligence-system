"""Graph nodes.

Every agent in the roster becomes a node here. A node is an async callable
taking `TriageState` and returning a **partial** state update.

`make_agent_node()` is the only glue: it runs the agent and turns any failure
into a structured `last_error` (carrying the HTTP status when the failure came
from Corti) so the orchestrator can route on it — a 401 in particular.
"""

import logging
from collections.abc import Awaitable, Callable

from app.agents import DISPATCHABLE_CLASSES, Agent, ChatOrchestrator

# This workflow's control agent. Named explicitly: the agent library has
# several orchestrators and no default.
ORCHESTRATOR: type[Agent] = ChatOrchestrator
from app.graph_workflow.chat_orchestration.state import TriageState
from app.services.corti_client import CortiError

logger = logging.getLogger(__name__)

Node = Callable[[TriageState], Awaitable[dict]]

# The orchestrator is the graph's entry point — every run starts with it
# deciding what to do, including validating that there is anything to triage.
ENTRY_NODE = ORCHESTRATOR.spec.name


def record_error(node: str, exc: Exception) -> dict:
    """Uniform error shape for nodes to return when a step fails."""
    logger.exception("%s failed", node)
    status = exc.status_code if isinstance(exc, CortiError) else None
    return {
        "last_error": {"agent": node, "message": str(exc), "status_code": status},
        "errors": [f"{node}: {exc}"],
    }


def make_agent_node(agent_cls: type[Agent]) -> Node:
    """Wrap a roster agent as a graph node."""
    name = agent_cls.spec.name

    async def node(state: TriageState) -> dict:
        update: dict = {"step_count": state.get("step_count", 0) + 1}
        try:
            result = await agent_cls().run(state) or {}
        except Exception as exc:  # noqa: BLE001 — surfaced via last_error
            return {**update, **record_error(name, exc)}

        # Most agents reply with a state update, but the clinical ones reply
        # with a text message. This workflow keeps those under `results`,
        # keyed by agent, rather than flattening them onto named fields the
        # way referral intake does.
        if not isinstance(result, dict):
            result = {"results": {**(state.get("results") or {}), name: str(result)}}

        # A clean run clears the previous failure and records the visit.
        return {
            **update,
            "last_error": None,
            "completed_agents": [name],
            **result,
        }

    node.__name__ = f"{name}_node"
    return node


# Name -> callable: this workflow's orchestrator plus everything it can
# dispatch to. Other workflows' orchestrators are deliberately not nodes here.
NODES: dict[str, Node] = {
    cls.spec.name: make_agent_node(cls)
    for cls in (ORCHESTRATOR, *DISPATCHABLE_CLASSES)
}
