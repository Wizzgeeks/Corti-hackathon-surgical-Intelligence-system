"""What a consultant team's day looks like, in counts.

One request answers the whole page: how much is booked, what kind of work it
is, and how much of it is flagged. The classification of a consultation —
new, follow-up, or post-surgery — is not stored anywhere; it is derived from
what else the case has booked, which is why this lives on the server rather
than being assembled from several calls in the browser.

    GET  /today?consultant_team_id=...&date=2026-08-20
    POST /today/speech   {"text": "..."}

    200 {
      "consultant_team_id": "6a855a...",
      "date": "2026-08-20",
      "cases": 7,
      "consultations": 6,
      "surgeries": 2,
      "new_consultations": 3,
      "follow_up_consultations": 2,
      "post_surgery_consultations": 1,
      "high_flag_cases": 2,
      "appointments": [...],
      "summary_text": "Good morning. Today you have 7 cases: ..."
    }

    400 invalid team id or date
"""

import hashlib
import json
import logging
import re
from datetime import date as date_type
from datetime import datetime, time
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models.common import utcnow
from app.models.daily_briefing import DailyBriefing
from app.services.corti_textgen import generate_text
from app.services.elevenlabs import SpeechError, speak
from app.models import appointment as appointment_model
from app.models import case as case_model
from app.models import consultant_team as team_model
from app.models import daily_briefing as briefing_model
from app.models import patient as patient_model

logger = logging.getLogger(__name__)

router = APIRouter(tags=["today"])

CANCELLED = "cancelled"
SURGERY = "surgery"
CONSULTATION = "consultation"
# Severities that should stand out on the day view.
HIGH_SEVERITIES = {"high", "critical"}


class TodayAppointment(BaseModel):
    """One booking on the day, as it is read out."""

    appointment_id: str
    case_id: str = ""
    time: str = ""  # "09:00"
    appointment_type: str = ""
    # new | follow_up | post_surgery, for consultations only.
    category: str = ""
    patient_name: str = ""
    patient_age: int | None = None
    patient_gender: str = ""
    flags: list[str] = Field(default_factory=list)
    has_high_flag: bool = False


class TodaySummary(BaseModel):
    consultant_team_id: str
    date: date_type
    # Distinct cases the team sees today, however many appointments each has.
    cases: int = 0
    consultations: int = 0
    surgeries: int = 0
    # The consultations above, split by what the case has been through.
    new_consultations: int = 0
    follow_up_consultations: int = 0
    post_surgery_consultations: int = 0
    # Cases seen today carrying a high or critical flag.
    high_flag_cases: int = 0
    appointments: list[TodayAppointment] = Field(default_factory=list)
    # The same day written out as prose, for reading aloud on the way in.
    summary_text: str = ""
    # False when Corti was unreachable and the plain summary was used.
    briefing_by_corti: bool = False


def day_bounds(day: date_type) -> tuple[datetime, datetime]:
    """Appointments are stored as local naive datetimes, so the day is too."""
    return datetime.combine(day, time.min), datetime.combine(day, time.max)


def is_live(appointment: dict) -> bool:
    return appointment.get("status") != CANCELLED


CATEGORY_WORDS = {
    "new": "new consultation",
    "follow_up": "follow-up consultation",
    "post_surgery": "post-surgery consultation",
}


def spoken_time(when: datetime | None) -> str:
    """"09:00" -> "9 oh 5" reads badly; a plain 24-hour clock does not.

    Speech engines say "9:05" correctly, so the clock is left as digits and
    only the leading zero is dropped, which would otherwise be read as
    "zero nine".
    """
    if not when:
        return ""
    return f"{when.hour}:{when.minute:02d}"


def describe_patient(patient: dict | None) -> str:
    """"Melissa Pearce, 47, female" — the identifying line, spoken."""
    if not patient:
        return "an unnamed patient"
    parts = [str(patient.get("name") or "").strip() or "an unnamed patient"]
    age = patient.get("age")
    if age:
        parts.append(f"{age}")
    gender = str(patient.get("gender") or "").strip()
    if gender:
        parts.append(gender.lower())
    return ", ".join(parts)


