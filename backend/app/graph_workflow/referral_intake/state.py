"""State for the referral intake workflow.

Self-contained by design: a workflow owns its state so it can evolve without
disturbing the other workflows that share the same agent roster.
"""

import operator
from typing import Annotated, Any, TypedDict


class CortiCall(TypedDict, total=False):
    """One agent's round trip to Corti, kept for the API response."""

    agent_name: str
    corti_request: Any
    corti_response: Any


def merge_corti_logs(
    existing: dict[str, CortiCall] | None, new: dict[str, CortiCall] | None
) -> dict[str, CortiCall]:
    """Append new Corti calls as `agent1`, `agent2`, … in call order.

    A reducer rather than a plain overwrite, so each agent's call is added to
    the record instead of replacing the previous agent's.
    """
    merged = dict(existing or {})
    for call in (new or {}).values():
        merged[f"agent{len(merged) + 1}"] = call
    return merged


class AgentError(TypedDict, total=False):
    """Structured failure report from an agent.

    `status_code` carries the upstream HTTP status when the failure came from
    an API call, which is what lets the router spot a 401 without parsing
    error text.
    """

    agent: str
    message: str
    status_code: int | None


class IntakeState(TypedDict, total=False):
    """State threaded through the fixed intake sequence."""

    # --- Inputs ---
    referral_id: str
    referral_text: str
    document_path: str | None
    # Set when triaging against an existing case; the orchestrator loads the
    # records below from Mongo and every agent sends them to Corti.
    case_id: str | None

    # --- Case records, loaded once by the orchestrator ---
    case_document: dict[str, Any] | None
    appointment_documents: list[dict[str, Any]]
    surgery_documents: list[dict[str, Any]]
    case_context_loaded: bool

    # --- Corti session (one login per run) ---
    corti_access_token: str | None
    corti_authenticated: bool
    corti_auth_error: str | None
    auth_retry_count: int
    # Step to resume once re-authentication succeeds.
    pending_step: str | None

    # --- referral_document_reader ---
    referral_transcription: str
    page_count: int
    is_scanned: bool

    # --- Agent output, flattened onto the response contract ---
    # The referral orchestrator maps each agent's reply into these fields:
    # `case_data_extractor` returns the four patient values as a dict, every
    # other agent returns a text message that fills exactly one field.
    patient_name: str  # case_data_extractor
    patient_age: str  # case_data_extractor
    patient_gender: str  # case_data_extractor
    patient_contact: str  # case_data_extractor
    referred_by: dict[str, str]  # case_data_extractor (name, role, organisation)
    referred_to_consultant: str  # case_data_extractor — who the letter names
    case_summary: str  # case_summariser
    flags: str  # clinical_flag_detector
    recommendation: str  # next_action_recommender
    # Urgency is kept in state but is not part of the returned JSON.
    urgency_summary: str  # urgency_assessor
    # Pre-consultation brief, from Corti fact extraction.
    pre_consultation_facts: list[dict[str, Any]]  # the raw facts behind it

    # The assembled JSON payload returned to the caller.
    referral_output: dict[str, str]

    # --- Extras an agent may record alongside its message ---
    symptoms: list[str]
    clinical_background: str | None
    consultant_team_id: str | None

    # --- Routing (written by the referral orchestrator) ---
    next_agent: str
    routing_reason: str

    # --- Progress / diagnostics ---
    completed_agents: Annotated[list[str], operator.add]
    step_count: int
    results: dict[str, Any]
    # Every Corti call made during the run, in order.
    corti_logs: Annotated[dict[str, CortiCall], merge_corti_logs]
    # The agent that just ran and the raw reply it gave, so the orchestrator
    # can log what each step produced before deciding the next one.
    last_agent: str | None
    last_agent_output: Any
    last_error: AgentError | None
    errors: Annotated[list[str], operator.add]


def new_state(
    referral_id: str,
    referral_text: str = "",
    document_path: str | None = None,
    case_id: str | None = None,
) -> IntakeState:
    """Build the initial state for an intake run."""
    return IntakeState(
        referral_id=referral_id,
        referral_text=referral_text,
        document_path=document_path,
        case_id=case_id,
        case_document=None,
        appointment_documents=[],
        surgery_documents=[],
        case_context_loaded=False,
        corti_access_token=None,
        corti_authenticated=False,
        corti_auth_error=None,
        auth_retry_count=0,
        pending_step=None,
        referral_transcription="",
        page_count=0,
        is_scanned=False,
        symptoms=[],
        referral_output={},
        completed_agents=[],
        step_count=0,
        results={},
        corti_logs={},
        last_agent=None,
        last_agent_output=None,
        last_error=None,
        errors=[],
    )
