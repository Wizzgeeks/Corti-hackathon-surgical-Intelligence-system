from datetime import datetime

from bson import ObjectId
from pydantic import BaseModel, Field

from app.models.common import MongoModel, PyObjectId, utcnow
from app.models.enums import CaseStatus, FlagSeverity

COLLECTION = "cases"


class Flag(BaseModel):
    label: str
    severity: FlagSeverity = FlagSeverity.LOW
    rationale: str | None = None

class MedicalCode(BaseModel):
    """One coded diagnosis, as Corti's coding tool returned it.

    Stored on the case rather than recomputed per view: coding costs a Corti
    call, and the text it is derived from only changes when an agent run
    rewrites it. `update_agent_run` clears these, which is what makes the
    next read fetch fresh ones.
    """

    code: str = ""
    description: str = ""
    system: str = ""
    # Corti does not always score a code.
    confidence: float | None = None
    evidence: str = ""


class QuestionnaireQuestion(BaseModel):
    """One question actually put to this patient.

    The full form is nine questions, but a patient is only asked what the
    clinical background does not already answer — so which questions apply
    is a property of the case, and stored with it.
    """

    order: int
    question: str
    # Why this one survived the cull, for a clinician wondering why the
    # patient was asked about allergies and not about medication.
    reason: str = ""


class Referred_by(BaseModel):
    name: str
    role: str
    organization: str


class Case(MongoModel):
    referral_document_content: str
    patient: PyObjectId  # -> patients._id
    referred_by: list[Referred_by] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    case_summary: str | None = None
    flags: list[Flag] = Field(default_factory=list)
    recommendation: str | None = None
    # Preparation for the first visit, and free-text working notes. Both are
    # typed by the clinician on the case itself — the per-visit equivalents
    # live on Consultation.
    pre_consultation_details: str | None = None
    notes: str | None = None
    # Written by the coding tool from the consultation summaries; empty until
    # the case has been consulted on, and cleared by every agent run.
    medical_codes: list[MedicalCode] = Field(default_factory=list)
    is_urgent: bool = False
    urgency_reason: str | None = None
    # The personalised form: which of the standard questions this patient is
    # asked. Empty until it has been worked out, and the public form falls
    # back to asking everything while it is.
    questionnaire_questions: list[QuestionnaireQuestion] = Field(
        default_factory=list
    )
    questionnaire_generated_at: datetime | None = None
    # Set when the patient submits the public questionnaire, and again once a
    # clinician has folded those answers into the case.
    patient_recording_completed: bool = False
    patient_recording_reconciled: bool = False
    status: CaseStatus = CaseStatus.NEW
