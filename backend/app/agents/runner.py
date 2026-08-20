"""Running agents from an API request.

One entry point for every caller: an endpoint hands over a case (or a stored
document) and the name of the agent it needs, and gets that agent's reply
back. Sequences are the same call with more than one name.

There is deliberately no per-flow wrapper. The agents are the shared thing —
upload, the analysis endpoints and the orchestrator all run the *same*
`case_data_extractor`, the same `case_summariser` — so a new flow is a new
list of names here, never a new agent.

    reply  = await run_agent("case_summariser", state)
    result = await run_agents(["referral_document_reader",
                              "case_data_extractor"], state)
"""

import logging
from typing import Any

from bson import ObjectId

from app.agents import AGENTS
from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import case as case_model
from app.models import patient as patient_model
from app.models import surgery as surgery_model

logger = logging.getLogger(__name__)


def flags_to_text(flags: list[dict] | None) -> str:
    """Render stored flags back into the prose the agents read."""
    parts = []
    for flag in flags or []:
        rationale = str(flag.get("rationale") or flag.get("label") or "").strip()
        severity = str(flag.get("severity") or "").strip()
        if rationale:
            parts.append(f"{rationale} ({severity})" if severity else rationale)
    return " ".join(parts)


async def build_case_state(case_id: str) -> dict[str, Any]:
    """The state an agent expects when working on a stored case.

    Loads the case, its appointments and its surgeries once, so every agent in
    a request reasons over the same records — the job the orchestrator does
    inside a graph run.
    """
    if not ObjectId.is_valid(case_id):
        raise ValueError(f"{case_id!r} is not a valid case id.")

    oid = ObjectId(case_id)
    case = await get_collection(case_model.COLLECTION).find_one({"_id": oid})
    if not case:
        raise LookupError(f"No case with id {case_id}.")

    patient = None
    if case.get("patient"):
        patient = await get_collection(patient_model.COLLECTION).find_one(
            {"_id": case["patient"]}
        )

    appointments = (
        await get_collection(appointment_model.COLLECTION)
        .find({"case": oid})
        .sort("start_time", 1)
        .to_list(length=100)
    )
    surgeries = (
        await get_collection(surgery_model.COLLECTION)
        .find({"case": oid})
        .to_list(length=100)
    )

    return {
        "case_id": case_id,
        # The letter the case was built from — the agents' source material.
        "referral_transcription": case.get("referral_document_content") or "",
        "case_summary": case.get("case_summary") or "",
        "flags": flags_to_text(case.get("flags")),
        "urgency_summary": case.get("urgency_reason") or "",
        "recommendation": case.get("recommendation") or "",
        "patient_name": (patient or {}).get("name", ""),
        "patient_age": str((patient or {}).get("age", "") or ""),
        "patient_gender": (patient or {}).get("gender", ""),
        # Allergies are part of the background now, not a field of their own.
        "clinical_background": (patient or {}).get("clinical_background") or "",
        # The Mongo records every agent sends to Corti as context.
        "case_document": case,
        "appointment_documents": appointments,
        "surgery_documents": surgeries,
    }


def _agent_class(name: str):
    try:
        return AGENTS[name]
    except KeyError:
        raise ValueError(
            f"Unknown agent {name!r}. Known agents: {', '.join(sorted(AGENTS))}."
        ) from None


async def run_agent(name: str, state: dict[str, Any]) -> dict[str, Any]:
    """Run one agent and return its reply, unchanged.

    Agents answer either with a state update (`case_data_extractor`) or with
    `{"text": ..., "corti_call": ...}`; both are handed back as-is so the
    caller decides what to keep.
    """
    reply = await _agent_class(name)().run(state) or {}
    if not isinstance(reply, dict):
        reply = {"text": str(reply)}

    logger.info(
        "Agent %s replied (%d chars).", name, len(str(reply.get("text", "")))
    )
    return reply


async def run_agents(
    names: list[str], state: dict[str, Any]
) -> dict[str, Any]:
    """Run agents in order, threading one state through them.

        {"state": ..., "corti_logs": {...}, "errors": [...]}

    A failing agent is recorded and the sequence continues: the later agents
    often still have something to work with, and the caller can see exactly
    which step gave up.
    """
    corti_logs: dict[str, Any] = {}
    errors: list[str] = []

    for name in names:
        try:
            reply = await run_agent(name, state)
        except Exception as exc:  # noqa: BLE001 — reported, not raised
            logger.exception("Agent %s failed", name)
            errors.append(f"{name}: {exc}")
            continue

        call = reply.pop("corti_call", None)
        if call:
            corti_logs[f"agent{len(corti_logs) + 1}"] = call

        # A text reply belongs to the field that agent owns; a state update
        # merges straight in.
        text = reply.pop("text", None)
        state.update(reply)
        if text is not None:
            state[f"{name}_text"] = text

    return {"state": state, "corti_logs": corti_logs, "errors": errors}
