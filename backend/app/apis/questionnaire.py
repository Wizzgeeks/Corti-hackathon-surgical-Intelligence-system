"""The patient's own questionnaire — a public form, one link per case.

These two routes are the only ones in the app a patient reaches, so they are
deliberately narrow: the form is served the questions and the name of whoever
referred them, and takes back answers. Nothing else about the case leaves
here — no summary, no flags, no clinical detail — because the link carries no
login and anyone holding it can call these.

    GET  /public/cases/{case_id}/questionnaire
    POST /public/cases/{case_id}/questionnaire
    GET  /cases/{case_id}/questionnaire            (clinician)
    POST /cases/{case_id}/questionnaire/reconcile  (clinician)

    curl 'http://127.0.0.1:8000/public/cases/6a855a.../questionnaire'

    200 {
      "case_id": "6a855a...",
      "patient_name": "Melissa",
      "referred_by": "Dr Andie Fulton, Bryndwr Medical Rooms",
      "completed": false,
      "questions": [{"order": 1, "question": "Has there been any changes..."}]
    }

    400 invalid case id · 404 unknown case
"""

import logging
import re
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models import case as case_model
from app.models import patient as patient_model
from app.models import patient_questionnaire as questionnaire_model
from app.models.common import utcnow
from app.models.case import QuestionnaireQuestion
from app.models.patient_questionnaire import PatientQuestionnaire
from app.services.corti_textgen import extract_facts, format_facts, generate_text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["patient_questionnaire"])

# The form, in order. Kept here rather than in the database: the answers store
# the question they were asked, so editing this list never rewrites history.
QUESTIONS: tuple[str, ...] = (
    "Has there been any changes to your symptoms, since you last saw your referrer?",
    "Have you ever been hospitalised in the last 3 years? If yes, what was it for "
    "and for how long?",
    "Do you have any major medical illness that your specialist should be aware of? "
    "Can you name them and mention any relevant details that your specialist should "
    "be aware of?",
    "Describe any accessibility issues that you may need support with at the time of "
    "your clinic visit?",
    "Are you allergic to any drug(s)? If so, name the drug(s) and describe the "
    "allergic reaction.",
    "Are you taking any blood thinners, anti-diabetic or other medication that your "
    "specialist should be aware of?",
    "Is your consult with our specialist related to a work place injury?",
    "Who is your insurance funder?",
    "Are there any other information that you would like to provide us that may help "
    "during your consultation with the specialist?",
)


class QuestionItem(BaseModel):
    order: int
    question: str
    reason: str = ""


# --- personalising the form ------------------------------------------------

# A patient will not work through a long form, and the ones that matter are
# at the top of it. Anything past this is dropped.
MAX_QUESTIONS = 4

PERSONALISE_PROMPT = (
    "You are preparing a pre-appointment questionnaire for a patient. "
    "You are given the clinical background already on file, and a numbered "
    "list of standard questions."
)

PERSONALISE_CONTENT_PROMPT = (
    "Decide which of the numbered questions still need to be asked, and pick "
    "at most FOUR of them — the four that would change this patient's care "
    "the most. "
    "A question should be SKIPPED when the clinical background already "
    "answers it clearly and specifically. Prefer questions the background is "
    "silent on, and questions only the patient can answer — allergies, "
    "medication, accessibility needs, workplace injury, insurance — over "
    "ones the notes already cover. "
    "Reply with nothing but the numbers of the questions to ASK, separated "
    "by commas, MOST IMPORTANT FIRST. At most four numbers. No words, no "
    "explanation, no punctuation other than the commas. Example: 5,3,9,1"
)


def personalise_context(clinical_background: str) -> str:
    """The background and the numbered form, as one block of text."""
    numbered = "\n".join(
        f"{index + 1}. {question}" for index, question in enumerate(QUESTIONS)
    )
    background = (clinical_background or "").strip() or "(nothing on file)"
    return (
        f"CLINICAL BACKGROUND ALREADY ON FILE:\n{background}\n\n"
        f"STANDARD QUESTIONS:\n{numbered}"
    )


