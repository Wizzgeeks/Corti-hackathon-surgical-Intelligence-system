"""Regenerate one part of a case with its agent.

Each endpoint runs a single Corti-backed agent against a stored case and, by
default, writes the result back. Use them when a clinician wants a section
redone — the summary rewritten, the flags re-checked — without re-running the
whole pipeline.

    POST /cases/{case_id}/summary

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a1197d7beaa80e15d57/summary'

    200 {
      "case_id": "6a855a1197d7beaa80e15d57",
      "agent": "case_summariser",
      "field": "case_summary",
      "value": "47-year-old woman with right ulnar wrist pain since June 2024...",
      "persisted": true,
      "corti_log": {"agent_name": "case_summariser", "corti_request": {}, "corti_response": {}},
      "errors": []
    }

    POST /cases/{case_id}/flags

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a.../flags'

    200 { "field": "flags", "value": "Diagnostic uncertainty (medium)...",
          "flags": [{"label": "...", "severity": "medium", "rationale": "..."}],
          "persisted": true, ... }

    POST /cases/{case_id}/urgency

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a.../urgency'

    200 { "field": "urgency_reason", "value": "Urgent. Unexplained weight loss...",
          "is_urgent": true, "persisted": true, ... }

    POST /cases/{case_id}/recommendation

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a.../recommendation'

    200 { "field": "recommendation", "value": "Arrange an MRI before the first
          appointment...", "persisted": true, ... }

    All four accept an optional body to steer the re-run and to skip saving:

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a.../flags' \
      -H 'Content-Type: application/json' \
      -d '{"instruction": "Pay particular attention to the weight loss.",
           "persist": false}'

    400 invalid case id · 404 unknown case · 502 the agent or Corti failed
"""

import logging
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.runner import build_case_state, run_agent
from app.db.mongodb import get_collection
from app.models import case as case_model
from app.models.case import Flag
from app.models.common import utcnow
from app.models.enums import FlagSeverity

logger = logging.getLogger(__name__)

router = APIRouter(tags=["case analysis"])

FLAGS_LABEL = "Referral flags"

# Wording the urgency agent opens with. It is asked to lead with the verdict,
# so the first word decides — anything else leaves the flag untouched.
URGENT_PREFIXES = ("urgent", "yes", "immediate", "emergency")
ROUTINE_PREFIXES = ("routine", "no", "non-urgent", "not urgent")


class AnalysisRequest(BaseModel):
    """Optional steering for a re-run."""

    # Appended to the agent's context, e.g. "focus on the weight loss".
    instruction: str = ""
    # False returns the agent's answer without writing it to the case.
    persist: bool = True


class AnalysisResponse(BaseModel):
    case_id: str
    agent: str
    # The case field this endpoint owns.
    field: str
    value: str
    persisted: bool = False
    # Set by the endpoints that derive more than a string.
    flags: list[Flag] | None = None
    is_urgent: bool | None = None
    # The Corti exchange behind the answer, for debugging in the frontend.
    corti_log: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


def split_title(text: str) -> tuple[str, str]:
    """Split the summariser's reply into title and body.

    Its convention is a title line, a blank line, then the summary; a reply
    without that separator is all summary.
    """
    if "\n\n" in text:
        title, _, body = text.partition("\n\n")
        return title.strip(), body.strip()
    return "", text.strip()


def text_to_flags(text: str) -> list[Flag]:
    """Wrap the detector's prose as a single stored flag.

    The agent answers in sentences; `Case.flags` is a list. One flag holding
    the whole reply keeps the clinician's text intact rather than guessing at
    sentence boundaries.
    """
    text = (text or "").strip()
    if not text:
        return []
    return [Flag(label=FLAGS_LABEL, severity=FlagSeverity.MEDIUM, rationale=text)]


def read_urgency(text: str) -> bool | None:
    """Read the verdict from the urgency agent's opening word.

    `None` when it cannot be told — better to leave the stored flag alone than
    to guess from prose.
    """
    opening = (text or "").strip().lower().lstrip("*# ").replace("**", "")
    if opening.startswith(URGENT_PREFIXES):
        return True
    if opening.startswith(ROUTINE_PREFIXES):
        return False
    return None


