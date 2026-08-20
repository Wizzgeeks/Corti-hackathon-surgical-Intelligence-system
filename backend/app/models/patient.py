from pydantic import Field

from app.models.common import MongoModel

COLLECTION = "patients"


class Patient(MongoModel):
    name: str
    age: int = Field(ge=0, le=130)
    clinical_background: str | None = None
    gender: str
    contact: str
    
