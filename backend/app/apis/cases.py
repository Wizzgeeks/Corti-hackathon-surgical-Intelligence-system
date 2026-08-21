"""Create a case from the reviewed triage form.

The form is the clinician's confirmation of what triage produced, so this
endpoint writes the accepted values into their own collections: the patient
into `patients`, the case into `cases`, linked by id.

    POST /cases

    curl -X POST 'http://127.0.0.1:8000/cases' \
      -H 'Content-Type: application/json' \
      -d '{
        "patient": {
          "name": "Janelle Henderson",
          "age": 49,
          "gender": "Female",
          "contact": "",
        },
        "referrer": {
          "name": "Andie Fulton",
          "role": "",
          "organization": "Motus Lincoln"
        },
        "case": {
          "case_summary": "62-year-old man with six months of progressive right knee pain...",
          "flags": "Unintentional weight loss of 6 kg over three months (high)...",
          "recommendation": "Arrange a weight-bearing knee X-ray and routine bloods..."
        },
        "pdf_content": "Merivale Hand Clinic Ltd ... extracted referral text ...",
        "referral_id": "abc123"
      }'

    201 {
      "patient_id": "6a855a1197d7beaa80e15d56",
      "case_id": "6a855a1197d7beaa80e15d57",
      "warnings": []
    }

    GET /cases

    List view: summary rows for a caseload table. No consultations, no
    appointments, no referral document text — use the detail endpoint for
    those.

    curl 'http://127.0.0.1:8000/cases?limit=20&skip=0&is_urgent=true'

    200 {
      "total": 42,
      "limit": 20,
      "skip": 0,
      "cases": [
        {
          "case_id": "6a855a1197d7beaa80e15d57",
          "status": "new",
          "is_urgent": true,
          "urgency_reason": "Unexplained weight loss alongside night pain.",
          "case_summary": "62-year-old man with six months of...",
          "recommendation": "Arrange a weight-bearing knee X-ray...",
          "flags": [
            {"label": "Referral flags", "severity": "medium", "rationale": "..."}
          ],
          "symptoms": [],
          "referred_by": [
            {"name": "Andie Fulton", "role": "", "organization": "Motus Lincoln"}
          ],
          "patient": {
            "patient_id": "6a855a1197d7beaa80e15d56",
            "name": "Janelle Henderson",
            "age": 49,
            "gender": "Female",
            "contact": "",
            },
          "consultant": {
                  "name": "Orthopaedics",
            "speciality": "Orthopaedics"
          },
          "created_at": "2026-08-19T07:24:01.066000",
          "updated_at": "2026-08-19T07:24:01.066000"
        }
      ]
    }

    GET /cases/{case_id}

    Everything on the case: the list fields plus the referral document text,
    consultations, appointments and surgeries.

    curl 'http://127.0.0.1:8000/cases/6a855a1197d7beaa80e15d57'

    200 {
      "case_id": "6a855a1197d7beaa80e15d57",
      "...": "all list fields",
      "referral_document_content": "Merivale Hand Clinic Ltd\\n208 Papanui Road\\n...",
      "consultations": [
        {
          "consultation_id": "6a855a...",
          "appointment_id": "6a855b...",
          "transcription": "...",
          "consultation_summary": "..."
        }
      ],
      "appointments": [
        {
          "appointment_id": "6a855b...",
          "appointment_type": "consultation",
          "status": "scheduled",
          "start_time": "2026-09-01T09:00:00",
          "end_time": "2026-09-01T09:30:00"
        }
      ],
      "surgeries": []
    }

    404 when the case id is unknown · 400 when it is not a valid id

    PATCH /cases/{case_id}

    Partial update. Send only what changed — any subset of the patient, the
    referrer, or the case itself. Omitted fields are left alone; a field sent
    as null or "" is written as such, so clearing a value is possible.

    curl -X PATCH 'http://127.0.0.1:8000/cases/6a855a1197d7beaa80e15d57' \
      -H 'Content-Type: application/json' \
      -d '{"case": {"is_urgent": true, "urgency_reason": "Weight loss unexplained."}}'

    curl -X PATCH 'http://127.0.0.1:8000/cases/6a855a1197d7beaa80e15d57' \
      -H 'Content-Type: application/json' \
      -d '{
        "patient": {"contact": "0211 674 957"},
        "referrer": {"role": "Registered Hand Therapist"},
        "case": {"status": "triaged", "is_urgent": true}
      }'

    200 — the updated case, in the same shape as GET /cases/{case_id}, with
    `warnings` when something was accepted but not fully resolved.

    400 when the body is empty or an id is malformed · 404 unknown case
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import case as case_model
from app.models import consultant_team as team_model
from app.models import consultation as consultation_model
from app.models import investigation as investigation_model
from app.models import patient as patient_model
from app.models import surgery as surgery_model
from app.models.case import Case, Flag, MedicalCode, QuestionnaireQuestion, Referred_by
from app.models.common import utcnow
from app.models.enums import CaseStatus, FlagSeverity
from app.models.patient import Patient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cases"])

# The form's free-text flags box is stored as one flag; severity is not
# captured in the form, so it is left at the model default.
FLAGS_LABEL = "Referral flags"


class PatientDetails(BaseModel):
    name: str
    age: int = Field(ge=0, le=130)
    gender: str = ""
    contact: str = ""
    clinical_background: str | None = None


class ReferrerDetails(BaseModel):
    name: str = ""
    role: str = ""
    organization: str = ""


class CaseDetails(BaseModel):
    case_summary: str = ""
    flags: str = ""
    recommendation: str = ""
    pre_consultation_details: str = ""
    notes: str = ""
    symptoms: list[str] = Field(default_factory=list)
    is_urgent: bool = False
    urgency_reason: str | None = None


class CreateCaseRequest(BaseModel):
    patient: PatientDetails
    referrer: ReferrerDetails = Field(default_factory=ReferrerDetails)
    case: CaseDetails
    # Links the case back to the uploaded referral, when it came from one.
    referral_id: str | None = None
    # Text extracted from the referral PDF — `pdf_content` from the upload
    # response. Stored on the case as the source the triage was based on.
    referral_document_content: str = Field(default="", alias="pdf_content")

    model_config = {"populate_by_name": True}


class CreateCaseResponse(BaseModel):
    patient_id: str
    case_id: str
    # Anything accepted but not fully resolved (e.g. unknown consultant team).
    warnings: list[str] = Field(default_factory=list)


def build_flags(text: str) -> list[Flag]:
    """Wrap the form's free-text flags as a single `Flag`."""
    text = (text or "").strip()
    if not text:
        return []
    return [Flag(label=FLAGS_LABEL, severity=FlagSeverity.MEDIUM, rationale=text)]


