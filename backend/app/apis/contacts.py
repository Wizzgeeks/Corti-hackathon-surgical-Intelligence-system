"""CRUD for contacts.

A contact is a person a referral comes from or is addressed to — the same
(name, role, organization) shape a case already records under `referred_by`,
kept as a reusable directory so referrers do not have to be retyped.

Nothing references a contact by id, so deleting one is unconditional.

    POST   /contacts
    GET    /contacts?limit=50&skip=0&q=smith
    GET    /contacts/{contact_id}
    PATCH  /contacts/{contact_id}
    DELETE /contacts/{contact_id}

    curl -X POST 'http://127.0.0.1:8000/contacts' \
      -H 'Content-Type: application/json' \
      -d '{"name": "Dr Aisha Khan", "role": "GP",
           "organization": "Riverside Surgery"}'
"""

import logging
from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models import contact as contact_model
from app.models.common import utcnow
from app.models.contact import Contact

logger = logging.getLogger(__name__)

router = APIRouter(tags=["contacts"], prefix="/contacts")


class ContactCreate(BaseModel):
    name: str = Field(min_length=1)
    role: str = ""
    organization: str = ""


class ContactPatch(BaseModel):
    """Every field optional — only what is sent gets written."""

    name: str | None = Field(default=None, min_length=1)
    role: str | None = None
    organization: str | None = None


class ContactRead(BaseModel):
    contact_id: str
    name: str = ""
    role: str = ""
    organization: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContactListResponse(BaseModel):
    total: int
    limit: int
    skip: int
    contacts: list[ContactRead] = Field(default_factory=list)


def to_contact(doc: dict) -> ContactRead:
    return ContactRead(
        contact_id=str(doc.get("_id", "")),
        name=doc.get("name", ""),
        role=doc.get("role", ""),
        organization=doc.get("organization", ""),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


def contact_oid(contact_id: str) -> ObjectId:
    if not ObjectId.is_valid(contact_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{contact_id!r} is not a valid contact id.",
        )
    return ObjectId(contact_id)


async def load_contact(contact_id: str) -> dict:
    doc = await get_collection(contact_model.COLLECTION).find_one(
        {"_id": contact_oid(contact_id)}
    )
    if not doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No contact with id {contact_id}."
        )
    return doc


async def reject_duplicate(name: str, organization: str, *, exclude: ObjectId | None = None) -> None:
    """The same person at the same organization is one contact, not two.

    Backed by a unique (name, organization) index, so this turns what would
    otherwise be a 500 from Mongo into a 409.
    """
    query: dict[str, Any] = {"name": name, "organization": organization}
    if exclude is not None:
        query["_id"] = {"$ne": exclude}
    if await get_collection(contact_model.COLLECTION).find_one(query, {"_id": 1}):
        where = f" at {organization!r}" if organization else ""
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A contact named {name!r}{where} already exists.",
        )


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact(payload: ContactCreate) -> ContactRead:
    """Add a contact."""
    contact = Contact(
        name=payload.name.strip(),
        role=payload.role.strip(),
        organization=payload.organization.strip(),
    )
    contacts = get_collection(contact_model.COLLECTION)
    await reject_duplicate(contact.name, contact.organization)

    result = await contacts.insert_one(contact.to_mongo())
    logger.info("Created contact %s", result.inserted_id)
    return to_contact(await contacts.find_one({"_id": result.inserted_id}))


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    q: str | None = Query(None, description="Match name, role or organization."),
) -> ContactListResponse:
    """List contacts, alphabetically by name."""
    query: dict[str, Any] = {}
    if q:
        pattern = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"name": pattern},
            {"role": pattern},
            {"organization": pattern},
        ]

    contacts = get_collection(contact_model.COLLECTION)
    total = await contacts.count_documents(query)
    docs = (
        await contacts.find(query)
        .sort("name", 1)
        .skip(skip)
        .limit(limit)
        .to_list(length=limit)
    )
    return ContactListResponse(
        total=total, limit=limit, skip=skip, contacts=[to_contact(d) for d in docs]
    )


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(contact_id: str) -> ContactRead:
    return to_contact(await load_contact(contact_id))


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact(contact_id: str, payload: ContactPatch) -> ContactRead:
    """Update any subset of a contact."""
    oid = contact_oid(contact_id)
    current = await load_contact(contact_id)

    update = payload.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update — send at least one field.",
        )

    for field in ("name", "role", "organization"):
        if isinstance(update.get(field), str):
            update[field] = update[field].strip()

    # The pair is uniquely indexed, so check it whenever either half moves.
    if "name" in update or "organization" in update:
        await reject_duplicate(
            update.get("name", current.get("name", "")),
            update.get("organization", current.get("organization", "")),
            exclude=oid,
        )

    contacts = get_collection(contact_model.COLLECTION)
    update["updated_at"] = utcnow()
    await contacts.update_one({"_id": oid}, {"$set": update})
    logger.info("Updated contact %s", contact_id)
    return to_contact(await contacts.find_one({"_id": oid}))


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(contact_id: str) -> Response:
    """Remove a contact."""
    oid = contact_oid(contact_id)
    await load_contact(contact_id)
    await get_collection(contact_model.COLLECTION).delete_one({"_id": oid})
    logger.info("Deleted contact %s", contact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
