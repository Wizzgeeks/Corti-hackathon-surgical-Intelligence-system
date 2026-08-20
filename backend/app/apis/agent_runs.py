"""Running the Corti Console agents against a stored case.

Distinct from `case_analysis.py`, which runs our own agents: these are built
in the Corti Console and reach back into our MCP server for the record
themselves. We send an identifier, not the case — the urgency agent a patient
name, the summariser a case id — and they run concurrently.

    POST /update_agent_run

    curl -X POST 'http://127.0.0.1:8000/update_agent_run' \
      -H 'Content-Type: application/json' \
      -d '{"case_id": "6a870af1673e6e1622953190"}'

    200 {
      "case_id": "6a870af1673e6e1622953190",
      "agent": "urgency_identifier",
      "agent_id": "agt.d8a2e8a1-496d-4a55-a4cf-629ab61519f2",
      "patient_name": "Janelle Henderson",
      "recommendation": "ROUTINE",
      "is_urgent": false,
      "requires_clinician_escalation": false,
      "urgency_reason": "The referral describes a chronic, symptomatic TFCC tear
        with failed conservative treatment, but the picture is consistent with a
        stable elective condition rather than an urgent red-flag presentation.",
      "evidence": [
        "Referral documents a chronic right ulnar-sided wrist problem present
         for about 12 months after a FOOSH injury in Feb 2024.",
        "MRI confirms a peripheral ulnar-sided TFCC tear with adjacent oedema."
      ],
      "text": "{\"recommendation\":\"ROUTINE\",...}",
      "context_id": "01a01fab-5d38-7407-bc58-727236837668",
      "case_summary": "Right TFCC tear referral. Chronic right ulnar-sided
        wrist pain after FOOSH in February 2024...",
      "summary_points": ["Right TFCC tear referral...", "MRI 04/09/2024..."],
      "summary_context_id": "01a01fef-5022-7d85-ae8a-38bdfd548f34",
      "flags": [
        {"label": "Record-integrity discrepancy affecting triage",
         "severity": "medium",
         "rationale": "The case summary states fevers and night sweats, but
          these are not supported in the referral letter."}
      ],
      "flags_text": "MEDIUM - Record-integrity discrepancy affecting triage:...",
      "flag_context_id": "01a01ff8-...",
      "recommendation_text": "Book appointment with Dr. Ram Chandru. Based on
        his/her availability and booked slots, 21 August 2026 10:00-10:30 for a
        consultation would be appropriate.",
      "recommendation_steps": ["Book appointment with Dr. Ram Chandru..."],
      "recommendation_context_id": "01a0201c-...",
      "agents_run": ["urgency_identifier", "case_summariser", "flag_detector",
                     "next_action_recommender"],
      "persisted": true,
      "corti_logs": {
        "urgency_identifier": {"agent_name": "...", "corti_request": {},
                               "corti_response": {}},
        "case_summariser": {"agent_name": "...", "corti_request": {},
                            "corti_response": {}},
        "flag_detector": {"agent_name": "...", "corti_request": {},
                          "corti_response": {}},
        "next_action_recommender": {"agent_name": "...", "corti_request": {},
                                    "corti_response": {}}
      },
      "errors": []
    }

    All four agents run concurrently and each reads the case from our MCP
    server, so the call costs the slowest agent's latency rather than the sum.
    One failing is reported in `errors` while the others' answers are still
    returned and saved; only every agent failing is a 502.

    Run just one of them:

    curl -X POST 'http://127.0.0.1:8000/update_agent_run' \
      -H 'Content-Type: application/json' \
      -d '{"case_id": "6a870af...", "agents": ["case_summariser"]}'

    Steer the run, or see the answer without saving it:

    curl -X POST 'http://127.0.0.1:8000/update_agent_run' \
      -H 'Content-Type: application/json' \
      -d '{"case_id": "6a870af...", "persist": false,
           "instruction": "Weigh the reported weight loss heavily."}'

    400 invalid case id or an unknown agent name · 404 unknown case
    502 every agent asked for failed
"""