def parse_question_numbers(text: str) -> list[int]:
    """Read "5,3,9" back into question numbers, most important first.

    Tolerant of the model answering with prose around the list: every number
    in range is taken, anything else ignored. The order it answered in is
    kept — it is asked for most-important-first, and that is what decides
    which survive the cap — while duplicates are dropped.
    """
    seen: list[int] = []
    for chunk in re.findall(r"\d+", text or ""):
        number = int(chunk)
        if 1 <= number <= len(QUESTIONS) and number not in seen:
            seen.append(number)
    return seen




class QuestionnaireForm(BaseModel):
    """Everything the public form is allowed to know about the case."""

    case_id: str
    patient_name: str = ""
    # "Dr Andie Fulton, Bryndwr Medical Rooms" — who the referral came from.
    referred_by: str = ""
    completed: bool = False
    questions: list[QuestionItem] = Field(default_factory=list)


class AnswerIn(BaseModel):
    order: int = 0
    question: str
    answer: str = ""


class QuestionnaireSubmission(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list)


class SubmissionResponse(BaseModel):
    case_id: str
    answered: int
    completed: bool = True


def case_oid(case_id: str) -> ObjectId:
    if not ObjectId.is_valid(case_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="That form link is not valid."
        )
    return ObjectId(case_id)


async def load_case(case_id: str) -> dict:
    doc = await get_collection(case_model.COLLECTION).find_one({"_id": case_oid(case_id)})
    if not doc:
        # Deliberately vague: this is a public endpoint, and confirming which
        # case ids exist is not something a stranger needs to learn.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="That form link is not valid."
        )
    return doc


def referrer_line(case: dict) -> str:
    """The referrer as one readable line, for 'we got your referral from …'."""
    referrers: list[dict[str, Any]] = case.get("referred_by") or []
    if not referrers:
        return ""
    first = referrers[0] or {}
    name = str(first.get("name") or "").strip()
    organization = str(first.get("organization") or "").strip()
    role = str(first.get("role") or "").strip()

    who = name or role or organization
    if name and role:
        who = f"{name} ({role})"
    if organization and organization != who:
        return f"{who}, {organization}" if who else organization
    return who


class PersonaliseRequest(BaseModel):
    # Work it out again even though the case already has a set.
    refresh: bool = False


class PersonaliseResponse(BaseModel):
    case_id: str
    questions: list[QuestionItem] = Field(default_factory=list)
    # True when these came off the case rather than from Corti just now.
    cached: bool = False
    # How many of the standard questions were dropped as already answered.
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


def fallback_questions() -> list[QuestionItem]:
    """What to ask when personalising could not be done.

    The first few of the standard form rather than all nine: the cap is a
    promise to the patient about how long this takes, and a failure upstream
    is not a reason to break it.
    """
    return [
        QuestionItem(order=index + 1, question=question)
        for index, question in enumerate(QUESTIONS[:MAX_QUESTIONS])
    ]


