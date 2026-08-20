from app.models.common import MongoModel, PyObjectId

COLLECTION = "patient_questionnaires"


class PatientQuestionnaire(MongoModel):
    """One question and the patient's answer, as given on the public form.

    Stored one document per answer rather than one per submission: the
    questions are expected to change over time, and a row that carries the
    question it was asked stays readable when they do.
    """

    case: PyObjectId  # -> cases._id
    question: str
    answer: str = ""
    # Position in the form, so the answers read back in the order asked.
    order: int = 0
