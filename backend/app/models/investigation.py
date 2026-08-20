from datetime import datetime

from pydantic import Field

from app.models.common import MongoModel, PyObjectId
from app.models.enums import InvestigationStatus

COLLECTION = "investigation_details"


class InvestigationDetails(MongoModel):
    """An investigation ordered for a case — imaging, bloods, a procedure.

    Hangs off the case rather than the consultation: an investigation is often
    ordered before the first appointment and reported after it, so tying it to
    a single consultation would lose that.
    """

    case: PyObjectId  # -> cases._id
    # Set when the investigation was ordered at, or reviewed in, a specific
    name: str
    transcription: str
    summary: str
    reported_at: datetime | None = None
    # Report files, images — stored elsewhere, referenced here.
    attachments: list[str] = Field(default_factory=list)
