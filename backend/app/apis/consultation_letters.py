"""Drafting the letter that follows a consultation.

The material is sent up from the page rather than read back out of the
database: the clinician may have edited the summary without saving it, and the
letter should be written from what is on screen. The case id in the URL is
what the draft is *about* — it is checked, and used to fill in anything the
page did not send.

    POST /cases/{case_id}/consultation_letter

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a.../consultation_letter' \
      -H 'Content-Type: application/json' \
      -d '{
        "current_consultation_summary": "Chief complaint: ongoing wrist pain...",
        "previous_consultation_summaries": ["Seen 14 Aug: splint applied..."],
        "patient": {"name": "Melissa Pearce", "age": 47, "gender": "female"}
      }'

    201 {
      "case_id": "6a855a...",
      "letter": "Dear Dr Ashok,\n\nI reviewed Melissa Pearce...",
      "patient": {"name": "Melissa Pearce", "age": 47, "gender": "female"},
      "context_id": "ctx.9f2...",
      "errors": []
    }

    The letter is not stored: it is a draft the clinician edits on the page
    before printing, so there is nothing here worth keeping a stale copy of.

    400 invalid case id or nothing to write from · 404 unknown case
    502 the agent could not be reached
"""

import logging
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.corti_agents.consultation_letter_writer import write_consultation_letter
from app.db.mongodb import get_collection
from app.models import case as case_model
from app.models import patient as patient_model

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consultations"])


class PatientDemographics(BaseModel):
    """Who the letter is about, as the page has them.

    Loose on purpose: every field is optional, because a letter is still worth
    drafting for a patient whose age or contact was never filled in.
    """

    name: str = ""
    age: int | None = None
    gender: str = ""
    contact: str = ""
    clinical_background: str = ""


class ConsultationLetterRequest(BaseModel):
    current_consultation_summary: str
    # Oldest first, as the page lists them. Empty for a first consultation.
    previous_consultation_summaries: list[str] = Field(default_factory=list)
    patient: PatientDemographics | None = None
    # Named on the letterhead rather than written into the body, so they are
    # passed through to the agent as context only.
    consultant_name: str = ""
    consultant_role: str = ""
    # Continue an earlier exchange — "make it shorter" without re-sending the
    # whole case.
    context_id: str | None = None


class ConsultationLetterResponse(BaseModel):
    case_id: str
    letter: str = ""
    # What the letter was written from, echoed back so the page can show the
    # demographics on the letterhead without a second call.
    patient: PatientDemographics = Field(default_factory=PatientDemographics)
    consultant_name: str = ""
    consultant_role: str = ""
    context_id: str = ""
    # The Corti exchange, so the frontend can show what was sent.
    corti_log: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


async def patient_for_case(case_oid: ObjectId) -> PatientDemographics:
    """The stored demographics, for filling in what the page did not send."""
    case = await get_collection(case_model.COLLECTION).find_one(
        {"_id": case_oid}, {"patient": 1}
    )
    patient_id = (case or {}).get("patient")
    if not patient_id:
        return PatientDemographics()

    patient = await get_collection(patient_model.COLLECTION).find_one(
        {"_id": patient_id}
    )
    if not patient:
        return PatientDemographics()

    return PatientDemographics(
        name=str(patient.get("name") or "").strip(),
        age=patient.get("age"),
        gender=str(patient.get("gender") or "").strip(),
        contact=str(patient.get("contact") or "").strip(),
        clinical_background=str(patient.get("clinical_background") or "").strip(),
    )


def merged(sent: PatientDemographics | None, stored: PatientDemographics) -> PatientDemographics:
    """What the page sent wins; the stored record fills the gaps.

    The page is the more current of the two — it carries edits that have not
    been saved — but it is also the more likely to have left a field out.
    """
    if not sent:
        return stored
    fields = sent.model_dump()
    for key, value in stored.model_dump().items():
        if not fields.get(key) and value:
            fields[key] = value
    return PatientDemographics(**fields)


@router.post(
    "/cases/{case_id}/consultation_letter",
    response_model=ConsultationLetterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_consultation_letter(
    case_id: str, payload: ConsultationLetterRequest
) -> ConsultationLetterResponse:
    """Draft the consultation letter for one case."""
    if not ObjectId.is_valid(case_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{case_id!r} is not a valid case id."
        )

    summary = (payload.current_consultation_summary or "").strip()
    if not summary:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="There is no consultation summary to write the letter from.",
        )

    case_oid = ObjectId(case_id)
    if not await get_collection(case_model.COLLECTION).find_one({"_id": case_oid}):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case with id {case_id}."
        )

    patient = merged(payload.patient, await patient_for_case(case_oid))
    # Blank entries would read to the agent as consultations that produced
    # nothing, which is not the same as a patient who has not been seen before.
    previous = [
        text.strip()
        for text in payload.previous_consultation_summaries
        if (text or "").strip()
    ]

    try:
        reply = await write_consultation_letter(
            current_consultation_summary=summary,
            previous_consultation_letters=previous,
            patient=patient.model_dump(exclude_none=True),
            data={
                "case_id": case_id,
                "consultant_name": payload.consultant_name,
                "consultant_role": payload.consultant_role,
            },
            context_id=payload.context_id,
        )
    except Exception as exc:  # noqa: BLE001 — the reason belongs on the page
        logger.exception("Consultation letter for case %s failed.", case_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"The letter could not be drafted: {exc}",
        ) from exc

    letter = (reply.letter or "").strip()
    if not letter:
        # A reachable agent that answered with nothing is not a 502: the call
        # worked, so the page is told plainly that there is no draft.
        logger.warning("Consultation letter for case %s came back empty.", case_id)

    logger.info(
        "Consultation letter for case %s: %d chars from %d previous summary(ies).",
        case_id,
        len(letter),
        len(previous),
    )
    return ConsultationLetterResponse(
        case_id=case_id,
        letter=letter,
        patient=patient,
        consultant_name=payload.consultant_name,
        consultant_role=payload.consultant_role,
        context_id=reply.context_id,
        corti_log=reply.as_call(),
        errors=[] if letter else ["The agent returned an empty letter."],
    )
