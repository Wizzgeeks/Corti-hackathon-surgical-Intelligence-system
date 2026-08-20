from datetime import datetime

from pydantic import Field

from app.models.common import MongoModel, PyObjectId, utcnow

COLLECTION = "daily_briefings"


class DailyBriefing(MongoModel):
    """One consultant team's day, written out by Corti and kept.

    Stored rather than generated per request: the same briefing is read
    several times over a morning, and paying for a text generation each time
    a page loads would be both slow and wasteful. One document per team per
    day, replaced when the day's list changes.
    """

    consultant: PyObjectId  # -> consultant_teams._id
    # The day it describes, as "YYYY-MM-DD", not the day it was written.
    # A plain string because BSON has no date-only type: storing a datetime
    # would invite timezone drift on a value that is only ever a calendar day.
    date: str
    text: str = ""
    # What the briefing was generated from, so a stale one can be spotted
    # without re-reading every appointment.
    source_fingerprint: str = ""
    generated_at: datetime = Field(default_factory=utcnow)
    # False when Corti could not be reached and the plain summary was used.
    generated_by_corti: bool = True
