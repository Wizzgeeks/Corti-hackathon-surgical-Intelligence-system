import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel
from pymongo.errors import OperationFailure

logger = logging.getLogger(__name__)

# One consultation (or surgery) per appointment — but only among records that
# actually have one. Without the partial filter, every record booked against
# no appointment stores `appointment: null`, and the second one collides with
# the first: unique treats all those nulls as the same key.
ONE_PER_APPOINTMENT = IndexModel(
    [("appointment", ASCENDING)],
    unique=True,
    partialFilterExpression={"appointment": {"$type": "objectId"}},
)

from app.models import (
    appointment,
    case,
    consultant_team,
    consultation,
    investigation,
    contact,
    patient,
    surgery,
)

INDEXES: dict[str, list[IndexModel]] = {
    consultant_team.COLLECTION: [
        IndexModel([("name", ASCENDING)], unique=True),
        IndexModel([("speciality", ASCENDING)]),
    ],
    contact.COLLECTION: [
        IndexModel(
            [("name", ASCENDING), ("organization", ASCENDING)], unique=True
        ),
        IndexModel([("organization", ASCENDING)]),
    ],
    patient.COLLECTION: [
        IndexModel([("name", ASCENDING)]),
    ],
    case.COLLECTION: [
        IndexModel([("patient", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("is_urgent", ASCENDING), ("created_at", ASCENDING)]),
    ],
    appointment.COLLECTION: [
        IndexModel([("patient", ASCENDING)]),
        IndexModel([("consultant", ASCENDING), ("start_time", ASCENDING)]),
        IndexModel([("case", ASCENDING)]),
    ],
    consultation.COLLECTION: [
        IndexModel([("case", ASCENDING)]),
        ONE_PER_APPOINTMENT,
    ],
    investigation.COLLECTION: [
        IndexModel([("case", ASCENDING)]),
        IndexModel([("status", ASCENDING), ("requested_at", ASCENDING)]),
    ],
    surgery.COLLECTION: [
        IndexModel([("case", ASCENDING)]),
        ONE_PER_APPOINTMENT,
    ],
}


# Mongo refuses to redefine an existing index rather than migrating it, so an
# index whose definition has changed is dropped and rebuilt. Only ever on
# startup, and only for the index that actually differs. It reports the clash
# two ways depending on what changed: the options (85) or the key spec, which
# includes a partial filter (86).
INDEX_CONFLICT_CODES = (85, 86)


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    for collection, models in INDEXES.items():
        try:
            await db[collection].create_indexes(models)
        except OperationFailure as exc:
            if exc.code not in INDEX_CONFLICT_CODES:
                raise
            # The message names the index that clashes, e.g. "appointment_1".
            existing = {
                name
                for name in (await db[collection].index_information())
                if name != "_id_" and name in str(exc)
            }
            for name in existing:
                logger.info("Rebuilding %s.%s with new options", collection, name)
                await db[collection].drop_index(name)
            await db[collection].create_indexes(models)