@router.post(
    "/cases",
    response_model=CreateCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_case(payload: CreateCaseRequest) -> CreateCaseResponse:
    """Store the reviewed triage as a patient record and a case."""
    warnings: list[str] = []

    patient = Patient(
        name=payload.patient.name,
        age=payload.patient.age,
        gender=payload.patient.gender,
        contact=payload.patient.contact,
        clinical_background=payload.patient.clinical_background,
    )
    patient_result = await get_collection(patient_model.COLLECTION).insert_one(
        patient.to_mongo()
    )

    referrer = payload.referrer
    case = Case(
        referral_document_content=payload.referral_document_content,
        patient=patient_result.inserted_id,
        referred_by=(
            [
                Referred_by(
                    name=referrer.name,
                    role=referrer.role,
                    organization=referrer.organization,
                )
            ]
            if any((referrer.name, referrer.role, referrer.organization))
            else []
        ),
        symptoms=payload.case.symptoms,
        case_summary=payload.case.case_summary or None,
        flags=build_flags(payload.case.flags),
        recommendation=payload.case.recommendation or None,
        pre_consultation_details=payload.case.pre_consultation_details or None,
        notes=payload.case.notes or None,
        is_urgent=payload.case.is_urgent,
        urgency_reason=payload.case.urgency_reason,
    )

    try:
        case_result = await get_collection(case_model.COLLECTION).insert_one(
            case.to_mongo()
        )
    except Exception as exc:  # noqa: BLE001 — don't leave an orphan patient
        await get_collection(patient_model.COLLECTION).delete_one(
            {"_id": patient_result.inserted_id}
        )
        logger.exception("Case insert failed; rolled back patient")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not store the case: {exc}",
        ) from exc

    logger.info(
        "Stored patient %s and case %s (referral %s)",
        patient_result.inserted_id,
        case_result.inserted_id,
        payload.referral_id,
    )

    return CreateCaseResponse(
        patient_id=str(patient_result.inserted_id),
        case_id=str(case_result.inserted_id),
        warnings=warnings,
    )