def build_briefing(
    day: date_type,
    team_name: str,
    counts: dict[str, int],
    items: list[TodayAppointment],
) -> str:
    """The day as prose, for a screen reader or the car.

    Written to be *heard*: short sentences, no abbreviations a speech engine
    would spell out, and the flagged patients called out by name rather than
    left as a number the listener has to hold on to.
    """
    when = day.strftime("%A %d %B")
    who = f" for {team_name}" if team_name else ""

    if not items:
        return f"{when}{who}. Nothing is booked today."

    lines: list[str] = []
    total = counts["cases"]
    lines.append(
        f"{when}{who}. You have {total} "
        f"{'case' if total == 1 else 'cases'} today: "
        f"{counts['consultations']} "
        f"{'consultation' if counts['consultations'] == 1 else 'consultations'} "
        f"and {counts['surgeries']} "
        f"{'surgery' if counts['surgeries'] == 1 else 'surgeries'}."
    )

    breakdown = [
        (counts["new_consultations"], "new"),
        (counts["follow_up_consultations"], "follow-up"),
        (counts["post_surgery_consultations"], "post-surgery"),
    ]
    said = [f"{n} {word}" for n, word in breakdown if n]
    if said:
        lines.append("Of the consultations, " + ", ".join(said) + ".")

    flagged = counts["high_flag_cases"]
    if flagged:
        lines.append(
            f"{flagged} {'case carries' if flagged == 1 else 'cases carry'} "
            "a high flag."
        )

    lines.append("Here is the list.")
    for item in items:
        kind = CATEGORY_WORDS.get(item.category) or (
            "surgery" if item.appointment_type == SURGERY else "consultation"
        )
        sentence = f"At {item.time}, {item.patient_name}"
        if item.patient_age:
            sentence += f", {item.patient_age}"
        if item.patient_gender:
            sentence += f", {item.patient_gender.lower()}"
        sentence += f". {kind.capitalize()}."
        if item.flags:
            sentence += " Flags: " + "; ".join(item.flags) + "."
        lines.append(sentence)

    return " ".join(lines)


BRIEFING_NAME = "Daily consultant briefing"
BRIEFING_HEADING = "Today"
BRIEFING_PROMPT = (
    "You are briefing a consultant on their clinic list before they arrive. "
    "Write it to be listened to, not read: short sentences, no abbreviations, "
    "no headings, no bullet points, no markdown."
)
BRIEFING_CONTENT_PROMPT = (
    "Open with the date and how many cases, consultations and surgeries there "
    "are. Then take each appointment in time order and say the time, the "
    "patient's name, their age and sex, and whether it is a new consultation, "
    "a follow-up, a post-surgery review or a surgery. Where a case carries "
    "flags, say what they are and how severe. Mention anything in the case "
    "summary or recommendation that changes what the consultant should do "
    "today. Do not invent anything that is not in the material given."
)
BRIEFING_STYLE = "Plain spoken English, calm and factual, in the second person."


def briefing_context(
    day: date_type, team_name: str, totals: dict[str, int], items: list[TodayAppointment],
    case_notes: dict[str, dict[str, Any]],
) -> str:
    """The material Corti writes the briefing from.

    Handed over as plain text rather than JSON: the model is being asked to
    speak it, and the shape of the day reads better than a data structure.
    """
    lines = [
        f"Date: {day.strftime('%A %d %B %Y')}",
        f"Consultant: {team_name or 'unnamed'}",
        (
            f"Totals: {totals['cases']} cases, {totals['consultations']} "
            f"consultations, {totals['surgeries']} surgeries, "
            f"{totals['new_consultations']} new, "
            f"{totals['follow_up_consultations']} follow-up, "
            f"{totals['post_surgery_consultations']} post-surgery, "
            f"{totals['high_flag_cases']} with a high flag."
        ),
        "",
        "Appointments:",
    ]
    for item in items:
        kind = CATEGORY_WORDS.get(item.category) or item.appointment_type
        line = (
            f"- {item.time} {item.patient_name}"
            f"{f', {item.patient_age}' if item.patient_age else ''}"
            f"{f', {item.patient_gender}' if item.patient_gender else ''}. {kind}."
        )
        if item.flags:
            line += " Flags: " + "; ".join(item.flags) + "."
        notes = case_notes.get(item.case_id) or {}
        if notes.get("case_summary"):
            line += f" Case summary: {notes['case_summary']}"
        if notes.get("recommendation"):
            line += f" Recommendation: {notes['recommendation']}"
        lines.append(line)
    return "\n".join(lines)


