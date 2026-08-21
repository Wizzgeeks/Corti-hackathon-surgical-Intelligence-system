"""Medical coding for a case, from its consultation summaries.

A case is only codeable once it has been consulted on: the referral letter
describes what the patient was sent in with, the consultation records what was
actually found. So this endpoint codes the consultation summaries, falling
back to the agent-written case summary for the wider picture.

    POST /get_medical_codes

    curl -X POST 'http://127.0.0.1:8000/get_medical_codes' \
      -H 'Content-Type: application/json' \
      -d '{"case_id": "6a870af1673e6e1622953190"}'

    200 {
      "case_id": "6a870af1673e6e1622953190",
      "codes": [
        {"code": "S63.591A", "description": "Other specified sprain of right
          wrist, initial encounter", "system": "icd10cm-inpatient",
         "confidence": 0.82, "evidence": "peripheral ulnar-sided TFCC tear"}
      ],
      "system": ["icd10cm-inpatient"],
      "source_characters": 1462,
      "errors": []
    }

    A case with no consultation summary yet is not an error — it returns
    `codes: []` and says so in `errors`, because the UI asks for codes as soon
    as a case is opened and a not-yet-consulted case is the normal case.

    400 invalid case id · 404 unknown case · 502 Corti rejected the call
"""

import logging
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models import case as case_model
from app.models import consultation as consultation_model
from app.models.common import utcnow
from app.services.corti_client import CortiError
from app.services.corti_coding import DEFAULT_SYSTEMS, fetch_codes

logger = logging.getLogger(__name__)

router = APIRouter(tags=["medical codes"])


class MedicalCodesRequest(BaseModel):
    case_id: str
    # Which coding systems to ask for; the clinic's default when omitted.
    system: list[str] | None = None
    # Ignore what is stored and code the case again.
    refresh: bool = False


class MedicalCode(BaseModel):
    code: str = ""
    description: str = ""
    system: str = ""
    # Corti does not always score a code.
    confidence: float | None = None
    evidence: str = ""


class MedicalCodesResponse(BaseModel):
    case_id: str
    codes: list[MedicalCode] = Field(default_factory=list)
    system: list[str] = Field(default_factory=list)
    source_characters: int = 0
    # True when these came off the case rather than from Corti.
    cached: bool = False
    errors: list[str] = Field(default_factory=list)


async def _coding_context(case_id: ObjectId) -> str:
    """The text worth coding: every consultation summary, then the case
    summary for background the consultations assume."""
    consultations = (
        await get_collection(consultation_model.COLLECTION)
        .find({"case": case_id})
        .sort("created_at", 1)
        .to_list(length=100)
    )

    parts = [
        (item.get("consultation_summary") or "").strip()
        for item in consultations
    ]
    return "\n\n".join(part for part in parts if part)


@router.post("/get_medical_codes", response_model=MedicalCodesResponse)
async def get_medical_codes(payload: MedicalCodesRequest) -> MedicalCodesResponse:
    """Code a case's consultations through Corti's coding tool.

    Read-only: the codes are returned, not written onto the case. They are
    derived from summaries that change, so storing them would only create a
    second thing to keep in step.
    """
    try:
        case_id = ObjectId(payload.case_id)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Invalid case id: {payload.case_id}"
        ) from exc

    case = await get_collection(case_model.COLLECTION).find_one({"_id": case_id})
    if not case:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case {payload.case_id}."
        )

    systems = payload.system or list(DEFAULT_SYSTEMS)

    # Stored codes stand until an agent run clears them: the summaries they
    # were read from cannot change without one.
    stored = case.get("medical_codes") or []
    if stored and not payload.refresh:
        return MedicalCodesResponse(
            case_id=payload.case_id,
            codes=[MedicalCode(**code) for code in stored],
            system=systems,
            cached=True,
        )

    context = await _coding_context(case_id)

    # Not an error: the UI asks on every case open, and most cases have not
    # been consulted on yet.
    if not context:
        return MedicalCodesResponse(
            case_id=payload.case_id,
            system=systems,
            errors=["This case has no consultation summary yet, so nothing was coded."],
        )

    # Background the consultation assumes, appended only when there is a
    # consultation to give it context to.
    summary = (case.get("case_summary") or "").strip()
    if summary:
        context = f"{context}\n\n{summary}"

    try:
        codes, _raw = await fetch_codes(context, systems)
    except CortiError as exc:
        logger.exception("coding failed for case %s", payload.case_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Corti coding failed: {exc}"
        ) from exc

    # Written back so the next read is free. An empty answer is stored too —
    # it is a real result, and re-asking Corti would only produce it again.
    await get_collection(case_model.COLLECTION).update_one(
        {"_id": case_id},
        {"$set": {"medical_codes": codes, "updated_at": utcnow()}},
    )

    logger.info(
        "get_medical_codes: case %s coded %d char(s) -> %d code(s), saved",
        payload.case_id,
        len(context),
        len(codes),
    )

    return MedicalCodesResponse(
        case_id=payload.case_id,
        codes=[MedicalCode(**code) for code in codes],
        system=systems,
        source_characters=len(context),
    )