# --- Read models -----------------------------------------------------------


class PatientSummary(BaseModel):
    patient_id: str = ""
    name: str = ""
    age: int | None = None
    gender: str = ""
    contact: str = ""
    clinical_background: str | None = None


class ConsultantSummary(BaseModel):
    consultant_team_id: str = ""
    name: str = ""
    speciality: str = ""


class CaseSummary(BaseModel):
    """A row in the caseload list. Deliberately without consultations."""

    case_id: str
    status: str = ""
    is_urgent: bool = False
    # Whether the patient has filled in the public questionnaire, and whether
    # a clinician has since worked those answers into the case.
    patient_recording_completed: bool = False
    patient_recording_reconciled: bool = False
    urgency_reason: str | None = None
    case_summary: str | None = None
    recommendation: str | None = None
    pre_consultation_details: str | None = None
    notes: str | None = None
    flags: list[Flag] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    referred_by: list[Referred_by] = Field(default_factory=list)
    patient: PatientSummary | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseListResponse(BaseModel):
    total: int
    limit: int
    skip: int
    cases: list[CaseSummary] = Field(default_factory=list)


class ConsultationDetail(BaseModel):
    consultation_id: str
    appointment_id: str | None = None
    transcription: str | None = None
    consultation_summary: str | None = None


class AppointmentDetail(BaseModel):
    appointment_id: str
    appointment_type: str = ""
    status: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    # Which team the booking is with — shown against the consultation on the
    # case page, so it is resolved here rather than fetched per appointment.
    consultant: ConsultantSummary | None = None


class SurgeryDetail(BaseModel):
    surgery_id: str
    appointment_id: str | None = None
    procedure_code: str | None = None
    pre_surgery_plan: str | None = None
    op_notes_transcription: str | None = None
    op_notes_summary: str | None = None


class CaseDetail(CaseSummary):
    """The whole case: list fields plus everything hanging off it."""

    referral_document_content: str = ""
    # Carried on the detail so the case page can render the coding it
    # already has instead of asking the coding endpoint for it again.
    medical_codes: list[MedicalCode] = Field(default_factory=list)
    # Which of the standard questions this patient is asked. Empty means the
    # form has not been personalised yet, which is what the case page reacts
    # to on load.
    questionnaire_questions: list[QuestionnaireQuestion] = Field(
        default_factory=list
    )
    consultations: list[ConsultationDetail] = Field(default_factory=list)
    appointments: list[AppointmentDetail] = Field(default_factory=list)
    surgeries: list[SurgeryDetail] = Field(default_factory=list)


# --- Serialisation ---------------------------------------------------------


def _oid(value: Any) -> str:
    return str(value) if value else ""


