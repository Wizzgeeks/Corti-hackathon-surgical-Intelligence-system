"""Nodes for the referral intake workflow.

The referral orchestrator is the entry point and control returns to it after
every agent, so it can fold each reply into state and decide the next step.

`make_agent_node()` is the glue: it runs the agent, hands the reply to the
orchestrator's `map_agent_output()` so text messages land in the right output
field, and turns any failure into a structured `last_error` — carrying the
HTTP status when it came from Corti, so a 401 is recognisable.
"""

import logging
from collections.abc import Awaitable, Callable

from app.agents import Agent
from app.agents.orchestrators.referral_orchestrator import (
    REFERRAL_ORCHESTRATOR_NAME,
    ReferralOrchestrator,
    map_agent_output,
)
from app.agents.skilled_agents import (
    CaseDataExtractor,
    CaseSummariser,
    ClinicalFlagDetector,
    NextActionRecommender,
    PreConsultationBriefer,
    ReferralDocumentReader,
    UrgencyAssessor,
)
from app.agents.support_agents import CortiAuthenticator
from app.graph_workflow.referral_intake.state import IntakeState
from app.services.corti_client import CortiError

logger = logging.getLogger(__name__)

Node = Callable[[IntakeState], Awaitable[dict]]

UNAUTHORIZED = 401

# The control agent: first to run, and re-entered after every step.
ORCHESTRATOR: type[Agent] = ReferralOrchestrator
ORCHESTRATOR_NODE = REFERRAL_ORCHESTRATOR_NAME
ENTRY_NODE = ORCHESTRATOR_NODE

# Corti access is established before any skilled agent runs.
AUTH_STEP: type[Agent] = CortiAuthenticator
AUTH_NODE = AUTH_STEP.spec.name

# The intake pipeline, in execution order.
SEQUENCE: tuple[type[Agent], ...] = (
    ReferralDocumentReader,
    CaseDataExtractor,
    CaseSummariser,
    ClinicalFlagDetector,
    UrgencyAssessor,
    NextActionRecommender,
    PreConsultationBriefer,
)
SEQUENCE_NAMES: tuple[str, ...] = tuple(cls.spec.name for cls in SEQUENCE)

# Everything the orchestrator can dispatch to.
DISPATCHABLE: tuple[type[Agent], ...] = (AUTH_STEP, *SEQUENCE)
DISPATCHABLE_NAMES: tuple[str, ...] = tuple(cls.spec.name for cls in DISPATCHABLE)


def record_error(node: str, exc: Exception) -> dict:
    """Uniform error shape for nodes to return when a step fails."""
    logger.exception("%s failed", node)
    status = exc.status_code if isinstance(exc, CortiError) else None
    update = {
        "last_error": {"agent": node, "message": str(exc), "status_code": status},
        "errors": [f"{node}: {exc}"],
    }
    # On a 401 the run detours through the authenticator; remember where to
    # come back to.
    if status == UNAUTHORIZED:
        update["pending_step"] = node
    return update


def make_agent_node(agent_cls: type[Agent]) -> Node:
    """Wrap an agent as a graph node."""
    name = agent_cls.spec.name
    is_control = name in (ORCHESTRATOR_NODE, AUTH_NODE)

    async def node(state: IntakeState) -> dict:
        update: dict = {"step_count": state.get("step_count", 0) + 1}
        try:
            result = await agent_cls().run(state) or {}
        except Exception as exc:  # noqa: BLE001 — surfaced via last_error
            return {**update, **record_error(name, exc)}

        # An agent that talked to Corti records the exchange under
        # `corti_call`; lift it into `corti_logs` so it is not mistaken for an
        # output field. The reducer on that key appends rather than replaces.
        corti_logs: dict = {}
        if isinstance(result, dict) and "corti_call" in result:
            result = dict(result)
            corti_logs = {"corti_logs": {name: result.pop("corti_call")}}

        # Text agents wrap their message as {"text": ...} so they can attach a
        # `corti_call` alongside it; unwrap so the mapping sees the message.
        extra: dict = {}
        if isinstance(result, dict) and "text" in result:
            extra = {k: v for k, v in result.items() if k != "text"}
            result = result["text"]

        # A skilled agent may reply with a plain message or dict instead of a
        # state update; the orchestrator decides which field it belongs in.
        reply = result
        mapped = {} if is_control else map_agent_output(name, result)
        if mapped:
            result = {}

        return {
            **update,
            "last_error": None,
            # Carry the raw reply forward so the orchestrator can log what
            # this step produced. Skipped for the orchestrator's own turns.
            **(
                {}
                if name == ORCHESTRATOR_NODE
                else {"last_agent": name, "last_agent_output": reply}
            ),
            # The authenticator must preserve `pending_step` — that is the
            # step it exists to send the run back to.
            **({} if name == AUTH_NODE else {"pending_step": None}),
            "completed_agents": [name],
            **corti_logs,
            **extra,
            **mapped,
            **(result if isinstance(result, dict) else {}),
        }

    node.__name__ = f"{name}_node"
    return node


# Name -> callable: the orchestrator plus everything it dispatches to.
NODES: dict[str, Node] = {
    cls.spec.name: make_agent_node(cls) for cls in (ORCHESTRATOR, *DISPATCHABLE)
}
