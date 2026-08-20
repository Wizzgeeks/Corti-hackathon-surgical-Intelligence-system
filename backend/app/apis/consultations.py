"""Turning a recorded consultation into a stored record.

The dialog streams a diarized transcript from Corti; this is what happens when
the clinician stops recording and asks for the facts. Order matters: the
transcript is written to the consultation **first**, so a failure in fact
extraction cannot lose what was said, and only then is Corti's FactsR endpoint
called and its answer stored as the consultation summary.

    POST /cases/{case_id}/consultation_facts

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a.../consultation_facts' \
      -H 'Content-Type: application/json' \
      -d '{"transcription": "[Doctor] How is the wrist?\n[Patient] Still sore."}'

    201 {
      "case_id": "6a855a...",
      "consultation_id": "6a86f1...",
      "appointment_id": "6a86f0...",
      "transcription_saved": true,
      "transcription": "[Doctor] How is the wrist?\n[Patient] Still sore.",
      "consultation_summary": "Chief complaint:\n- Ongoing right wrist pain.\n\nHistory of present illness:\n- Pain worse with repetitive tasks.",
      "facts": [{"group": "chief-complaint", "text": "Ongoing right wrist pain."}],
      "fact_count": 2,
      "errors": []
    }

    The transcript is stored even when extraction fails; the response then
    carries `consultation_summary: ""` and the reason in `errors`.

    400 invalid case id or empty transcript · 404 unknown case
"""

import logging
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import case as case_model
from app.models import consultation as consultation_model
from app.models.common import utcnow
from app.models.consultation import Consultation
from app.services.corti_textgen import extract_facts, format_facts

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consultations"])


class ConsultationFactsRequest(BaseModel):
    """The transcript to store, and where to put it."""

    transcription: str
    # Target a specific consultation; otherwise the case's most recent one is
    # used, and a new one is created if the case has none.
    consultation_id: str | None = None
    appointment_id: str | None = None
    # False stores the transcript without calling Corti.
    extract: bool = True


class ConsultationFactsResponse(BaseModel):
    case_id: str
    consultation_id: str
    appointment_id: str | None = None
    transcription_saved: bool = False
    transcription: str = ""
    consultation_summary: str = ""
    facts: list[dict[str, Any]] = Field(default_factory=list)
    fact_count: int = 0
    # The Corti exchange, so the frontend can show what was sent.
    corti_log: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


async def resolve_consultation(case_oid: ObjectId, payload: ConsultationFactsRequest) -> dict:
    """Find the consultation this transcript belongs to, or start one.

    Prefers an explicit id, then the appointment's record, then the case's
    most recent consultation. A case recorded before anything was booked gets
    a consultation created for it rather than losing the transcript.
    """
    consultations = get_collection(consultation_model.COLLECTION)

    if payload.consultation_id:
        if not ObjectId.is_valid(payload.consultation_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"{payload.consultation_id!r} is not a valid consultation id.",
            )
        found = await consultations.find_one({"_id": ObjectId(payload.consultation_id)})
        if not found:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"No consultation with id {payload.consultation_id}.",
            )
        return found

    if payload.appointment_id and ObjectId.is_valid(payload.appointment_id):
        found = await consultations.find_one(
            {"appointment": ObjectId(payload.appointment_id)}
        )
        if found:
            return found

    found = await consultations.find_one({"case": case_oid}, sort=[("created_at", -1)])
    if found:
        return found

    # Nothing booked: keep the recording anyway, against the case's most
    # recent consultation appointment if there is one.
    appointment = await get_collection(appointment_model.COLLECTION).find_one(
        {"case": case_oid, "appointment_type": "consultation"},
        sort=[("start_time", -1)],
    )
    record = Consultation(
        case=case_oid, appointment=(appointment or {}).get("_id")
    ).to_mongo()
    result = await consultations.insert_one(record)
    logger.info("Created consultation %s for case %s", result.inserted_id, case_oid)
    return {**record, "_id": result.inserted_id}


@router.post(
    "/cases/{case_id}/consultation_facts",
    response_model=ConsultationFactsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def extract_consultation_facts(
    case_id: str, payload: ConsultationFactsRequest
) -> ConsultationFactsResponse:
    """Store the transcript, then extract its facts into the summary."""
    if not ObjectId.is_valid(case_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{case_id!r} is not a valid case id."
        )
    transcript = (payload.transcription or "").strip()
    if not transcript:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="There is no transcript to store."
        )

    case_oid = ObjectId(case_id)
    if not await get_collection(case_model.COLLECTION).find_one({"_id": case_oid}):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case with id {case_id}."
        )

    consultation = await resolve_consultation(case_oid, payload)
    consultations = get_collection(consultation_model.COLLECTION)

    # 1. The transcript first — losing what was said would be the worst
    #    outcome, and extraction is the part that can fail.
    await consultations.update_one(
        {"_id": consultation["_id"]},
        {"$set": {"transcription": transcript, "updated_at": utcnow()}},
    )

    errors: list[str] = []
    summary = ""
    facts: list[dict[str, Any]] = []
    corti_log: dict[str, Any] | None = None

    # 2. Then the facts, stored as the templated brief.
    if payload.extract:
        try:
            result = await extract_facts(context_text=transcript, access_token=None)
        except Exception as exc:  # noqa: BLE001 — transcript is already safe
            logger.exception("FactsR failed for case %s", case_id)
            errors.append(f"Fact extraction failed: {exc}")
        else:
            facts = result.facts
            summary = format_facts(facts)
            corti_log = result.as_call("consultation_facts")
            if summary:
                await consultations.update_one(
                    {"_id": consultation["_id"]},
                    {"$set": {"consultation_summary": summary, "updated_at": utcnow()}},
                )
            else:
                errors.append("Corti returned no facts for this transcript.")

    logger.info(
        "Case %s: stored %d-char transcript and %d fact(s).",
        case_id,
        len(transcript),
        len(facts),
    )
    return ConsultationFactsResponse(
        case_id=case_id,
        consultation_id=str(consultation["_id"]),
        appointment_id=(
            str(consultation["appointment"]) if consultation.get("appointment") else None
        ),
        transcription_saved=True,
        transcription=transcript,
        consultation_summary=summary,
        facts=facts,
        fact_count=len(facts),
        corti_log=corti_log,
        errors=errors,
    )