def to_case_summary(doc: dict, patient: dict | None) -> dict:
    """Shape one case document for the API."""
    return {
        "case_id": _oid(doc.get("_id")),
        "status": doc.get("status", ""),
        "is_urgent": doc.get("is_urgent", False),
        "patient_recording_completed": doc.get("patient_recording_completed", False),
        "patient_recording_reconciled": doc.get("patient_recording_reconciled", False),
        "urgency_reason": doc.get("urgency_reason"),
        "case_summary": doc.get("case_summary"),
        "recommendation": doc.get("recommendation"),
        "pre_consultation_details": doc.get("pre_consultation_details"),
        "notes": doc.get("notes"),
        "flags": doc.get("flags") or [],
        "symptoms": doc.get("symptoms") or [],
        "referred_by": doc.get("referred_by") or [],
        "patient": (
            {
                "patient_id": _oid(patient.get("_id")),
                "name": patient.get("name", ""),
                "age": patient.get("age"),
                "gender": patient.get("gender", ""),
                "contact": patient.get("contact", ""),
                "clinical_background": patient.get("clinical_background"),
            }
            if patient
            else None
        ),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


# --- Endpoints -------------------------------------------------------------


@router.get("/cases", response_model=CaseListResponse)
async def list_cases(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    is_urgent: bool | None = None,
) -> CaseListResponse:
    """List cases, newest first.

    Summary rows only — consultations, appointments and the referral document
    text are on the detail endpoint, since a caseload table does not need to
    carry them.
    """
    query: dict[str, Any] = {}
    if status_filter:
        query["status"] = status_filter
    if is_urgent is not None:
        query["is_urgent"] = is_urgent
    cases = get_collection(case_model.COLLECTION)
    total = await cases.count_documents(query)
    docs = (
        await cases.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(
            length=limit
        )
    )

    # Resolve the referenced patients in one query rather than one per case.
    patients = await _by_id(patient_model.COLLECTION, [d.get("patient") for d in docs])

    return CaseListResponse(
        total=total,
        limit=limit,
        skip=skip,
        cases=[
            CaseSummary(**to_case_summary(doc, patients.get(doc.get("patient"))))
            for doc in docs
        ],
    )


async def _by_id(collection: str, ids: list[Any]) -> dict[Any, dict]:
    """Fetch documents by id, keyed by `_id`."""
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    docs = await get_collection(collection).find({"_id": {"$in": wanted}}).to_list(
        length=len(wanted)
    )
    return {doc["_id"]: doc for doc in docs}


@router.get("/cases/{case_id}", response_model=CaseDetail)
async def get_case(case_id: str) -> CaseDetail:
    """Return one case with everything attached to it."""
    if not ObjectId.is_valid(case_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{case_id!r} is not a valid case id."
        )

    oid = ObjectId(case_id)
    doc = await get_collection(case_model.COLLECTION).find_one({"_id": oid})
    if not doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case with id {case_id}."
        )

    patient = None
    if doc.get("patient"):
        patient = await get_collection(patient_model.COLLECTION).find_one(
            {"_id": doc["patient"]}
        )
    consultations = await get_collection(consultation_model.COLLECTION).find(
        {"case": oid}
    ).to_list(length=100)
    appointments = await get_collection(appointment_model.COLLECTION).find(
        {"case": oid}
    ).sort("start_time", 1).to_list(length=100)
    surgeries = await get_collection(surgery_model.COLLECTION).find(
        {"case": oid}
    ).to_list(length=100)

    # An appointment can be with a different team than the case is assigned
    # to, so resolve them from the appointments themselves.
    appointment_teams = await _by_id(
        team_model.COLLECTION, [a.get("consultant") for a in appointments]
    )

    return CaseDetail(
        **to_case_summary(doc, patient),
        referral_document_content=doc.get("referral_document_content", ""),
        medical_codes=doc.get("medical_codes") or [],
        questionnaire_questions=doc.get("questionnaire_questions") or [],
        consultations=[
            ConsultationDetail(
                consultation_id=_oid(c.get("_id")),
                appointment_id=_oid(c.get("appointment")) or None,
                transcription=c.get("transcription"),
                consultation_summary=c.get("consultation_summary"),
            )
            for c in consultations
        ],
        appointments=[
            AppointmentDetail(
                appointment_id=_oid(a.get("_id")),
                appointment_type=a.get("appointment_type", ""),
                status=a.get("status", ""),
                start_time=a.get("start_time"),
                end_time=a.get("end_time"),
                consultant=(
                    ConsultantSummary(
                        consultant_team_id=_oid(t.get("_id")),
                        name=t.get("name", ""),
                        speciality=t.get("speciality", ""),
                    )
                    if (t := appointment_teams.get(a.get("consultant")))
                    else None
                ),
            )
            for a in appointments
        ],
        surgeries=[
            SurgeryDetail(
                surgery_id=_oid(s.get("_id")),
                appointment_id=_oid(s.get("appointment")) or None,
                procedure_code=s.get("procedure_code"),
                pre_surgery_plan=s.get("pre_surgery_plan"),
                op_notes_transcription=s.get("op_notes_transcription"),
                op_notes_summary=s.get("op_notes_summary"),
            )
            for s in surgeries
        ],
    )


