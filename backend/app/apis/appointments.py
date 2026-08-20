"""CRUD for appointments, and the consultation that hangs off one.

A consultation appointment is the *booking*; the clinical record for it lives
in `consultations`. Creating one appointment therefore writes both, so a
booking shows up on the case's detail page as a consultation immediately —
carrying its pre-consultation requirement and notes from the moment it
is booked.

    POST   /appointments
    GET    /appointments?case_id=..&consultant_team_id=..&from=..&to=..
    GET    /appointments/{appointment_id}
    PATCH  /appointments/{appointment_id}
    DELETE /appointments/{appointment_id}

    curl -X POST 'http://127.0.0.1:8000/appointments' \
      -H 'Content-Type: application/json' \
      -d '{
        "case_id": "6a855a1197d7beaa80e15d57",
        "consultant_team_id": "6a855a19343c5cbafa5cbf89",
        "start_time": "2026-09-01T09:00:00",
        "end_time": "2026-09-01T09:30:00",
        "appointment_type": "consultation",
      }'
"""

import logging
from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, model_validator

from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import case as case_model
from app.models import consultant_team as team_model
from app.models import consultation as consultation_model
from app.models import patient as patient_model
from app.models.appointment import Appointment
from app.models.common import utcnow
from app.models.consultation import Consultation
from app.models.enums import AppointmentStatus, AppointmentType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["appointments"], prefix="/appointments")


# --- Request models --------------------------------------------------------


class AppointmentCreate(BaseModel):
    start_time: datetime
    end_time: datetime
    consultant_team_id: str
    # The patient is taken from the case when a case is given, so only one of
    # the two is required.
    case_id: str | None = None
    patient_id: str | None = None
    appointment_type: AppointmentType = AppointmentType.CONSULTATION
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    # Written to the consultation record created alongside the booking.

    @model_validator(mode="after")
    def check(self) -> "AppointmentCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time.")
        if not self.case_id and not self.patient_id:
            raise ValueError("Provide case_id or patient_id.")
        return self


class AppointmentPatch(BaseModel):
    """Every field optional — only what is sent gets written."""

    start_time: datetime | None = None
    end_time: datetime | None = None
    consultant_team_id: str | None = None
    appointment_type: AppointmentType | None = None
    status: AppointmentStatus | None = None
    transcription: str | None = None
    consultation_summary: str | None = None


# --- Read models -----------------------------------------------------------


class ConsultantSummary(BaseModel):
    consultant_team_id: str = ""
    name: str = ""
    speciality: str = ""


class PatientSummary(BaseModel):
    patient_id: str = ""
    name: str = ""
    age: int | None = None
    gender: str = ""


class ConsultationSummary(BaseModel):
    consultation_id: str = ""
    transcription: str | None = None
    consultation_summary: str | None = None


class AppointmentRead(BaseModel):
    appointment_id: str
    appointment_type: str = ""
    status: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    case_id: str | None = None
    patient: PatientSummary | None = None
    consultant: ConsultantSummary | None = None
    # Present for consultation appointments; surgeries keep their record in
    # `surgeries` instead.
    consultation: ConsultationSummary | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AppointmentListResponse(BaseModel):
    total: int
    limit: int
    skip: int
    appointments: list[AppointmentRead] = Field(default_factory=list)


# --- Helpers ---------------------------------------------------------------


def _oid(value: Any) -> str:
    return str(value) if value else ""


def as_oid(value: str, what: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{value!r} is not a valid {what} id."
        )
    return ObjectId(value)


async def require(collection: str, oid: ObjectId, what: str) -> dict:
    doc = await get_collection(collection).find_one({"_id": oid})
    if not doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No {what} with id {oid}."
        )
    return doc


