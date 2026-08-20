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

class Referred_by(BaseModel):
    name: str
    role: str
    organization: str


class ConsultantRequest(BaseModel):
    """One question put to a consultant about this case, and their answer.

    Stored inline on the case rather than in its own collection: a request is
    only ever read as part of its case. `request_id` is generated here so an
    update can target one entry without relying on its position in the list.

    The two times are separate from `created_at`/`updated_at` because the
    exchange is what is being recorded, not when the row was written: a
    request can sit unanswered, which is what an empty `response` and a null
    `responded_time` mean.
    """

    request_id: str = Field(default_factory=lambda: str(ObjectId()))
    consultant_requests: str = ""
    request_time: datetime | None = Field(default_factory=utcnow)
    response: str | None = None
    responded_time: datetime | None = None


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
    # Questions raised with a consultant and their replies, oldest first.
    consultant_requests: list[ConsultantRequest] = Field(default_factory=list)
    is_urgent: bool = False
    urgency_reason: str | None = None
    status: CaseStatus = CaseStatus.NEW