# --- Update ----------------------------------------------------------------


class PatientPatch(BaseModel):
    """Every field optional — only what is sent gets written."""

    name: str | None = None
    age: int | None = Field(default=None, ge=0, le=130)
    gender: str | None = None
    contact: str | None = None
    clinical_background: str | None = None


class ReferrerPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    organization: str | None = None


class CasePatch(BaseModel):
    case_summary: str | None = None
    # Free text (wrapped as one flag) or a ready-made list of flags.
    flags: str | list[Flag] | None = None
    recommendation: str | None = None
    pre_consultation_details: str | None = None
    notes: str | None = None
    # Replaces the whole list — read the case, append, send it back.
    symptoms: list[str] | None = None
    is_urgent: bool | None = None
    urgency_reason: str | None = None
    status: CaseStatus | None = None
    referral_document_content: str | None = None


class UpdateCaseRequest(BaseModel):
    patient: PatientPatch | None = None
    referrer: ReferrerPatch | None = None
    case: CasePatch | None = None


class UpdateCaseResponse(CaseDetail):
    """The updated case, plus anything that could not be fully applied."""

    warnings: list[str] = Field(default_factory=list)


def _merge_referrer(existing: list[dict], patch: dict) -> list[dict]:
    """Apply a referrer patch to the case's first referrer entry.

    `referred_by` is a list on the model but the form edits one referrer, so
    the patch updates the first entry and creates it if there is none.
    """
    current = dict(existing[0]) if existing else {"name": "", "role": "", "organization": ""}
    current.update(patch)
    return [current, *existing[1:]]


