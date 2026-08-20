"""Investigation reports attached to a case.

An uploaded report goes through the same two steps the recorded consultation
does, and in the same order: the PDF is read to text and stored first, so a
failure in fact extraction cannot lose the report, and only then is Corti's
FactsR endpoint called and its answer kept as the summary.

The extractor is the same agent the referral intake uses — a PDF is a PDF,
whether it arrived as a referral letter or as a radiology report.

    GET  /cases/{case_id}/investigations
    POST /cases/{case_id}/investigations   (multipart: name, file)

    curl -X POST 'http://127.0.0.1:8000/cases/6a855a.../investigations' \
      -F 'name=MRI right knee' \
      -F 'file=@/path/to/report.pdf;type=application/pdf'

    201 {
      "investigation_id": "6a8701...",
      "case_id": "6a855a...",
      "name": "MRI right knee",
      "transcription": "MRI RIGHT KNEE\\nClinical: ...",
      "summary": "Findings:\\n- Full-thickness cartilage loss ...",
      "reported_at": "2026-08-20T13:20:11.204Z",
      "attachments": ["storage/uploads/investigations/8f2c....pdf"],
      "fact_count": 6,
      "errors": []
    }

    The report is stored even when extraction fails; the response then carries
    `summary: ""` and the reason in `errors`.

    400 invalid case id or not a PDF · 404 unknown case
    413 over the size limit · 415 wrong content type · 422 no readable text
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.agents.skilled_agents import ReferralDocumentReader
from app.core.config import settings
from app.db.mongodb import get_collection
from app.models import case as case_model
from app.models import investigation as investigation_model
from app.models.common import utcnow
from app.models.investigation import InvestigationDetails
from app.services.corti_textgen import extract_facts, format_facts

logger = logging.getLogger(__name__)

router = APIRouter(tags=["investigations"], prefix="/cases/{case_id}/investigations")

CHUNK_SIZE = 1024 * 1024  # 1 MiB
PDF_MAGIC = b"%PDF-"


class InvestigationRead(BaseModel):
    investigation_id: str
    case_id: str
    name: str = ""
    # Text the PDF reader pulled out of the report.
    transcription: str = ""
    # The facts Corti found, rendered as a brief.
    summary: str = ""
    reported_at: datetime | None = None
    attachments: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class InvestigationListResponse(BaseModel):
    total: int
    investigations: list[InvestigationRead] = Field(default_factory=list)


class InvestigationCreateResponse(InvestigationRead):
    """The stored report, plus what extraction managed to do with it."""

    fact_count: int = 0
    # Non-fatal problems: the report is stored regardless.
    errors: list[str] = Field(default_factory=list)


def case_oid(case_id: str) -> ObjectId:
    if not ObjectId.is_valid(case_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{case_id!r} is not a valid case id."
        )
    return ObjectId(case_id)


async def require_case(case_id: str) -> ObjectId:
    oid = case_oid(case_id)
    if not await get_collection(case_model.COLLECTION).find_one({"_id": oid}, {"_id": 1}):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No case with id {case_id}."
        )
    return oid


def to_read(doc: dict) -> InvestigationRead:
    return InvestigationRead(
        investigation_id=str(doc.get("_id", "")),
        case_id=str(doc.get("case", "")),
        name=doc.get("name") or "",
        transcription=doc.get("transcription") or "",
        summary=doc.get("summary") or "",
        reported_at=doc.get("reported_at"),
        attachments=doc.get("attachments") or [],
        created_at=doc.get("created_at"),
    )


async def store_upload(file: UploadFile, investigation_id: str) -> tuple[Path, int]:
    """Stream the upload to disk, returning its path and size."""
    upload_dir = Path(settings.upload_dir) / "investigations"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{investigation_id}.pdf"

    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"PDF exceeds the {settings.max_upload_mb} MB limit.",
                    )
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return dest, size


@router.get("", response_model=InvestigationListResponse)
async def list_investigations(case_id: str) -> InvestigationListResponse:
    """Every investigation on the case, most recently reported first."""
    oid = await require_case(case_id)
    docs = (
        await get_collection(investigation_model.COLLECTION)
        .find({"case": oid})
        .sort("created_at", -1)
        .to_list(length=200)
    )
    return InvestigationListResponse(
        total=len(docs), investigations=[to_read(d) for d in docs]
    )


@router.post("", response_model=InvestigationCreateResponse, status_code=status.HTTP_201_CREATED)
async def upload_investigation(
    case_id: str,
    name: str = Form(...),
    file: UploadFile = File(...),
) -> InvestigationCreateResponse:
    """Upload a report: read the PDF, then summarise it from its facts."""
    oid = await require_case(case_id)

    if file.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Expected a PDF, got content type '{file.content_type}'.",
        )
    header = await file.read(len(PDF_MAGIC))
    if header != PDF_MAGIC:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="File is not a valid PDF."
        )
    await file.seek(0)

    investigation_id = uuid.uuid4().hex
    dest, size = await store_upload(file, investigation_id)

    # 1. The PDF, through the same reader the referral intake uses.
    try:
        read = await ReferralDocumentReader().run(
            {"referral_id": investigation_id, "document_path": str(dest)}
        )
    except Exception as exc:  # noqa: BLE001 — the upload is already on disk
        logger.exception("Could not read investigation PDF for case %s", case_id)
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not read the PDF: {exc}",
        ) from exc

    transcription = (read.get("referral_transcription") or "").strip()
    if not transcription:
        # A scanned report carries no text, so there is nothing to summarise
        # and nothing worth storing.
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The PDF has no extractable text (is it a scan?).",
        )

    # 2. Store it before extracting: losing the report would be worse than
    #    losing its summary, and extraction is the part that can fail.
    record = InvestigationDetails(
        case=oid,
        name=name.strip() or file.filename or "Investigation",
        transcription=transcription,
        summary="",
        reported_at=utcnow(),
        attachments=[str(dest)],
    ).to_mongo()

    investigations = get_collection(investigation_model.COLLECTION)
    result = await investigations.insert_one(record)

    # 3. Then the facts, stored as the report's summary.
    errors: list[str] = []
    facts: list[dict[str, Any]] = []
    summary = ""
    try:
        extracted = await extract_facts(context_text=transcription, access_token=None)
    except Exception as exc:  # noqa: BLE001 — the report is already safe
        logger.exception("Fact extraction failed for investigation %s", result.inserted_id)
        errors.append(f"Fact extraction failed: {exc}")
    else:
        facts = extracted.facts
        summary = format_facts(facts)
        if summary:
            await investigations.update_one(
                {"_id": result.inserted_id},
                {"$set": {"summary": summary, "updated_at": utcnow()}},
            )
        else:
            errors.append("Corti returned no facts for this report.")

    logger.info(
        "Case %s: stored investigation %s (%d bytes, %d chars, %d fact(s))",
        case_id,
        result.inserted_id,
        size,
        len(transcription),
        len(facts),
    )

    stored = await investigations.find_one({"_id": result.inserted_id})
    return InvestigationCreateResponse(
        **to_read(stored).model_dump(), fact_count=len(facts), errors=errors
    )
