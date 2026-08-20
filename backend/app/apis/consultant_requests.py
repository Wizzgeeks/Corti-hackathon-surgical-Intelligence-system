"""Consultant requests on a case — the question, and the reply when it comes.

Each request is one entry in the case's `consultant_requests` array. The
request text and the response are saved independently (the UI has a button
for each), so every route here writes one side of one entry and leaves the
rest of the case alone.

Both timestamps belong to the server: `request_time` is stamped whenever the
request text is saved, `responded_time` whenever a response is saved, and a
response cleared to blank clears its time again. Neither is read from the
request body — a browser clock is not the record of when the exchange
happened.

    GET    /cases/{case_id}/consultant_requests
    POST   /cases/{case_id}/consultant_requests
    PATCH  /cases/{case_id}/consultant_requests/{request_id}
    DELETE /cases/{case_id}/consultant_requests/{request_id}

    curl -X POST \
      'http://127.0.0.1:8000/cases/6530.../consultant_requests' \
      -H 'Content-Type: application/json' \
      -d '{"consultant_requests": "Is a weight-bearing X-ray needed?"}'
"""

import logging
from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.db.mongodb import get_collection
from app.models import case as case_model
from app.models.case import ConsultantRequest
from app.models.common import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consultant_requests"], prefix="/cases/{case_id}")


class ConsultantRequestCreate(BaseModel):
    """A new request. A response may be supplied if it is already known."""

    consultant_requests: str = ""
    response: str | None = None


class ConsultantRequestPatch(BaseModel):
    """Either side of one request. Only what is sent is written."""

    consultant_requests: str | None = None
    response: str | None = None


class ConsultantRequestRead(BaseModel):
    request_id: str
    consultant_requests: str = ""
    request_time: datetime | None = None
    response: str | None = None
    responded_time: datetime | None = None


class ConsultantRequestListResponse(BaseModel):
    total: int
    consultant_requests: list[ConsultantRequestRead] = Field(default_factory=list)


def case_oid(case_id: str) -> ObjectId:
    if not ObjectId.is_valid(case_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{case_id!r} is not a valid case id."
        )
    return ObjectId(case_id)


async def load_case(case_id: str) -> dict:
    doc = await get_collection(case_model.COLLECTION).find_one({"_id": case_oid(case_id)})
    if not doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case with id {case_id}."
        )
    return doc


def requests_of(doc: dict) -> list[dict]:
    return list(doc.get("consultant_requests") or [])


def find_request(items: list[dict], request_id: str) -> int:
    """Position of one request in the case's list, or 404."""
    for index, item in enumerate(items):
        if str(item.get("request_id")) == request_id:
            return index
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail=f"No consultant request with id {request_id} on this case.",
    )


async def write_requests(oid: ObjectId, items: list[dict]) -> None:
    """Persist the whole array, touching the case's own `updated_at`."""
    await get_collection(case_model.COLLECTION).update_one(
        {"_id": oid},
        {"$set": {"consultant_requests": items, "updated_at": utcnow()}},
    )


def to_read(item: dict) -> ConsultantRequestRead:
    return ConsultantRequestRead(
        request_id=str(item.get("request_id", "")),
        consultant_requests=item.get("consultant_requests") or "",
        request_time=item.get("request_time"),
        response=item.get("response"),
        responded_time=item.get("responded_time"),
    )


@router.get("/consultant_requests", response_model=ConsultantRequestListResponse)
async def list_consultant_requests(case_id: str) -> ConsultantRequestListResponse:
    """Every request on the case, oldest first."""
    items = requests_of(await load_case(case_id))
    return ConsultantRequestListResponse(
        total=len(items), consultant_requests=[to_read(i) for i in items]
    )


@router.post(
    "/consultant_requests",
    response_model=ConsultantRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_consultant_request(
    case_id: str, payload: ConsultantRequestCreate
) -> ConsultantRequestRead:
    """Raise a request against the case, stamped with the time it arrived."""
    oid = case_oid(case_id)
    doc = await load_case(case_id)

    text = (payload.consultant_requests or "").strip()
    response = (payload.response or "").strip()
    if not text and not response:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="A consultant request needs a request or a response.",
        )

    entry = ConsultantRequest(
        consultant_requests=text,
        request_time=utcnow(),
        response=response or None,
        responded_time=utcnow() if response else None,
    )

    items = [*requests_of(doc), entry.model_dump()]
    await write_requests(oid, items)
    logger.info("Case %s: added consultant request %s", case_id, entry.request_id)
    return to_read(items[-1])


@router.patch(
    "/consultant_requests/{request_id}", response_model=ConsultantRequestRead
)
async def update_consultant_request(
    case_id: str, request_id: str, payload: ConsultantRequestPatch
) -> ConsultantRequestRead:
    """Save one side of a request.

    Sending `consultant_requests` re-stamps `request_time`; sending a
    `response` stamps `responded_time`, or clears it when the response is
    blanked. Omitting a field leaves it, and its time, untouched — which is
    what lets the two Save buttons act independently.
    """
    oid = case_oid(case_id)
    doc = await load_case(case_id)
    items = requests_of(doc)
    index = find_request(items, request_id)

    sent: dict[str, Any] = payload.model_dump(exclude_unset=True)
    if not sent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update — send a request or a response.",
        )

    entry = dict(items[index])

    if "consultant_requests" in sent:
        entry["consultant_requests"] = (sent["consultant_requests"] or "").strip()
        entry["request_time"] = utcnow()

    if "response" in sent:
        response = (sent["response"] or "").strip()
        entry["response"] = response or None
        entry["responded_time"] = utcnow() if response else None

    items[index] = entry
    await write_requests(oid, items)
    logger.info("Case %s: updated consultant request %s", case_id, request_id)
    return to_read(entry)


@router.delete(
    "/consultant_requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_consultant_request(case_id: str, request_id: str) -> Response:
    """Remove one request from the case."""
    oid = case_oid(case_id)
    items = requests_of(await load_case(case_id))
    index = find_request(items, request_id)

    del items[index]
    await write_requests(oid, items)
    logger.info("Case %s: deleted consultant request %s", case_id, request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
