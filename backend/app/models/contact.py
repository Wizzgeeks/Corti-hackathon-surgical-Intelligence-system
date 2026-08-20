from app.models.common import MongoModel

COLLECTION = "contacts"


class Contact(MongoModel):
    """A person a referral can come from or be addressed to.

    Mirrors the shape `Case.referred_by` already carries (name, role,
    organization), so a referrer picked up during triage can be kept here as
    a reusable record. Any prefix ("Dr", "Prof") is part of `name`.
    """

    name: str
    role: str = ""
    organization: str = ""