@router.post(
    "/cases/{case_id}/questionnaire/personalise",
    response_model=PersonaliseResponse,
)
async def personalise_questionnaire(
    case_id: str, payload: PersonaliseRequest | None = None
) -> PersonaliseResponse:
    """Work out which questions this patient still needs to be asked.

    The clinical background and the standard form go to Corti together, and
    what comes back is the numbers of the questions the background does not
    already answer. Those are stored on the case, so the patient's link and
    every later read use the same set.

    Safe by default: if Corti fails, or answers with nothing usable, the case
    keeps the whole form. Asking a patient a question twice is a small cost;
    never asking is not.
    """
    options = payload or PersonaliseRequest()
    oid = case_oid(case_id)
    case = await load_case(case_id)

    stored = case.get("questionnaire_questions") or []
    if stored and not options.refresh:
        return PersonaliseResponse(
            case_id=case_id,
            questions=[QuestionItem(**item) for item in stored],
            cached=True,
            skipped=len(QUESTIONS) - len(stored),
        )

    errors: list[str] = []
    numbers: list[int] = []
    try:
        result = await generate_text(
            name="Questionnaire personalisation",
            heading="Questions to ask",
            prompt=PERSONALISE_PROMPT,
            content_prompt=PERSONALISE_CONTENT_PROMPT,
            context_text=personalise_context(case.get("clinical_background") or ""),
            access_token=None,
        )
        numbers = parse_question_numbers(result.text)
        if not numbers:
            errors.append(
                "The model did not name any questions, so the whole form is "
                "being asked."
            )
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        logger.exception("questionnaire personalisation failed for %s", case_id)
        errors.append(f"Could not personalise the form: {exc}")

    # Capped by priority — the model answers most-important-first — then put
    # back into form order, which is the order they read best in.
    chosen = sorted(numbers[:MAX_QUESTIONS])
    questions = (
        [
            QuestionItem(order=number, question=QUESTIONS[number - 1])
            for number in chosen
        ]
        if chosen
        else fallback_questions()
    )

    await get_collection(case_model.COLLECTION).update_one(
        {"_id": oid},
        {
            "$set": {
                "questionnaire_questions": [
                    QuestionnaireQuestion(**item.model_dump()).model_dump(mode="json")
                    for item in questions
                ],
                "questionnaire_generated_at": utcnow(),
                "updated_at": utcnow(),
            }
        },
    )

    logger.info(
        "personalise_questionnaire: case %s -> %d of %d question(s), %d error(s)",
        case_id,
        len(questions),
        len(QUESTIONS),
        len(errors),
    )

    return PersonaliseResponse(
        case_id=case_id,
        questions=questions,
        skipped=len(QUESTIONS) - len(questions),
        errors=errors,
    )


@router.get(
    "/public/cases/{case_id}/questionnaire", response_model=QuestionnaireForm
)
async def get_questionnaire(case_id: str) -> QuestionnaireForm:
    """The form: who referred them, and what to ask."""
    case = await load_case(case_id)

    patient_name = ""
    if case.get("patient"):
        patient = await get_collection(patient_model.COLLECTION).find_one(
            {"_id": case["patient"]}, {"name": 1}
        )
        # First name only — enough to address them, without putting a full
        # identity behind an unauthenticated link.
        patient_name = str((patient or {}).get("name") or "").split(" ")[0]

    return QuestionnaireForm(
        case_id=case_id,
        patient_name=patient_name,
        referred_by=referrer_line(case),
        completed=bool(case.get("patient_recording_completed")),
        # The personalised set when one has been worked out; the whole form
        # until then, so a link opened early still asks everything rather
        # than nothing.
        questions=(
            [QuestionItem(**item) for item in stored]
            if (stored := case.get("questionnaire_questions") or [])
            else fallback_questions()
        ),
    )


@router.post(
    "/public/cases/{case_id}/questionnaire",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_questionnaire(
    case_id: str, payload: QuestionnaireSubmission
) -> SubmissionResponse:
    """Store the answers and mark the case as answered.

    A resubmission replaces the previous answers rather than adding a second
    set — the patient reopening the link and correcting themselves is the
    expected case, not a new questionnaire.
    """
    oid = case_oid(case_id)
    await load_case(case_id)

    answered = [a for a in payload.answers if (a.answer or "").strip()]
    if not answered:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Please answer at least one question before submitting.",
        )

    questionnaires = get_collection(questionnaire_model.COLLECTION)
    await questionnaires.delete_many({"case": oid})
    await questionnaires.insert_many(
        [
            PatientQuestionnaire(
                case=oid,
                question=a.question.strip(),
                answer=a.answer.strip(),
                order=a.order or index + 1,
            ).to_mongo()
            for index, a in enumerate(answered)
        ]
    )

    # Answered, but nobody has read them into the case yet.
    await get_collection(case_model.COLLECTION).update_one(
        {"_id": oid},
        {
            "$set": {
                "patient_recording_completed": True,
                "patient_recording_reconciled": False,
                "updated_at": utcnow(),
            }
        },
    )

    logger.info("Case %s: patient answered %d question(s)", case_id, len(answered))
    return SubmissionResponse(case_id=case_id, answered=len(answered))


# --- Clinician side --------------------------------------------------------


class AnswerRead(BaseModel):
    order: int = 0
    question: str = ""
    answer: str = ""


