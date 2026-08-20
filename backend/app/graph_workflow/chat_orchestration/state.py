"""Shared state that flows through the orchestration graph.

Every node receives this dict and returns a partial update, which LangGraph
merges back in. Add fields here as each step of the pipeline is defined.
"""

import operator
from typing import Annotated, Any, TypedDict


class AgentError(TypedDict, total=False):
    """Structured failure report from an agent.

    `status_code` carries the upstream HTTP status when the failure came from
    an API call, which is what lets the orchestrator spot a 401 without
    parsing error text.
    """

    agent: str
    message: str
    status_code: int | None


class TriageState(TypedDict, total=False):
    """State for the referral triage graph."""

    # --- Inputs ---
    referral_id: str
    referral_text: str
    # Path to the stored referral PDF. The document reader falls back to the
    # conventional upload location when this is not set.
    document_path: str | None

    # --- Document (written by the referral document reader) ---
    # Text extracted from the referral PDF; every downstream clinical agent
    # reads this rather than touching the file again.
    referral_transcription: str
    page_count: int
    # True when the PDF yielded no text at all — an image-only/scanned letter.
    is_scanned: bool

    # --- Corti session (lives for one workflow run only) ---
    # The access token is carried here so agents in this run share one login
    # instead of re-authenticating per call. It is never persisted beyond the
    # run, and Corti tokens expire in ~5 minutes.
    corti_access_token: str | None
    corti_authenticated: bool
    corti_auth_error: str | None
    auth_retry_count: int

    # --- Routing (written by the orchestrator) ---
    next_agent: str
    routing_reason: str
    # Agent to resume once re-authentication succeeds.
    pending_agent: str | None
    completed_agents: Annotated[list[str], operator.add]
    # Number of agent hops taken; guards against an orchestrator that keeps
    # routing forever.
    step_count: int

    # --- Working data (populated by agents as they are added) ---
    results: dict[str, Any]

    # --- Diagnostics ---
    # Most recent failure, kept structured so routing can act on it.
    last_error: AgentError | None
    # Annotated with operator.add so parallel branches append rather than
    # overwrite each other's errors.
    errors: Annotated[list[str], operator.add]


def new_state(
    referral_id: str,
    referral_text: str = "",
    document_path: str | None = None,
) -> TriageState:
    """Build the initial state for a graph run."""
    return TriageState(
        referral_id=referral_id,
        referral_text=referral_text,
        document_path=document_path,
        referral_transcription="",
        page_count=0,
        is_scanned=False,
        corti_access_token=None,
        corti_authenticated=False,
        corti_auth_error=None,
        auth_retry_count=0,
        pending_agent=None,
        completed_agents=[],
        step_count=0,
        results={},
        last_error=None,
        errors=[],
    )
