from app.models.common import MongoModel

COLLECTION = "consultant_teams"


class ConsultantTeam(MongoModel):
    name: str
    speciality: str
    description: str | None = None
