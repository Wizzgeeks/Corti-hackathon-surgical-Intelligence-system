"""Mongo reads behind the MCP tools.

Kept apart from the server so the shape of a patient record is defined in one
place and can be tested without an MCP client.
"""

import asyncio
import logging
from typing import Any

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import case as case_model
from app.models import consultant_team as team_model
from app.models import consultation as consultation_model
from app.models import contact as contact_model
from app.models import investigation as investigation_model
from app.models import patient as patient_model
from app.models import surgery as surgery_model

logger = logging.getLogger(__name__)

# A patient with a long history should not blow up one tool response.
MAX_CASES = 100
MAX_CHILDREN = 200


def jsonable(value: Any) -> Any:
    """Make a Mongo document safe to serialise: ObjectId and datetime to str."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def find_patient(
    patient_id: str | None = None, patient_name: str | None = None
) -> dict | None:
    """Look a patient up by id, or by name when the caller has no id.

    A name match is case-insensitive and exact — a partial match could return
    the wrong person's record, which is the one failure mode worth avoiding
    here.
    """
    patients = get_collection(patient_model.COLLECTION)

    if patient_id:
        if not ObjectId.is_valid(patient_id):
            raise ValueError(f"{patient_id!r} is not a valid patient id.")
        return await patients.find_one({"_id": ObjectId(patient_id)})

    if patient_name:
        return await patients.find_one(
            {"name": {"$regex": f"^{patient_name.strip()}$", "$options": "i"}}
        )

    raise ValueError("Supply either patient_id or patient_name.")


async def _by_id(collection: str, ids: list[Any]) -> dict[Any, dict]:
    """Fetch documents by id, keyed by `_id`."""
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    docs = (
        await get_collection(collection)
        .find({"_id": {"$in": wanted}})
        .to_list(length=len(wanted))
    )
    return {doc["_id"]: doc for doc in docs}


async def full_patient_record(
    patient_id: str | None = None, patient_name: str | None = None
) -> dict[str, Any]:
    """Assemble the whole record for one patient.

        {"patient": {...},
         "cases": [{..., "consultations": [...], "appointments": [...]}]}

    Everything is fetched in a fixed number of queries rather than one per
    case, so a patient with a long history costs the same round trips as one
    with a single case.
    """
    patient = await find_patient(patient_id, patient_name)
    if not patient:
        return {}

    cases = (
        await get_collection(case_model.COLLECTION)
        .find({"patient": patient["_id"]})
        .sort("created_at", -1)
        .to_list(length=MAX_CASES)
    )
    case_ids = [c["_id"] for c in cases]

    consultations: list[dict] = []
    appointments: list[dict] = []
    if case_ids:
        consultations = (
            await get_collection(consultation_model.COLLECTION)
            .find({"case": {"$in": case_ids}})
            .to_list(length=MAX_CHILDREN)
        )
        appointments = (
            await get_collection(appointment_model.COLLECTION)
            .find({"case": {"$in": case_ids}})
            .sort("start_time", 1)
            .to_list(length=MAX_CHILDREN)
        )

    # Resolve the consultant teams so a case names its team rather than
    # carrying an id a model cannot interpret.
    teams = await _by_id(team_model.COLLECTION, [c.get("consultant") for c in cases])

    by_case_consultations: dict[Any, list] = {}
    for doc in consultations:
        by_case_consultations.setdefault(doc.get("case"), []).append(doc)
    by_case_appointments: dict[Any, list] = {}
    for doc in appointments:
        by_case_appointments.setdefault(doc.get("case"), []).append(doc)

    assembled = []
    for case in cases:
        team = teams.get(case.get("consultant"))
        assembled.append(
            {
                **case,
                "consultant_team": team,
                "consultations": by_case_consultations.get(case["_id"], []),
                "appointments": by_case_appointments.get(case["_id"], []),
            }
        )

    logger.info(
        "Patient %s: %d case(s), %d consultation(s), %d appointment(s).",
        patient["_id"],
        len(cases),
        len(consultations),
        len(appointments),
    )

    return jsonable({"patient": patient, "cases": assembled})


async def search_patients(name: str, limit: int = 20) -> list[dict[str, Any]]:
    """Find patients whose name contains `name`, so a caller can get an id."""
    docs = (
        await get_collection(patient_model.COLLECTION)
        .find(
            {"name": {"$regex": name.strip(), "$options": "i"}},
            {"name": 1, "age": 1, "gender": 1, "contact": 1},
        )
        .limit(limit)
        .to_list(length=limit)
    )
    return jsonable(docs)


def _consultation_view(
    doc: dict, appointments: dict[Any, dict], teams: dict[Any, dict]
) -> dict[str, Any]:
    """One consultation, with its consultant named and its time filled in.

    Neither lives on the consultation: both come from the appointment it was
    booked under. Every stored field is kept alongside them, so a field added
    to `Consultation` still reaches the caller.
    """
    appointment = appointments.get(doc.get("appointment")) or {}
    team = teams.get(appointment.get("consultant")) or {}
    return {
        **doc,
        "transcription": doc.get("transcription") or "",
        "consultant": team.get("name", ""),
        "summary": doc.get("consultation_summary") or "",
        # When the consultation happened, not when the row was written — an
        # ad-hoc recording has no appointment, so it falls back.
        "time": appointment.get("start_time") or doc.get("created_at"),
    }


async def full_case_record(case_id: str) -> dict[str, Any]:
    """Everything on file for one case, shaped for a model to read.

        {"case": {case_id, pdf_content, referred_by, appointments,
                  investigations, requests, consultation, patient, surgery}}

    The case is read first because everything else keys off it; the five
    collections that hang off it are then read concurrently, so the whole
    record costs about one round trip rather than five.
    """
    if not ObjectId.is_valid(case_id):
        raise ValueError(f"{case_id!r} is not a valid case id.")

    oid = ObjectId(case_id)
    case = await get_collection(case_model.COLLECTION).find_one({"_id": oid})
    if not case:
        return {}

    async def _find(collection: str, sort: tuple | None = None) -> list[dict]:
        cursor = get_collection(collection).find({"case": oid})
        if sort:
            cursor = cursor.sort(*sort)
        return await cursor.to_list(length=MAX_CHILDREN)

    async def _patient() -> dict | None:
        if not case.get("patient"):
            return None
        return await get_collection(patient_model.COLLECTION).find_one(
            {"_id": case["patient"]}
        )

    # Independent reads, so they go out together rather than in sequence.
    patient, appointments, consultations, investigations, surgeries = (
        await asyncio.gather(
            _patient(),
            # Past and future both; the sort is what separates them.
            _find(appointment_model.COLLECTION, ("start_time", 1)),
            _find(consultation_model.COLLECTION, ("created_at", 1)),
            _find(investigation_model.COLLECTION, ("reported_at", 1)),
            _find(surgery_model.COLLECTION),
        )
    )

    # The consultant is recorded on the appointment, so naming one on a
    # consultation means going through its booking.
    teams = await _by_id(
        team_model.COLLECTION, [a.get("consultant") for a in appointments]
    )
    by_appointment = {a["_id"]: a for a in appointments}

    record = {
        "case_id": str(case["_id"]),
        # The referral letter the case was created from.
        "pdf_content": case.get("referral_document_content") or "",
        "referred_by": case.get("referred_by") or [],
        "appointments": [
            {**doc, "consultant": (teams.get(doc.get("consultant")) or {}).get("name", "")}
            for doc in appointments
        ],
        "investigations": [
            {
                **doc,
                "name": doc.get("name") or "",
                "extraction": doc.get("transcription") or "",
                "summary": doc.get("summary") or "",
            }
            for doc in investigations
        ],
        "requests": [
            {
                **entry,
                "request": entry.get("consultant_requests") or "",
                "response": entry.get("response") or "",
                # An unanswered request has no response time; fall back to
                # when it was asked so the entry is still orderable.
                "updated_at": entry.get("responded_time") or entry.get("request_time"),
            }
            for entry in (case.get("consultant_requests") or [])
        ],
        "consultation": [
            _consultation_view(doc, by_appointment, teams) for doc in consultations
        ],
        "patient": {
            **(patient or {}),
            "name": (patient or {}).get("name", ""),
            "age": (patient or {}).get("age", ""),
            "gender": (patient or {}).get("gender", ""),
            "clinical_background": (patient or {}).get("clinical_background", ""),
        },
        # One case can carry more than one procedure. `surgery` is the first,
        # matching the documented shape; `surgeries` keeps the rest.
        "surgery": surgeries[0] if surgeries else {},
        "surgeries": surgeries,
        # The clinical picture itself, which the shape above does not name.
        "case_summary": case.get("case_summary") or "",
        "symptoms": case.get("symptoms") or [],
        "flags": case.get("flags") or [],
        "recommendation": case.get("recommendation") or "",
        "is_urgent": case.get("is_urgent", False),
        "urgency_reason": case.get("urgency_reason") or "",
        "status": case.get("status") or "",
        "pre_consultation_details": case.get("pre_consultation_details") or "",
        "notes": case.get("notes") or "",
        "created_at": case.get("created_at"),
        "updated_at": case.get("updated_at"),
    }

    logger.info(
        "Case %s: %d appointment(s), %d consultation(s), %d investigation(s), "
        "%d request(s), %d surgery(ies).",
        case_id,
        len(appointments),
        len(consultations),
        len(investigations),
        len(record["requests"]),
        len(surgeries),
    )

    return jsonable({"case": record})


# The book is only useful looking forward, and a team with a full diary should
# not crowd out the rest of the response.
MAX_APPOINTMENTS = 500


def _slot(appointment: dict) -> str:
    """The appointment's time as one readable string.

    A model reads "starts at X, ends at Y" better as a single slot than as two
    fields it has to pair up itself.
    """
    start, end = appointment.get("start_time"), appointment.get("end_time")
    if not start:
        return ""
    start_text = start.isoformat() if hasattr(start, "isoformat") else str(start)
    if not end:
        return start_text
    end_text = end.isoformat() if hasattr(end, "isoformat") else str(end)
    return f"{start_text} - {end_text}"


async def consultant_availability(now: Any = None) -> dict[str, Any]:
    """Who is available, what they cover, and what is already booked.

        {"team": [{name, speciality, description, appointments: [...]}],
         "contacts": [{name, role, organisation}]}

    Only future appointments are returned: this answers "when could this
    patient be seen", and a past clinic tells you nothing about that. Teams,
    appointments and contacts are independent reads, so all three go out at
    once.
    """
    from datetime import datetime, timezone

    cutoff = now or datetime.now(timezone.utc)

    async def _teams() -> list[dict]:
        return (
            await get_collection(team_model.COLLECTION)
            .find({})
            .sort("name", 1)
            .to_list(length=MAX_CHILDREN)
        )

    async def _appointments() -> list[dict]:
        return (
            await get_collection(appointment_model.COLLECTION)
            .find({"start_time": {"$gte": cutoff}})
            .sort("start_time", 1)
            .to_list(length=MAX_APPOINTMENTS)
        )

    async def _contacts() -> list[dict]:
        return (
            await get_collection(contact_model.COLLECTION)
            .find({})
            .sort("name", 1)
            .to_list(length=MAX_CHILDREN)
        )

    teams, appointments, contacts = await asyncio.gather(
        _teams(), _appointments(), _contacts()
    )

    by_team: dict[Any, list] = {}
    for doc in appointments:
        by_team.setdefault(doc.get("consultant"), []).append(doc)

    assembled = []
    for team in teams:
        booked = by_team.get(team["_id"], [])
        assembled.append(
            {
                "name": team.get("name", ""),
                "speciality": team.get("speciality", ""),
                # What they actually cover — the procedures and diagnoses that
                # decide whether a referral belongs with them.
                "description": team.get("description") or "",
                "consultant_team_id": str(team["_id"]),
                "appointments": [
                    {
                        "type": doc.get("appointment_type", ""),
                        "slot": _slot(doc),
                        "consultant": team.get("name", ""),
                        "status": doc.get("status", ""),
                        "appointment_id": str(doc["_id"]),
                    }
                    for doc in booked
                ],
            }
        )

    logger.info(
        "Availability: %d team(s), %d future appointment(s), %d contact(s).",
        len(teams),
        len(appointments),
        len(contacts),
    )

    return jsonable(
        {
            "team": assembled,
            "contacts": [
                {
                    "name": doc.get("name", ""),
                    # Their role is what service they provide — a hand
                    # therapist, a radiology service.
                    "role": doc.get("role", ""),
                    "organisation": doc.get("organization", ""),
                    "contact_id": str(doc["_id"]),
                }
                for doc in contacts
            ],
        }
    )