class AnswerListResponse(BaseModel):
    case_id: str
    completed: bool = False
    reconciled: bool = False
    answers: list[AnswerRead] = Field(default_factory=list)


class ReconcileResponse(BaseModel):
    case_id: str
    # The rewritten background, as stored on the patient.
    clinical_background: str = ""
    fact_count: int = 0
    reconciled: bool = False
    errors: list[str] = Field(default_factory=list)


async def load_answers(oid: ObjectId) -> list[dict]:
    return (
        await get_collection(questionnaire_model.COLLECTION)
        .find({"case": oid})
        .sort("order", 1)
        .to_list(length=100)
    )


def as_context(answers: list[dict], background: str) -> str:
    """What FactsR is asked to read: the background, then the patient's words.

    The existing background goes first so the facts already on file are part
    of the same extraction — the point of reconciling is one brief covering
    both, not the questionnaire on its own.
    """
    blocks = []
    if background.strip():
        blocks.append(f"Known clinical background:\n{background.strip()}")
    if answers:
        lines = [
            f"Q: {a.get('question', '').strip()}\nA: {a.get('answer', '').strip()}"
            for a in answers
            if (a.get("answer") or "").strip()
        ]
        if lines:
            blocks.append("Patient questionnaire:\n" + "\n\n".join(lines))
    return "\n\n".join(blocks)


@router.get("/cases/{case_id}/questionnaire", response_model=AnswerListResponse)
async def get_answers(case_id: str) -> AnswerListResponse:
    """The patient's answers, for the clinician reviewing them."""
    case = await load_case(case_id)
    answers = await load_answers(case_oid(case_id))
    return AnswerListResponse(
        case_id=case_id,
        completed=bool(case.get("patient_recording_completed")),
        reconciled=bool(case.get("patient_recording_reconciled")),
        answers=[
            AnswerRead(
                order=a.get("order", 0),
                question=a.get("question", ""),
                answer=a.get("answer", ""),
            )
            for a in answers
        ],
    )


@router.post(
    "/cases/{case_id}/questionnaire/reconcile", response_model=ReconcileResponse
)
async def reconcile_questionnaire(case_id: str) -> ReconcileResponse:
    """Fold the patient's answers into the clinical background.

    The answers and the background already on file go to Corti's FactsR
    endpoint together, and the facts that come back replace the background —
    so what the patient said and what the referral said end up as one brief
    rather than two lists to read side by side.

    The case is only marked reconciled when that write actually happened; a
    failed extraction leaves the flag down so it can be run again.
    """
    oid = case_oid(case_id)
    case = await load_case(case_id)

    answers = await load_answers(oid)
    if not answers:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="The patient has not answered the questionnaire yet.",
        )

    patients = get_collection(patient_model.COLLECTION)
    patient = None
    if case.get("patient"):
        patient = await patients.find_one({"_id": case["patient"]})
    background = str((patient or {}).get("clinical_background") or "")

    context = as_context(answers, background)
    errors: list[str] = []
    try:
        result = await extract_facts(context_text=context, access_token=None)
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        logger.exception("Reconciliation failed for case %s", case_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Corti could not read the answers: {exc}",
        ) from exc

    summary = format_facts(result.facts)
    if not summary:
        # Nothing came back, so there is nothing to write and nothing to mark.
        return ReconcileResponse(
            case_id=case_id,
            clinical_background=background,
            errors=["Corti returned no facts for these answers."],
        )

    if patient:
        await patients.update_one(
            {"_id": patient["_id"]},
            {"$set": {"clinical_background": summary, "updated_at": utcnow()}},
        )
    else:
        errors.append("The case has no patient record; background not stored.")

    await get_collection(case_model.COLLECTION).update_one(
        {"_id": oid},
        {"$set": {"patient_recording_reconciled": True, "updated_at": utcnow()}},
    )

    logger.info(
        "Case %s: reconciled %d answer(s) into %d fact(s)",
        case_id,
        len(answers),
        len(result.facts),
    )
    return ReconcileResponse(
        case_id=case_id,
        clinical_background=summary,
        fact_count=len(result.facts),
        reconciled=True,
        errors=errors,
    )
