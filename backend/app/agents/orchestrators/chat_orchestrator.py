"""Chat Orchestrator — decides which agent runs next.

Routing happens in two tiers:

1. **Deterministic rules** (`decide_deterministically`) — plain code, no LLM.
   Auth handling lives here: a `401` from any agent sends the run back to the
   Corti Authenticator and then resumes the agent that failed. This must never
   depend on a model call — it is a control-flow decision with one correct
   answer, and it has to keep working when the LLM itself is unreachable.
2. **LLM routing** — only consulted when no deterministic rule applies, to
   pick the next clinical step from the state so far.
"""

import logging
from dataclasses import dataclass

from app.agents.base import Agent, AgentSpec
from app.agents.skilled_agents import WORKER_CLASSES
from app.graph_workflow.chat_orchestration.state import TriageState

logger = logging.getLogger(__name__)

# Returned as `next_agent` when the pipeline has nothing left to do.
DONE = "done"

CHAT_ORCHESTRATOR_NAME = "chat_orchestrator"

# Node name of the agent that establishes Corti access.
AUTH_AGENT = "corti_authenticator"

# How many times one run may re-authenticate before giving up. Guards against
# a permanently-rejected credential looping auth -> agent -> 401 -> auth.
MAX_AUTH_RETRIES = 2

UNAUTHORIZED = 401


@dataclass(frozen=True)
class Decision:
    """A routing decision, plus whether it ends the run in failure."""

    next_agent: str
    reason: str
    # True when the run is stopping because something went wrong, as opposed
    # to finishing normally. Failures are surfaced to the API layer via
    # `errors` / `last_error`, not just as a routing reason.
    is_failure: bool = False

    def to_update(self) -> dict:
        """Partial state update this decision implies."""
        update: dict = {"next_agent": self.next_agent, "routing_reason": self.reason}
        if self.is_failure:
            update["errors"] = [f"{CHAT_ORCHESTRATOR_NAME}: {self.reason}"]
            update["last_error"] = {
                "agent": CHAT_ORCHESTRATOR_NAME,
                "message": self.reason,
                "status_code": None,
            }
        return update


def is_unauthorized(state: TriageState) -> bool:
    """True when the most recent agent failure was an auth rejection."""
    error = state.get("last_error") or {}
    return error.get("status_code") == UNAUTHORIZED


def decide_deterministically(state: TriageState) -> Decision | None:
    """Route without an LLM where the answer is fixed.

    Returns a `Decision`, or `None` when the decision needs the model.
    """
    # 0. Nothing to triage -> stop before spending a single call.
    #    The orchestrator is the graph's entry point, so input validation
    #    happens here rather than in a separate node.
    if not (state.get("referral_text") or "").strip():
        return Decision(
            DONE, "No referral text supplied; nothing to triage.", is_failure=True
        )

    # 1. No Corti session yet -> authenticate before anything else.
    if not state.get("corti_access_token"):
        if state.get("auth_retry_count", 0) == 0:
            return Decision(
                AUTH_AGENT, "No Corti token in state; authenticating first."
            )

    # 2. An agent came back 401 -> the token expired or was rejected.
    #    Re-authenticate, then resume the agent that failed.
    if is_unauthorized(state):
        retries = state.get("auth_retry_count", 0)
        if retries >= MAX_AUTH_RETRIES:
            return Decision(
                DONE,
                f"Corti authentication failed {retries} times; stopping the run.",
                is_failure=True,
            )
        failed_agent = (state.get("last_error") or {}).get("agent")
        return Decision(
            AUTH_AGENT,
            f"{failed_agent or 'An agent'} returned 401; re-authenticating "
            f"(attempt {retries + 1} of {MAX_AUTH_RETRIES}).",
        )

    # 2b. Any other failure -> stop. Without this the run would keep handing
    #     control back to the agent that just failed, since a failed agent is
    #     never marked complete.
    if state.get("last_error"):
        error = state["last_error"]
        return Decision(
            DONE,
            f"{error.get('agent')} failed: {error.get('message')}",
            is_failure=True,
        )

    # 3. Just re-authenticated with an agent waiting -> resume it.
    pending = state.get("pending_agent")
    if pending and state.get("corti_access_token"):
        return Decision(pending, f"Re-authenticated; resuming {pending}.")

    # 4. Authentication is exhausted and still failing -> stop.
    if state.get("corti_auth_error") and not state.get("corti_access_token"):
        return Decision(
            DONE,
            f"Cannot authenticate with Corti: {state['corti_auth_error']}",
            is_failure=True,
        )

    # Nothing forced — let the LLM choose the next clinical step.
    return None


class ChatOrchestrator(Agent):
    """Chooses the next agent action instead of following a fixed pipeline.

    It is the graph's entry point: the run starts here, and control returns
    here after every other agent. It looks at what the state already holds and
    what is still missing, and names the agent that should run next — or
    `DONE` when the case is fully triaged. Short-circuiting also lives here:
    a document that is not a referral, or a case that cannot be read, ends the
    run without visiting the remaining agents.

    `run()` must consult `decide_deterministically()` first and only fall
    through to the LLM when it returns `None`. Apply the returned decision
    with `Decision.to_update()` — that is what records a terminal failure in
    `errors` / `last_error` so the API layer can surface it, rather than
    leaving it buried in `routing_reason`.

    `next_agent` must be an agent name from the roster (`AGENTS`) or `DONE`;
    the graph's conditional edge routes on that value.
    """

    async def run(self, state: TriageState) -> dict:
        """Decide the next agent.

        Deterministic rules win; only when none applies does the choice fall
        to the model.

        STUB: the LLM tier is not wired up yet, so the fallback walks the
        skilled agents in their declared order — enough to exercise the graph
        end to end without pretending to reason about the case.
        """
        decision = decide_deterministically(state)

        if decision is None:
            decision = self._next_unvisited(state)

        logger.info("chat routing -> %s (%s)", decision.next_agent, decision.reason)
        return decision.to_update()

    @staticmethod
    def _next_unvisited(state: TriageState) -> Decision:
        """Placeholder for LLM routing: first agent that has not run yet."""
        visited = set(state.get("completed_agents") or [])
        for agent_cls in WORKER_CLASSES:
            name = agent_cls.spec.name
            if name not in visited:
                return Decision(name, f"Next unvisited agent: {name}.")
        return Decision(DONE, "All agents have run.")

    spec = AgentSpec(
        name=CHAT_ORCHESTRATOR_NAME,
        title="Chat Orchestrator",
        purpose=(
            "Decide which agent runs next based on the current triage state, "
            "handle Corti auth failures deterministically, or end the run."
        ),
        consumes=(
            "referral_text",
            "results",
            "errors",
            "last_error",
            "corti_access_token",
            "auth_retry_count",
            "pending_agent",
            "completed_agents",
        ),
        produces=(
            "next_agent",
            "routing_reason",
            "pending_agent",
            "errors",
            "last_error",
        ),
    )