import asyncio
import logging
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.runner import build_case_state
from app.corti_agents.case_summariser import (
    CASE_SUMMARY_AGENT_ID,
    CaseSummaryReply,
)
from app.corti_agents.case_summariser import INSTRUCTION as SUMMARY_INSTRUCTION
from app.corti_agents.case_summariser import summarise_case
from app.corti_agents.flag_detector import FLAG_AGENT_ID, FlagReply
from app.corti_agents.flag_detector import INSTRUCTION as FLAG_INSTRUCTION
from app.corti_agents.flag_detector import detect_flags
from app.corti_agents.next_action_recommender import (
    NEXT_ACTION_AGENT_ID,
    NextActionReply,
)
from app.corti_agents.next_action_recommender import (
    INSTRUCTION as NEXT_ACTION_INSTRUCTION,
)
from app.corti_agents.next_action_recommender import recommend_next_action
from app.corti_agents.urgency_identifier import (
    URGENCY_AGENT_ID,
    UrgencyReply,
    identify_urgency,
)
from app.corti_agents.urgency_identifier import INSTRUCTION as URGENCY_INSTRUCTION
from app.db.mongodb import get_collection
from app.models import case as case_model
from app.models.case import Flag
from app.models.common import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent runs"])

AGENT_NAME = "urgency_identifier"
SUMMARY_AGENT_NAME = "case_summariser"
FLAG_AGENT_NAME = "flag_detector"
NEXT_ACTION_AGENT_NAME = "next_action_recommender"

ALL_AGENTS = (
    AGENT_NAME,
    SUMMARY_AGENT_NAME,
    FLAG_AGENT_NAME,
    NEXT_ACTION_AGENT_NAME,
)

# Grades the agent uses. Anything outside this map leaves the stored flag
# alone rather than guessing — the agent occasionally answers without one.
URGENT_GRADES = {"URGENT", "EMERGENCY", "IMMEDIATE", "TWO_WEEK_WAIT"}
ROUTINE_GRADES = {"ROUTINE", "NON_URGENT", "SOON"}


class AgentRunRequest(BaseModel):
    """Which case to run the agents over, and what to do with their answers."""

    case_id: str
    # Replaces the urgency agent's default instruction when set.
    instruction: str = ""
    # Replaces the summariser's default instruction when set.
    summary_instruction: str = ""
    # Replaces the flag agent's default instruction when set.
    flag_instruction: str = ""
    # Replaces the next-action agent's default instruction when set.
    next_action_instruction: str = ""
    # False returns the answers without writing them to the case.
    persist: bool = True
    # Continue an earlier conversation with the urgency agent.
    context_id: str | None = None
    # Which agents to run. Both by default; naming one skips the other.
    agents: list[str] | None = None


class AgentRunResponse(BaseModel):
    case_id: str
    agent: str = AGENT_NAME
    agent_id: str = URGENCY_AGENT_ID
    patient_name: str = ""
    recommendation: str = ""
    # None when the agent gave no grade we recognise — the case keeps the
    # urgency it already had.
    is_urgent: bool | None = None
    requires_clinician_escalation: bool = False
    urgency_reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    # The agent's reply verbatim, in case it answered outside the schema.
    text: str = ""
    context_id: str = ""

    # --- case_summariser ---
    # The write-up, and the same content split into its individual points.
    case_summary: str = ""
    summary_points: list[str] = Field(default_factory=list)
    summary_context_id: str = ""
    summary_agent_id: str = CASE_SUMMARY_AGENT_ID

    # --- flag_detector ---
    flags: list[Flag] = Field(default_factory=list)
    flags_text: str = ""
    flag_context_id: str = ""
    flag_agent_id: str = FLAG_AGENT_ID

    # --- next_action_recommender ---
    recommendation_text: str = ""
    recommendation_steps: list[str] = Field(default_factory=list)
    recommendation_context_id: str = ""
    next_action_agent_id: str = NEXT_ACTION_AGENT_ID

    # Which agents actually ran, in the order they were asked for.
    agents_run: list[str] = Field(default_factory=list)
    persisted: bool = False
    # The urgency exchange, kept for callers written before the summariser
    # existed; `corti_logs` carries both, keyed by agent name.
    corti_log: dict[str, Any] | None = None
    corti_logs: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