def fingerprint(items: list[TodayAppointment], totals: dict[str, int]) -> str:
    """Identifies the day's list, so a stored briefing can be spotted as stale.

    Covers what a briefing would have to change for: who is booked, when, what
    kind of appointment, and what is flagged.
    """
    material = json.dumps(
        {
            "totals": totals,
            "items": [
                [i.appointment_id, i.time, i.category, i.patient_name, i.flags]
                for i in items
            ],
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def briefing_for_day(
    team_oid: ObjectId,
    day: date_type,
    team_name: str,
    totals: dict[str, int],
    items: list[TodayAppointment],
    case_notes: dict[str, dict[str, Any]],
    refresh: bool = False,
) -> tuple[str, bool]:
    """The stored briefing for this team and day, generating one if needed.

    Returns `(text, from_corti)`. Regenerated when the day's list has changed
    since it was written, or when `refresh` is asked for — otherwise the
    stored one is returned untouched, which is the common case: the page is
    opened repeatedly through a morning that does not change.

    A Corti failure is not fatal. The plainly-assembled summary is stored
    instead and marked as such, so the page always has something to read and
    the next request tries Corti again.
    """
    briefings = get_collection(briefing_model.COLLECTION)
    key = {"consultant": team_oid, "date": str(day)}
    stamp = fingerprint(items, totals)

    stored = await briefings.find_one(key)
    if (
        stored
        and not refresh
        and stored.get("source_fingerprint") == stamp
        and stored.get("text")
        and stored.get("generated_by_corti")
    ):
        return stored["text"], True

    fallback = build_briefing(day, team_name, totals, items)
    text, by_corti = fallback, False

    if items:
        try:
            result = await generate_text(
                name=BRIEFING_NAME,
                heading=BRIEFING_HEADING,
                prompt=BRIEFING_PROMPT,
                content_prompt=BRIEFING_CONTENT_PROMPT,
                context_text=briefing_context(day, team_name, totals, items, case_notes),
                access_token=None,
                writing_style_prompt=BRIEFING_STYLE,
            )
        except Exception as exc:  # noqa: BLE001 — the day still needs a briefing
            logger.warning("Corti could not write the briefing: %s", exc)
        else:
            if (result.text or "").strip():
                text, by_corti = result.text.strip(), True

    record = DailyBriefing(
        consultant=team_oid,
        date=str(day),
        text=text,
        source_fingerprint=stamp,
        generated_at=utcnow(),
        generated_by_corti=by_corti,
    ).to_mongo()
    # Replaced rather than appended: one briefing per team per day.
    await briefings.update_one(key, {"$set": record}, upsert=True)
    logger.info(
        "Briefing for %s on %s %s.",
        team_oid,
        day,
        "written by Corti" if by_corti else "assembled locally",
    )
    return text, by_corti


@router.get("/today", response_model=TodaySummary)
async def today_summary(
    consultant_team_id: str = Query(..., description="The team whose day this is."),
    day: date_type | None = Query(None, alias="date"),
    refresh: bool = Query(
        False, description="Rewrite the briefing even if a current one is stored."
    ),
) -> TodaySummary:
    """Summarise one team's day."""
    if not ObjectId.is_valid(consultant_team_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{consultant_team_id!r} is not a valid consultant team id.",
        )

    team_oid = ObjectId(consultant_team_id)
    day = day or datetime.now().date()
    start, end = day_bounds(day)

    appointments = get_collection(appointment_model.COLLECTION)
    todays = [
        a
        for a in await appointments.find(
            {"consultant": team_oid, "start_time": {"$gte": start, "$lte": end}}
        )
        .sort("start_time", 1)
        .to_list(length=500)
        if is_live(a)
    ]

    consultations = [a for a in todays if a.get("appointment_type") == CONSULTATION]
    surgeries = [a for a in todays if a.get("appointment_type") == SURGERY]
    case_ids = {a["case"] for a in todays if a.get("case")}

    # Everything these cases have ever had booked, so a consultation can be
    # placed against the rest of the case rather than judged on its own. Not
    # limited to this team: a follow-up is still a follow-up when the first
    # visit was with someone else.
    history: dict[Any, list[dict]] = {}
    if case_ids:
        for a in (
            await appointments.find({"case": {"$in": list(case_ids)}})
            .sort("start_time", 1)
            .to_list(length=2000)
        ):
            if is_live(a):
                history.setdefault(a["case"], []).append(a)

    counts = {"new": 0, "follow_up": 0, "post_surgery": 0}
    category_by_id: dict[Any, str] = {}
    for appointment in consultations:
        case_id = appointment.get("case")
        earlier = [
            a
            for a in history.get(case_id, [])
            if a["_id"] != appointment["_id"]
            and a.get("start_time")
            and appointment.get("start_time")
            and a["start_time"] < appointment["start_time"]
        ]
        if any(a.get("appointment_type") == SURGERY for a in earlier):
            # Seen after an operation — the most specific of the three, so it
            # wins over "they have been here before".
            category = "post_surgery"
        elif any(a.get("appointment_type") == CONSULTATION for a in earlier):
            category = "follow_up"
        else:
            category = "new"
        counts[category] += 1
        category_by_id[appointment["_id"]] = category

    # Flags are read per case rather than counted, because the briefing names
    # what each one is instead of leaving the listener with a number.
    flags_by_case: dict[Any, list[dict]] = {}
    case_notes: dict[str, dict[str, Any]] = {}
    if case_ids:
        async for case in get_collection(case_model.COLLECTION).find(
            {"_id": {"$in": list(case_ids)}},
            {"flags": 1, "case_summary": 1, "recommendation": 1},
        ):
            flags_by_case[case["_id"]] = case.get("flags") or []
            # Carried into the briefing so it can say what today is actually
            # about, not just who is booked.
            case_notes[str(case["_id"])] = {
                "case_summary": (case.get("case_summary") or "").strip(),
                "recommendation": (case.get("recommendation") or "").strip(),
            }

    high_flag_cases = sum(
        1
        for flags in flags_by_case.values()
        if any(
            str(f.get("severity") or "").lower() in HIGH_SEVERITIES for f in flags
        )
    )

    patients: dict[Any, dict] = {}
    patient_ids = [a["patient"] for a in todays if a.get("patient")]
    if patient_ids:
        async for patient in get_collection(patient_model.COLLECTION).find(
            {"_id": {"$in": patient_ids}}
        ):
            patients[patient["_id"]] = patient

    items: list[TodayAppointment] = []
    for appointment in todays:
        case_flags = flags_by_case.get(appointment.get("case"), [])
        patient = patients.get(appointment.get("patient"))
        items.append(
            TodayAppointment(
                appointment_id=str(appointment.get("_id", "")),
                case_id=str(appointment.get("case") or ""),
                time=spoken_time(appointment.get("start_time")),
                appointment_type=appointment.get("appointment_type", ""),
                category=category_by_id.get(appointment["_id"], ""),
                patient_name=str((patient or {}).get("name") or "").strip()
                or "Unnamed patient",
                patient_age=(patient or {}).get("age"),
                patient_gender=str((patient or {}).get("gender") or ""),
                # Read out as "label, severity" so the listener hears how bad
                # it is straight after what it is.
                flags=[
                    ", ".join(
                        part
                        for part in (
                            str(f.get("label") or "").strip(),
                            str(f.get("severity") or "").strip(),
                        )
                        if part
                    )
                    for f in case_flags
                    if f.get("label") or f.get("severity")
                ],
                has_high_flag=any(
                    str(f.get("severity") or "").lower() in HIGH_SEVERITIES
                    for f in case_flags
                ),
            )
        )

    logger.info(
        "Team %s on %s: %d appointment(s) across %d case(s)",
        consultant_team_id,
        day,
        len(todays),
        len(case_ids),
    )
    totals = {
        "cases": len(case_ids),
        "consultations": len(consultations),
        "surgeries": len(surgeries),
        "new_consultations": counts["new"],
        "follow_up_consultations": counts["follow_up"],
        "post_surgery_consultations": counts["post_surgery"],
        "high_flag_cases": high_flag_cases,
    }

    team = await get_collection(team_model.COLLECTION).find_one(
        {"_id": team_oid}, {"name": 1}
    )

    team_name = str((team or {}).get("name") or "")
    summary_text, by_corti = await briefing_for_day(
        team_oid, day, team_name, totals, items, case_notes, refresh=refresh
    )

    return TodaySummary(
        consultant_team_id=consultant_team_id,
        date=day,
        **totals,
        appointments=items,
        summary_text=summary_text,
        briefing_by_corti=by_corti,
    )


# --- Reading it out --------------------------------------------------------

# Sentence-ish: everything up to a full stop, question or exclamation mark.
SENTENCE = re.compile(r"[^.!?]+[.!?]*", re.S)


class SpeechRequest(BaseModel):
    text: str


class SentenceSpan(BaseModel):
    """One sentence, and when it is spoken."""

    text: str
    # Offsets into the original text, so the page highlights the exact run.
    start: int
    end: int
    start_seconds: float = 0.0
    end_seconds: float = 0.0


class SpeechResponse(BaseModel):
    # mp3, base64 — played straight from a data URL.
    audio_base64: str
    duration_seconds: float = 0.0
    sentences: list[SentenceSpan] = Field(default_factory=list)


def sentence_spans(text: str, alignment: dict[str, Any]) -> list[SentenceSpan]:
    """Turn per-character timings into per-sentence ones.

    ElevenLabs times every character; a page cannot usefully highlight a
    character, so each sentence takes the start of its first character and the
    end of its last. The character list is assumed to line up with the text
    that was sent — it does — but the indexes are clamped anyway, since being
    one character short is not worth a 500.
    """
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not starts or not ends:
        return []

    spans: list[SentenceSpan] = []
    for match in SENTENCE.finditer(text):
        body = match.group()
        if not body.strip():
            continue
        first = min(match.start(), len(starts) - 1)
        last = min(match.end() - 1, len(ends) - 1)
        spans.append(
            SentenceSpan(
                text=body.strip(),
                start=match.start(),
                end=match.end(),
                start_seconds=float(starts[first]),
                end_seconds=float(ends[last]),
            )
        )
    return spans


@router.post("/today/speech", response_model=SpeechResponse)
async def speak_briefing(payload: SpeechRequest) -> SpeechResponse:
    """Read a briefing aloud.

    Proxied rather than called from the browser so the ElevenLabs key stays
    on the server. The response carries the audio and the sentence timings
    together, so the page can start playing and highlighting from one call.
    """
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="There is nothing to read out."
        )

    try:
        result = await speak(text)
    except SpeechError as exc:
        # 401/402 are about the account, not the request — pass the reason
        # through so the page can say which it was.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Text to speech failed: {exc}"
        ) from exc

    spans = sentence_spans(text, result["alignment"])
    return SpeechResponse(
        audio_base64=result["audio_base64"],
        duration_seconds=spans[-1].end_seconds if spans else 0.0,
        sentences=spans,
    )
