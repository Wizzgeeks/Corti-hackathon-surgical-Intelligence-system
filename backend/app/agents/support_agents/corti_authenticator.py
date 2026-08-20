"""Corti Authenticator — establishes Corti access for the run."""

import logging

from app.agents.base import Agent, AgentSpec
from app.graph_workflow.chat_orchestration.state import TriageState
from app.services.corti_client import CortiClient, CortiError

logger = logging.getLogger(__name__)


class CortiAuthenticator(Agent):
    """Confirms the run can talk to Corti before any Corti-backed agent starts.

    Calls the Corti login endpoint (OAuth2 client credentials) and puts the
    resulting access token into `corti_access_token`, so every Corti-backed
    agent in this run shares one login instead of authenticating per call.

    It is also the recovery point: when an agent gets a `401`, the orchestrator
    routes back here deterministically (no LLM), this agent mints a fresh
    token, and the failed agent is resumed. Each visit must clear
    `last_error` and increment `auth_retry_count` so the orchestrator can tell
    a retry from a first login and stop after `MAX_AUTH_RETRIES`.

    The token lives in graph state for the duration of one workflow run only —
    it is never persisted, and Corti tokens expire in ~5 minutes anyway.
    """

    spec = AgentSpec(
        name="corti_authenticator",
        title="Corti Authenticator",
        purpose=(
            "Obtain a Corti access token for the run and refresh it when an "
            "agent is rejected with 401."
        ),
        consumes=("auth_retry_count", "pending_agent", "last_error"),
        produces=(
            "corti_access_token",
            "corti_authenticated",
            "corti_auth_error",
            "auth_retry_count",
            "last_error",
        ),
    )

    async def run(self, state: TriageState) -> dict:
        """Mint a token and put it in state.

        A login failure is reported through `corti_auth_error` rather than
        raised: the node wrapper would turn a raised `CortiAuthError` into a
        `last_error` carrying Corti's status, and a 401 from the *login* call
        would then look to the orchestrator like an agent whose token expired,
        sending the run straight back here. Returning the failure instead means
        `auth_retry_count` is still incremented on the way out, so the retry
        ceiling actually applies.
        """
        # Counted per visit, not per success — the orchestrator uses it to stop
        # after MAX_AUTH_RETRIES rather than looping auth -> agent -> 401.
        attempt = state.get("auth_retry_count", 0) + 1
        base: dict = {"auth_retry_count": attempt, "last_error": None}

        try:
            # Construction validates that credentials are configured at all.
            token = await CortiClient().login()
        except CortiError as exc:
            logger.warning("Corti login failed on attempt %d: %s", attempt, exc)
            return {
                **base,
                "corti_access_token": None,
                "corti_authenticated": False,
                "corti_auth_error": str(exc),
            }

        logger.info("Corti login succeeded on attempt %d.", attempt)
        return {
            **base,
            "corti_access_token": token,
            "corti_authenticated": True,
            "corti_auth_error": None,
        }
