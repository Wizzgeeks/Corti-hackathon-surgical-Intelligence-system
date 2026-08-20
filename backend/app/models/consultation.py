from app.models.common import MongoModel, PyObjectId

COLLECTION = "consultations"


class Consultation(MongoModel):
    case: PyObjectId  # -> cases._id
    # Optional: a consultation is usually booked, but one can be recorded
    # ad hoc, and the recording is worth keeping either way.
    appointment: PyObjectId | None = None  # -> appointments._id
    # What the patient or clinic must have ready before the appointment —
    # imaging to bring, bloods to have taken, forms to complete.
    # The briefing a consultant reads beforehand: history, findings, context.
    transcription: str | None = None
    consultation_summary: str | None = None