def grade_to_urgent(recommendation: str) -> bool | None:
    """Map the agent's grade onto the case's urgency flag."""
    grade = (recommendation or "").strip().upper().replace(" ", "_").replace("-", "_")
    if grade in URGENT_GRADES:
        return True
    if grade in ROUTINE_GRADES:
        return False
    return None


@router.post("/update_agent_run", response_model=AgentRunResponse)
async def update_agent_run(payload: AgentRunRequest) -> AgentRunResponse:
    """Run the Corti agents over a case and store what they decide.

    Every agent reaches into our MCP server for the record itself — the
    urgency agent by patient name, the others by case id, with the next-action
    agent also reading consultant availability — so they work from what is
    stored rather than what we would have chosen to send them. They are independent, so they run concurrently: the
    endpoint costs the slowest agent's latency rather than the sum.

    One agent failing does not fail the request. Its error is reported and
    whatever the others produced is still returned and saved; only every
    agent failing is a 502.
    """
    try:
        state = await build_case_state(payload.case_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    wanted = payload.agents or list(ALL_AGENTS)
    unknown = set(wanted) - set(ALL_AGENTS)
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown agent(s): {', '.join(sorted(unknown))}. "
                f"Known: {', '.join(ALL_AGENTS)}."
            ),
        )

    patient_name = (state.get("patient_name") or "").strip()
    errors: list[str] = []

    # The urgency agent searches by name, so without one it has nothing to
    # look up — but the summariser works from the case id and is unaffected.
    run_urgency = AGENT_NAME in wanted and bool(patient_name)
    if AGENT_NAME in wanted and not patient_name:
        errors.append(
            f"Case {payload.case_id} has no patient name, so "
            f"{AGENT_NAME} was skipped."
        )
    run_summary = SUMMARY_AGENT_NAME in wanted
    run_flags = FLAG_AGENT_NAME in wanted
    run_next_action = NEXT_ACTION_AGENT_NAME in wanted

    async def _urgency() -> UrgencyReply | None:
        if not run_urgency:
            return None
        return await identify_urgency(
            patient_name=patient_name,
            instruction=payload.instruction.strip() or URGENCY_INSTRUCTION,
            context_id=payload.context_id,
        )

    async def _summary() -> CaseSummaryReply | None:
        if not run_summary:
            return None
        return await summarise_case(
            case_id=payload.case_id,
            instruction=payload.summary_instruction.strip() or SUMMARY_INSTRUCTION,
        )

    async def _flags() -> FlagReply | None:
        if not run_flags:
            return None
        return await detect_flags(
            case_id=payload.case_id,
            instruction=payload.flag_instruction.strip() or FLAG_INSTRUCTION,
        )

    async def _next_action() -> NextActionReply | None:
        if not run_next_action:
            return None
        return await recommend_next_action(
            case_id=payload.case_id,
            instruction=(
                payload.next_action_instruction.strip() or NEXT_ACTION_INSTRUCTION
            ),
        )

    # All four at once, and tolerating one failing: `return_exceptions` keeps
    # a dead agent from cancelling the others mid-flight.
    (
        urgency_result,
        summary_result,
        flag_result,
        next_action_result,
    ) = await asyncio.gather(
        _urgency(), _summary(), _flags(), _next_action(), return_exceptions=True
    )

    def _unwrap(result: Any, name: str, empty: Any) -> Any:
        """Turn a raised exception into a reported error."""
        if isinstance(result, BaseException):
            logger.exception(
                "%s failed for case %s", name, payload.case_id, exc_info=result
            )
            errors.append(f"{name} failed: {result}")
            return empty
        return result

    urgency = _unwrap(urgency_result, AGENT_NAME, None)
    summary = _unwrap(summary_result, SUMMARY_AGENT_NAME, None)
    flags_reply = _unwrap(flag_result, FLAG_AGENT_NAME, None)
    next_action = _unwrap(next_action_result, NEXT_ACTION_AGENT_NAME, None)

    # Every agent asked for being dead is a Corti problem, not a partial
    # answer.
    if urgency is None and summary is None and flags_reply is None and (
        next_action is None
    ):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="; ".join(errors) or "The agents returned nothing.",
        )

    replies = (
        (AGENT_NAME, urgency),
        (SUMMARY_AGENT_NAME, summary),
        (FLAG_AGENT_NAME, flags_reply),
        (NEXT_ACTION_AGENT_NAME, next_action),
    )
    agents_run = [name for name, reply in replies if reply is not None]

    if urgency is not None and not urgency.text:
        errors.append("The urgency agent returned nothing.")
    if summary is not None and not summary.text:
        errors.append("The case summariser returned nothing.")
    if flags_reply is not None and not flags_reply.text:
        errors.append("The flag detector returned nothing.")
    if next_action is not None and not next_action.text:
        errors.append("The next action recommender returned nothing.")

    is_urgent = grade_to_urgent(urgency.recommendation) if urgency else None
    if urgency is not None and urgency.text and is_urgent is None:
        errors.append(
            f"The agent gave no recognised grade "
            f"({urgency.recommendation or 'none'}); the stored urgency is "
            "unchanged."
        )

    # Only write what the agents actually decided: a missing grade must not
    # clear an urgency a clinician set, and an empty write-up must not wipe
    # an existing summary.
    persisted = False
    if payload.persist:
        changes: dict[str, Any] = {}
        if is_urgent is not None:
            changes["is_urgent"] = is_urgent
        if urgency is not None and urgency.rationale:
            changes["urgency_reason"] = urgency.rationale
        if summary is not None and summary.summary:
            changes["case_summary"] = summary.summary
        # Flags replace rather than append: the agent grades the whole case
        # each run, so keeping the old set would double them up.
        if next_action is not None and next_action.recommendation:
            changes["recommendation"] = next_action.recommendation
        if flags_reply is not None and flags_reply.flags:
            changes["flags"] = [
                Flag(**flag).model_dump(mode="json") for flag in flags_reply.flags
            ]
        if changes:
            changes["updated_at"] = utcnow()
            await get_collection(case_model.COLLECTION).update_one(
                {"_id": ObjectId(payload.case_id)}, {"$set": changes}
            )
            persisted = True

    corti_logs = {
        name: reply.as_call(name) for name, reply in replies if reply is not None
    }

    logger.info(
        "update_agent_run: case %s ran %s -> %s, %d-char summary, %d flag(s), "
        "%d recommended step(s) (persisted=%s, %d error(s))",
        payload.case_id,
        ", ".join(agents_run) or "nothing",
        (urgency.recommendation if urgency else None) or "no grade",
        len(summary.summary) if summary else 0,
        len(flags_reply.flags) if flags_reply else 0,
        len(next_action.steps) if next_action else 0,
        persisted,
        len(errors),
    )

    return AgentRunResponse(
        case_id=payload.case_id,
        patient_name=patient_name,
        recommendation=urgency.recommendation if urgency else "",
        is_urgent=is_urgent,
        requires_clinician_escalation=bool(urgency and urgency.escalate),
        urgency_reason=urgency.rationale if urgency else "",
        evidence=urgency.evidence if urgency else [],
        text=urgency.text if urgency else "",
        context_id=urgency.context_id if urgency else "",
        case_summary=summary.summary if summary else "",
        summary_points=summary.points if summary else [],
        summary_context_id=summary.context_id if summary else "",
        flags=[Flag(**flag) for flag in (flags_reply.flags if flags_reply else [])],
        flags_text=flags_reply.text if flags_reply else "",
        flag_context_id=flags_reply.context_id if flags_reply else "",
        recommendation_text=next_action.recommendation if next_action else "",
        recommendation_steps=next_action.steps if next_action else [],
        recommendation_context_id=next_action.context_id if next_action else "",
        agents_run=agents_run,
        persisted=persisted,
        corti_log=corti_logs.get(AGENT_NAME),
        corti_logs=corti_logs,
        errors=errors,
    )
