from app.models.common import MongoModel, PyObjectId

COLLECTION = "surgeries"


class Surgery(MongoModel):
    case: PyObjectId  # -> cases._id
    appointment: PyObjectId  # -> appointments._id
    pre_surgery_plan: str | None = None
    op_notes_transcription: str | None = None
    op_notes_summary: str | None = None
    procedure_code: str | None = None