@router.patch("/cases/{case_id}", response_model=UpdateCaseResponse)
async def update_case(case_id: str, payload: UpdateCaseRequest) -> UpdateCaseResponse:
    """Update any subset of a case, its patient, or its referrer.

    Uses `exclude_unset`, so an omitted field is untouched while a field sent
    explicitly as `null` clears the stored value.
    """
    if not ObjectId.is_valid(case_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{case_id!r} is not a valid case id."
        )

    oid = ObjectId(case_id)
    cases = get_collection(case_model.COLLECTION)
    existing = await cases.find_one({"_id": oid})
    if not existing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case with id {case_id}."
        )

    warnings: list[str] = []
    case_update: dict[str, Any] = {}
    # Tracked separately from `case_update`: a field can be sent and still
    # produce no write (an unresolvable consultant), which is a warning rather
    # than an empty request.
    fields_sent = False

    # --- case fields ---
    if payload.case is not None:
        sent = payload.case.model_dump(exclude_unset=True)
        fields_sent = fields_sent or bool(sent)

        if "flags" in sent:
            flags = sent.pop("flags")
            if isinstance(flags, str) or flags is None:
                case_update["flags"] = [f.model_dump() for f in build_flags(flags or "")]
            else:
                case_update["flags"] = [
                    f if isinstance(f, dict) else f.model_dump() for f in flags
                ]

        if "status" in sent and sent["status"] is not None:
            sent["status"] = CaseStatus(sent["status"]).value

        case_update.update(sent)

    # --- referrer, which lives on the case ---
    if payload.referrer is not None:
        referrer_patch = payload.referrer.model_dump(exclude_unset=True)
        fields_sent = fields_sent or bool(referrer_patch)
        if referrer_patch:
            case_update["referred_by"] = _merge_referrer(
                existing.get("referred_by") or [], referrer_patch
            )

    # --- patient, in its own collection ---
    patient_update: dict[str, Any] = {}
    if payload.patient is not None:
        patient_update = payload.patient.model_dump(exclude_unset=True)
        fields_sent = fields_sent or bool(patient_update)

    if not fields_sent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update — send at least one field.",
        )

    now = utcnow()

    if patient_update:
        patient_id = existing.get("patient")
        if not patient_id:
            warnings.append("Case has no patient linked; patient fields ignored.")
        else:
            patient_update["updated_at"] = now
            result = await get_collection(patient_model.COLLECTION).update_one(
                {"_id": patient_id}, {"$set": patient_update}
            )
            if result.matched_count == 0:
                warnings.append(
                    f"Linked patient {patient_id} no longer exists; "
                    "patient fields ignored."
                )

    if case_update:
        case_update["updated_at"] = now
        await cases.update_one({"_id": oid}, {"$set": case_update})

    logger.info(
        "Updated case %s (case fields: %s, patient fields: %s)",
        case_id,
        sorted(k for k in case_update if k != "updated_at"),
        sorted(k for k in patient_update if k != "updated_at"),
    )

    detail = await get_case(case_id)
    return UpdateCaseResponse(**detail.model_dump(), warnings=warnings)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(case_id: str) -> Response:
    """Delete a case and everything hanging off it.

    Consultations, surgeries, investigations and appointments all belong to
    the case and go with it — none of them mean anything on their own, and
    leaving them would keep a deleted case's appointments in the calendar.

    The patient is the exception: they are only removed when this was their
    last case, since one person can be referred more than once.

    Uploaded investigation reports are unlinked from disk as well, so a
    deleted case does not leave its PDFs behind.
    """
    oid = ObjectId(case_id) if ObjectId.is_valid(case_id) else None
    if oid is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{case_id!r} is not a valid case id."
        )

    cases = get_collection(case_model.COLLECTION)
    case = await cases.find_one({"_id": oid})
    if not case:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case with id {case_id}."
        )

    # The report files first: once the records are gone there is nothing left
    # pointing at them.
    investigations = get_collection(investigation_model.COLLECTION)
    async for doc in investigations.find({"case": oid}, {"attachments": 1}):
        for path in doc.get("attachments") or []:
            Path(path).unlink(missing_ok=True)

    removed = {}
    for label, collection in (
        ("consultations", consultation_model.COLLECTION),
        ("surgeries", surgery_model.COLLECTION),
        ("investigations", investigation_model.COLLECTION),
        ("appointments", appointment_model.COLLECTION),
    ):
        result = await get_collection(collection).delete_many({"case": oid})
        removed[label] = result.deleted_count

    await cases.delete_one({"_id": oid})

    patient_id = case.get("patient")
    if patient_id:
        # Any other case still referring to them keeps the patient on file.
        others = await cases.count_documents({"patient": patient_id})
        if others == 0:
            await get_collection(patient_model.COLLECTION).delete_one(
                {"_id": patient_id}
            )
            removed["patient"] = 1

    logger.info("Deleted case %s and %s", case_id, removed)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
