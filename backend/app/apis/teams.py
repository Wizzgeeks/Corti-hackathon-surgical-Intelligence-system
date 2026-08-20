"""CRUD for consultant teams.

A team is the unit a case is assigned to and an appointment is booked with,
so it is referenced by both — which is why deleting one that is still in use
is refused rather than silently orphaning those records.

    POST   /consultant_teams
    GET    /consultant_teams?limit=50&skip=0&q=ortho
    GET    /consultant_teams/{team_id}
    PATCH  /consultant_teams/{team_id}
    DELETE /consultant_teams/{team_id}

    curl -X POST 'http://127.0.0.1:8000/consultant_teams' \
      -H 'Content-Type: application/json' \
      -d '{"name": "Orthopaedics", "speciality": "Orthopaedics",
           "description": "Knee and lower limb"}'
"""

import logging
from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import consultant_team as team_model
from app.models.common import utcnow
from app.models.consultant_team import ConsultantTeam

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consultant_teams"], prefix="/consultant_teams")


class TeamCreate(BaseModel):
    name: str = Field(min_length=1)
    speciality: str = ""
    description: str | None = None


class TeamPatch(BaseModel):
    """Every field optional — only what is sent gets written."""

    name: str | None = Field(default=None, min_length=1)
    speciality: str | None = None
    description: str | None = None


class TeamRead(BaseModel):
    consultant_team_id: str
    name: str = ""
    speciality: str = ""
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TeamListResponse(BaseModel):
    total: int
    limit: int
    skip: int
    teams: list[TeamRead] = Field(default_factory=list)


def to_team(doc: dict) -> TeamRead:
    return TeamRead(
        consultant_team_id=str(doc.get("_id", "")),
        name=doc.get("name", ""),
        speciality=doc.get("speciality", ""),
        description=doc.get("description"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


def team_oid(team_id: str) -> ObjectId:
    if not ObjectId.is_valid(team_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{team_id!r} is not a valid consultant team id.",
        )
    return ObjectId(team_id)


async def load_team(team_id: str) -> dict:
    doc = await get_collection(team_model.COLLECTION).find_one({"_id": team_oid(team_id)})
    if not doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No consultant team with id {team_id}."
        )
    return doc


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(payload: TeamCreate) -> TeamRead:
    """Add a consultant team."""
    team = ConsultantTeam(
        name=payload.name.strip(),
        speciality=payload.speciality,
        description=payload.description,
    )
    teams = get_collection(team_model.COLLECTION)

    # `name` is uniquely indexed, so a duplicate is a client error, not a 500.
    if await teams.find_one({"name": team.name}, {"_id": 1}):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A consultant team named {team.name!r} already exists.",
        )

    result = await teams.insert_one(team.to_mongo())
    logger.info("Created consultant team %s", result.inserted_id)
    return to_team(await teams.find_one({"_id": result.inserted_id}))


@router.get("", response_model=TeamListResponse)
async def list_teams(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    q: str | None = Query(None, description="Match name or speciality."),
) -> TeamListResponse:
    """List consultant teams, alphabetically."""
    query: dict[str, Any] = {}
    if q:
        pattern = {"$regex": q, "$options": "i"}
        query["$or"] = [{"name": pattern}, {"speciality": pattern}]

    teams = get_collection(team_model.COLLECTION)
    total = await teams.count_documents(query)
    docs = (
        await teams.find(query).sort("name", 1).skip(skip).limit(limit).to_list(
            length=limit
        )
    )
    return TeamListResponse(
        total=total, limit=limit, skip=skip, teams=[to_team(d) for d in docs]
    )


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(team_id: str) -> TeamRead:
    return to_team(await load_team(team_id))


@router.patch("/{team_id}", response_model=TeamRead)
async def update_team(team_id: str, payload: TeamPatch) -> TeamRead:
    """Update any subset of a team."""
    oid = team_oid(team_id)
    await load_team(team_id)

    update = payload.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update — send at least one field.",
        )

    teams = get_collection(team_model.COLLECTION)
    if "name" in update and update["name"]:
        update["name"] = update["name"].strip()
        clash = await teams.find_one(
            {"name": update["name"], "_id": {"$ne": oid}}, {"_id": 1}
        )
        if clash:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"A consultant team named {update['name']!r} already exists.",
            )

    update["updated_at"] = utcnow()
    await teams.update_one({"_id": oid}, {"$set": update})
    logger.info("Updated consultant team %s", team_id)
    return to_team(await teams.find_one({"_id": oid}))


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: str) -> Response:
    """Remove a team, unless appointments are still booked with it.

    Cases no longer carry a team of their own, so an appointment is the only
    thing that can still point here.
    """
    oid = team_oid(team_id)
    await load_team(team_id)

    in_appointments = await get_collection(
        appointment_model.COLLECTION
    ).count_documents({"consultant": oid})
    if in_appointments:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"Team is still booked for {in_appointments} appointment(s); "
                "reassign them first."
            ),
        )

    await get_collection(team_model.COLLECTION).delete_one({"_id": oid})
    logger.info("Deleted consultant team %s", team_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
