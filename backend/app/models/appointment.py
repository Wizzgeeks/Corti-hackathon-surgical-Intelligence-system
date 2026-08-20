from datetime import datetime

from app.models.common import MongoModel, PyObjectId
from app.models.enums import AppointmentStatus, AppointmentType

COLLECTION = "appointments"


class Appointment(MongoModel):
    patient: PyObjectId  # -> patients._id
    consultant: PyObjectId  # -> consultant_teams._id
    case: PyObjectId | None = None  # -> cases._id
    start_time: datetime
    end_time: datetime
    appointment_type: AppointmentType
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