async def to_appointment(doc: dict) -> AppointmentRead:
    """Expand one appointment with the records the UI shows alongside it."""
    team = None
    if doc.get("consultant"):
        team = await get_collection(team_model.COLLECTION).find_one(
            {"_id": doc["consultant"]}
        )
    patient = None
    if doc.get("patient"):
        patient = await get_collection(patient_model.COLLECTION).find_one(
            {"_id": doc["patient"]}
        )
    consultation = await get_collection(consultation_model.COLLECTION).find_one(
        {"appointment": doc["_id"]}
    )

    return AppointmentRead(
        appointment_id=_oid(doc.get("_id")),
        appointment_type=doc.get("appointment_type", ""),
        status=doc.get("status", ""),
        start_time=doc.get("start_time"),
        end_time=doc.get("end_time"),
        case_id=_oid(doc.get("case")) or None,
        patient=(
            PatientSummary(
                patient_id=_oid(patient.get("_id")),
                name=patient.get("name", ""),
                age=patient.get("age"),
                gender=patient.get("gender", ""),
            )
            if patient
            else None
        ),
        consultant=(
            ConsultantSummary(
                consultant_team_id=_oid(team.get("_id")),
                name=team.get("name", ""),
                speciality=team.get("speciality", ""),
            )
            if team
            else None
        ),
        consultation=(
            ConsultationSummary(
                consultation_id=_oid(consultation.get("_id")),
                transcription=consultation.get("transcription"),
                consultation_summary=consultation.get("consultation_summary"),
            )
            if consultation
            else None
        ),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


# --- Endpoints -------------------------------------------------------------


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def create_appointment(payload: AppointmentCreate) -> AppointmentRead:
    """Book an appointment, and open its consultation record with it."""
    team_id = as_oid(payload.consultant_team_id, "consultant team")
    await require(team_model.COLLECTION, team_id, "consultant team")

    case_id = None
    patient_id = None
    if payload.case_id:
        case_id = as_oid(payload.case_id, "case")
        case = await require(case_model.COLLECTION, case_id, "case")
        patient_id = case.get("patient")
    if payload.patient_id:
        patient_id = as_oid(payload.patient_id, "patient")
        await require(patient_model.COLLECTION, patient_id, "patient")
    if not patient_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="The case has no patient linked; pass patient_id.",
        )

    appointment = Appointment(
        patient=patient_id,
        consultant=team_id,
        case=case_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        appointment_type=payload.appointment_type,
        status=payload.status,
    )
    appointments = get_collection(appointment_model.COLLECTION)
    result = await appointments.insert_one(appointment.to_mongo())

    # The consultation is what makes the booking visible on the case page, so
    # it is created with the appointment rather than on first edit.
    if payload.appointment_type == AppointmentType.CONSULTATION and case_id:
        consultation = Consultation(
            case=case_id,
            appointment=result.inserted_id,
        )
        await get_collection(consultation_model.COLLECTION).insert_one(
            consultation.to_mongo()
        )

    logger.info("Created appointment %s", result.inserted_id)
    return await to_appointment(await appointments.find_one({"_id": result.inserted_id}))


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    case_id: str | None = None,
    patient_id: str | None = None,
    consultant_team_id: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
) -> AppointmentListResponse:
    """List appointments in time order.

    `from`/`to` bound `start_time`, which is what the calendar needs when it
    asks for one month or one day at a time.
    """
    query: dict[str, Any] = {}
    if case_id:
        query["case"] = as_oid(case_id, "case")
    if patient_id:
        query["patient"] = as_oid(patient_id, "patient")
    if consultant_team_id:
        query["consultant"] = as_oid(consultant_team_id, "consultant team")
    if status_filter:
        query["status"] = status_filter
    if date_from or date_to:
        window: dict[str, datetime] = {}
        if date_from:
            window["$gte"] = date_from
        if date_to:
            window["$lte"] = date_to
        query["start_time"] = window

    appointments = get_collection(appointment_model.COLLECTION)
    total = await appointments.count_documents(query)
    docs = (
        await appointments.find(query)
        .sort("start_time", 1)
        .skip(skip)
        .limit(limit)
        .to_list(length=limit)
    )
    return AppointmentListResponse(
        total=total,
        limit=limit,
        skip=skip,
        appointments=[await to_appointment(doc) for doc in docs],
    )


@router.get("/{appointment_id}", response_model=AppointmentRead)
async def get_appointment(appointment_id: str) -> AppointmentRead:
    oid = as_oid(appointment_id, "appointment")
    return await to_appointment(
        await require(appointment_model.COLLECTION, oid, "appointment")
    )


@router.patch("/{appointment_id}", response_model=AppointmentRead)
async def update_appointment(
    appointment_id: str, payload: AppointmentPatch
) -> AppointmentRead:
    """Update the booking, its consultation notes, or both."""
    oid = as_oid(appointment_id, "appointment")
    existing = await require(appointment_model.COLLECTION, oid, "appointment")

    sent = payload.model_dump(exclude_unset=True)
    if not sent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update — send at least one field.",
        )

    # Consultation fields live in their own collection.
    consultation_update = {
        key: sent.pop(key)
        for key in (
            "transcription",
            "consultation_summary",
        )
        if key in sent
    }

    appointment_update: dict[str, Any] = dict(sent)
    if "consultant_team_id" in appointment_update:
        team_id = as_oid(
            appointment_update.pop("consultant_team_id"), "consultant team"
        )
        await require(team_model.COLLECTION, team_id, "consultant team")
        appointment_update["consultant"] = team_id

    start = appointment_update.get("start_time", existing.get("start_time"))
    end = appointment_update.get("end_time", existing.get("end_time"))
    if start and end and end <= start:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="end_time must be after start_time."
        )

    now = utcnow()
    appointments = get_collection(appointment_model.COLLECTION)
    if appointment_update:
        appointment_update["updated_at"] = now
        await appointments.update_one({"_id": oid}, {"$set": appointment_update})

    if consultation_update:
        consultation_update["updated_at"] = now
        consultations = get_collection(consultation_model.COLLECTION)
        result = await consultations.update_one(
            {"appointment": oid}, {"$set": consultation_update}
        )
        # A consultation may not exist yet (surgery, or an appointment booked
        # without a case) — create one when there is a case to attach it to.
        if result.matched_count == 0 and existing.get("case"):
            await consultations.insert_one(
                Consultation(
                    case=existing["case"], appointment=oid, **consultation_update
                ).to_mongo()
            )

    logger.info("Updated appointment %s", appointment_id)
    return await to_appointment(await appointments.find_one({"_id": oid}))


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(appointment_id: str) -> Response:
    """Cancel a booking outright, taking its consultation record with it."""
    oid = as_oid(appointment_id, "appointment")
    await require(appointment_model.COLLECTION, oid, "appointment")

    await get_collection(consultation_model.COLLECTION).delete_many({"appointment": oid})
    await get_collection(appointment_model.COLLECTION).delete_one({"_id": oid})
    logger.info("Deleted appointment %s", appointment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
