"""What a consultant team's day looks like, in counts.

One request answers the whole page: how much is booked, what kind of work it
is, and how much of it is flagged. The classification of a consultation —
new, follow-up, or post-surgery — is not stored anywhere; it is derived from
what else the case has booked, which is why this lives on the server rather
than being assembled from several calls in the browser.

    GET /today?consultant_team_id=...&date=2026-08-20

    200 {
      "consultant_team_id": "6a855a...",
      "date": "2026-08-20",
      "cases": 7,
      "consultations": 6,
      "surgeries": 2,
      "new_consultations": 3,
      "follow_up_consultations": 2,
      "post_surgery_consultations": 1,
      "high_flag_cases": 2
    }

    400 invalid team id or date
"""

import logging
from datetime import date as date_type
from datetime import datetime, time
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import case as case_model

logger = logging.getLogger(__name__)

router = APIRouter(tags=["today"])

CANCELLED = "cancelled"
SURGERY = "surgery"
CONSULTATION = "consultation"
# Severities that should stand out on the day view.
HIGH_SEVERITIES = {"high", "critical"}


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


def day_bounds(day: date_type) -> tuple[datetime, datetime]:
    """Appointments are stored as local naive datetimes, so the day is too."""
    return datetime.combine(day, time.min), datetime.combine(day, time.max)


def is_live(appointment: dict) -> bool:
    return appointment.get("status") != CANCELLED


@router.get("/today", response_model=TodaySummary)
async def today_summary(
    consultant_team_id: str = Query(..., description="The team whose day this is."),
    day: date_type | None = Query(None, alias="date"),
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
            counts["post_surgery"] += 1
        elif any(a.get("appointment_type") == CONSULTATION for a in earlier):
            counts["follow_up"] += 1
        else:
            counts["new"] += 1

    high_flag_cases = 0
    if case_ids:
        high_flag_cases = await get_collection(case_model.COLLECTION).count_documents(
            {
                "_id": {"$in": list(case_ids)},
                "flags.severity": {"$in": list(HIGH_SEVERITIES)},
            }
        )

    logger.info(
        "Team %s on %s: %d appointment(s) across %d case(s)",
        consultant_team_id,
        day,
        len(todays),
        len(case_ids),
    )
    return TodaySummary(
        consultant_team_id=consultant_team_id,
        date=day,
        cases=len(case_ids),
        consultations=len(consultations),
        surgeries=len(surgeries),
        new_consultations=counts["new"],
        follow_up_consultations=counts["follow_up"],
        post_surgery_consultations=counts["post_surgery"],
        high_flag_cases=high_flag_cases,
    )
