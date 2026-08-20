"""Referral upload and triage.

    POST /upload_referrals

    curl -X POST 'http://127.0.0.1:8000/upload_referrals' \
      -F 'file=@/path/to/referral.pdf;type=application/pdf'

    201 {
      "referral_id": "c63787d6519c497fb9f8dfa76533dab1",
      "filename": "referral.pdf",
      "size_bytes": 1445,
      "stored_path": "storage/uploads/referrals/c63787d6....pdf",
      "triage": {
        "patient_name": "Melissa Pearce",
        "patient_age": "47",
        "patient_gender": "Female",
        "patient_contact": "",
        "referred_by": {
          "name": "",
          "current_role": "GP",
          "organization": "Bryndwr Medical Rooms"
        },
        "allergies": "NA",
        "referred_to_consultant": "Mr Ram Chandru",
        "case_summary": "",
        "flags": "",
        "recommendation": ""
      },
      "pdf_content": "Merivale Hand Clinic Ltd\\n208 Papanui Road\\n...",
      "corti_logs": {
        "agent1": {
          "agent_name": "case_data_extractor",
          "corti_request": {"outputLanguage": "en", "templateRef": {"...": "..."}},
          "corti_response": {"document": {"...": "..."}}
        }
      },
      "warnings": []
    }

    415 wrong content type · 400 not a PDF · 413 over the size limit
    422 stored but not triageable · 500 unexpected triage failure
"""

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.agents.runner import run_agents
from app.services.corti_textgen import extract_facts, format_facts

logger = logging.getLogger(__name__)

router = APIRouter(tags=["referrals"])

# Upload runs these two, in order — the same agents every other flow uses.
INTAKE_AGENTS = ["referral_document_reader", "case_data_extractor"]

# What the extractor fills in, and what only later agents produce.
EXTRACTED_FIELDS: tuple[str, ...] = (
    "patient_name",
    "patient_age",
    "patient_gender",
    "patient_contact",
    "allergies",
    "referred_to_consultant",
)
DEFERRED_FIELDS: tuple[str, ...] = (
    "case_summary",
    "flags",
    "recommendation",
)
REFERRER_FIELDS: tuple[str, ...] = ("name", "current_role", "organization")


def empty_output() -> dict[str, Any]:
    """The full response shape with nothing filled in."""
    return {
        **{field: "" for field in (*EXTRACTED_FIELDS, *DEFERRED_FIELDS)},
        "clinical_background": "",
        "referred_by": {field: "" for field in REFERRER_FIELDS},
    }

CHUNK_SIZE = 1024 * 1024  # 1 MiB
PDF_MAGIC = b"%PDF-"


class Referrer(BaseModel):
    """Who sent the referral — a person, their role, and their organisation."""

    name: str = ""
    current_role: str = ""
    organization: str = ""


class TriageResult(BaseModel):
    """The intake pipeline's output, as returned to the caller.

    Every field is always present; anything the pipeline could not determine
    comes back blank rather than being omitted. Upload runs the reader and the
    extractor only, so `case_summary`, `flags` and `recommendation` are always
    blank here — they are produced later, not at upload time. The keys are kept
    so the contract does not change.

    `clinical_background` is the exception: it is filled at upload, from the
    facts Corti finds in the letter itself, so the reviewer sees the clinical
    picture before anything has been interpreted.
    """

    patient_name: str = ""
    patient_age: str = ""
    patient_gender: str = ""
    patient_contact: str = ""
    referred_by: Referrer = Field(default_factory=Referrer)
    allergies: str = ""
    referred_to_consultant: str = ""
    case_summary: str = ""
    flags: str = ""
    recommendation: str = ""
    # The letter's clinical facts, as a grouped brief. Comes from Corti's
    # FactsR endpoint rather than from an agent — see below.
    clinical_background: str = ""


class CortiCallLog(BaseModel):
    """One agent's round trip to Corti."""

    agent_name: str = ""
    corti_request: Any = None
    corti_response: Any = None


class UploadReferralResponse(BaseModel):
    """Upload receipt plus the fields intake extracted for it."""

    referral_id: str
    filename: str
    size_bytes: int
    stored_path: str
    triage: TriageResult
    # Text the document reader extracted from the PDF.
    pdf_content: str = ""
    # Every Corti exchange the run made, keyed `agent1`, `agent2`, … in order.
    corti_logs: dict[str, CortiCallLog] = Field(default_factory=dict)
    # Non-fatal problems from the run — the triage above may be partial.
    warnings: list[str] = Field(default_factory=list)


async def _store_upload(file: UploadFile, referral_id: str) -> tuple[Path, int]:
    """Stream the upload to disk, returning its path and size."""
    upload_dir = Path(settings.upload_dir) / "referrals"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{referral_id}.pdf"

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


@router.post(
    "/upload_referrals",
    response_model=UploadReferralResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_referral(file: UploadFile = File(...)) -> UploadReferralResponse:
    """Accept a referral PDF, extract what is in it, and return the result.

    The uploaded file is stored, then read and extracted by the two intake
    agents. Nothing is interpreted beyond the letter's own contents — the
    case is created from these fields and reasoned about afterwards.
    """
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

    referral_id = uuid.uuid4().hex
    dest, size = await _store_upload(file, referral_id)

    # Two agents, in order: read the PDF, then extract its fields.
    try:
        result = await run_agents(
            INTAKE_AGENTS,
            {"referral_id": referral_id, "document_path": str(dest)},
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as a 500 below
        logger.exception("Triage failed for referral %s", referral_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Triage failed: {exc}",
        ) from exc

    state = result["state"]
    errors = result["errors"]

    if state.get("is_scanned"):
        errors.append(
            "referral_document_reader: the PDF has no extractable text (scanned?)."
        )

    # Keep only the fields this endpoint promises; anything the extractor did
    # not find stays blank rather than missing.
    output = empty_output()
    for key in (*EXTRACTED_FIELDS, "referred_by"):
        if state.get(key):
            output[key] = state[key]

    # The letter's own clinical facts, straight from FactsR. Failure here is
    # not fatal: the extracted fields are still worth returning, and the
    # background can be typed in.
    transcription = state.get("referral_transcription") or ""
    if transcription.strip():
        try:
            facts = await extract_facts(context_text=transcription, access_token=None)
        except Exception as exc:  # noqa: BLE001 — reported, not raised
            logger.exception("FactsR failed for referral %s", referral_id)
            errors.append(f"clinical_background: {exc}")
        else:
            output["clinical_background"] = format_facts(facts.facts)
            call = facts.as_call("clinical_background")
            result["corti_logs"][f"agent{len(result['corti_logs']) + 1}"] = call

    # No payload at all means the pipeline stopped before producing anything —
    # an unreadable document, or Corti being unreachable. A payload that is
    # merely blank is fine: the letter is stored and the fields can be typed in.
    if not output:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Referral could not be triaged.",
                "referral_id": referral_id,
                "errors": errors,
            },
        )

    return UploadReferralResponse(
        referral_id=referral_id,
        filename=file.filename or f"{referral_id}.pdf",
        size_bytes=size,
        stored_path=str(dest),
        triage=TriageResult(**output),
        pdf_content=state.get("referral_transcription") or "",
        corti_logs=result["corti_logs"],
        warnings=errors,
    )