async def _run(agent_name: str, case_id: str, payload: AnalysisRequest) -> dict:
    """Load the case, run the one agent this endpoint owns, return its reply."""
    try:
        state = await build_case_state(case_id)
        if payload.instruction.strip():
            state["extra_instruction"] = payload.instruction.strip()

        reply = await run_agent(agent_name, state)
        return {
            "agent": agent_name,
            "text": reply.get("text", ""),
            "corti_call": reply.get("corti_call"),
        }
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — upstream (Corti) failure
        logger.exception("%s failed for case %s", agent_name, case_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"{agent_name} failed: {exc}"
        ) from exc


async def _save(case_id: str, update: dict) -> None:
    """Write the regenerated field(s) back to the case."""
    await get_collection(case_model.COLLECTION).update_one(
        {"_id": ObjectId(case_id)}, {"$set": {**update, "updated_at": utcnow()}}
    )


@router.post("/cases/{case_id}/summary", response_model=AnalysisResponse)
async def update_summary(
    case_id: str, payload: AnalysisRequest = AnalysisRequest()
) -> AnalysisResponse:
    """Rewrite the case summary with the summariser agent."""
    result = await _run("case_summariser", case_id, payload)
    # The summariser still opens with a one-line title; it is dropped, since
    # a case no longer carries one.
    _, summary = split_title(result["text"])

    persisted = False
    if payload.persist and summary:
        await _save(case_id, {"case_summary": summary})
        persisted = True

    return AnalysisResponse(
        case_id=case_id,
        agent=result["agent"],
        field="case_summary",
        value=summary,
        persisted=persisted,
        corti_log=result["corti_call"],
        errors=[] if summary else ["case_summariser returned nothing."],
    )


@router.post("/cases/{case_id}/flags", response_model=AnalysisResponse)
async def update_flags(
    case_id: str, payload: AnalysisRequest = AnalysisRequest()
) -> AnalysisResponse:
    """Re-check the clinical flags with the flag detector agent."""
    result = await _run("clinical_flag_detector", case_id, payload)
    flags = text_to_flags(result["text"])

    persisted = False
    if payload.persist and flags:
        await _save(case_id, {"flags": [f.model_dump() for f in flags]})
        persisted = True

    return AnalysisResponse(
        case_id=case_id,
        agent=result["agent"],
        field="flags",
        value=result["text"],
        flags=flags,
        persisted=persisted,
        corti_log=result["corti_call"],
        errors=[] if flags else ["clinical_flag_detector returned nothing."],
    )


@router.post("/cases/{case_id}/urgency", response_model=AnalysisResponse)
async def update_urgency(
    case_id: str, payload: AnalysisRequest = AnalysisRequest()
) -> AnalysisResponse:
    """Reassess urgency with the urgency agent."""
    result = await _run("urgency_assessor", case_id, payload)
    text = result["text"]
    is_urgent = read_urgency(text)

    errors = []
    if text and is_urgent is None:
        errors.append(
            "Could not read a verdict from the reply; is_urgent left unchanged."
        )

    persisted = False
    if payload.persist and text:
        update: dict[str, Any] = {"urgency_reason": text}
        if is_urgent is not None:
            update["is_urgent"] = is_urgent
        await _save(case_id, update)
        persisted = True

    return AnalysisResponse(
        case_id=case_id,
        agent=result["agent"],
        field="urgency_reason",
        value=text,
        is_urgent=is_urgent,
        persisted=persisted,
        corti_log=result["corti_call"],
        errors=errors or ([] if text else ["urgency_assessor returned nothing."]),
    )


@router.post("/cases/{case_id}/recommendation", response_model=AnalysisResponse)
async def update_recommendation(
    case_id: str, payload: AnalysisRequest = AnalysisRequest()
) -> AnalysisResponse:
    """Regenerate the recommended next action."""
    result = await _run("next_action_recommender", case_id, payload)
    text = result["text"]

    persisted = False
    if payload.persist and text:
        await _save(case_id, {"recommendation": text})
        persisted = True

    return AnalysisResponse(
        case_id=case_id,
        agent=result["agent"],
        field="recommendation",
        value=text,
        persisted=persisted,
        corti_log=result["corti_call"],
        errors=[] if text else ["next_action_recommender returned nothing."],
    )
