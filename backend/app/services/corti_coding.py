"""Corti medical coding — `POST /v2/tools/coding/`.

Stateless: clinical text goes in, coded diagnoses come back. Nothing is
stored against an interaction, which suits us — we already hold the case and
only want the codes for it.

Corti has moved the shape of this response before, so `normalise_codes()`
reads defensively and never raises on an unexpected payload: an unreadable
entry is skipped rather than failing the whole call.
"""

import logging
from typing import Any

from app.services import corti_endpoints as urls
from app.services.corti_client import CortiClient

logger = logging.getLogger(__name__)

# ICD-10-CM inpatient, matching what the clinic codes against today.
DEFAULT_SYSTEMS = ("icd10cm-inpatient",)

# Corti reads the whole context in one call; a very long case would be
# rejected, so the text is capped rather than sent whole.
MAX_CONTEXT_CHARS = 20000


def build_payload(text: str, systems: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """The request body for the coding tool."""
    return {
        "system": list(systems),
        "context": [{"type": "text", "text": text[:MAX_CONTEXT_CHARS]}],
    }


def _first(entry: dict[str, Any], *names: str) -> str:
    """First non-empty value among `names`, as a stripped string."""
    for name in names:
        value = entry.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalise_codes(response: Any) -> list[dict[str, Any]]:
    """Corti's reply -> a flat list of codes the UI can render.

    Accepts either a bare list or an object wrapping one under `codes`,
    `results` or `data`, since which of those Corti sends has varied.
    """
    entries: Any = response
    if isinstance(response, dict):
        for key in ("codes", "results", "data", "items"):
            if isinstance(response.get(key), list):
                entries = response[key]
                break
        else:
            entries = []

    if not isinstance(entries, list):
        return []

    codes: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = _first(entry, "code", "id", "value")
        label = _first(entry, "description", "label", "display", "text", "name")
        if not code and not label:
            continue
        confidence = entry.get("confidence", entry.get("score"))
        codes.append(
            {
                "code": code,
                "description": label,
                "system": _first(entry, "system", "codeSystem", "codingSystem"),
                "confidence": (
                    float(confidence)
                    if isinstance(confidence, (int, float))
                    else None
                ),
                "evidence": _first(entry, "evidence", "rationale", "context"),
            }
        )
    return codes


async def fetch_codes(
    text: str,
    systems: tuple[str, ...] | list[str] = DEFAULT_SYSTEMS,
    *,
    client: CortiClient | None = None,
) -> tuple[list[dict[str, Any]], Any]:
    """Code `text`. Returns the normalised codes and Corti's raw reply."""
    corti = client or CortiClient()
    payload = build_payload(text, systems)
    response = await corti.post(urls.api_url(urls.Paths.TOOLS_CODING), json=payload)
    codes = normalise_codes(response)
    logger.info("corti coding: %d char(s) in -> %d code(s)", len(text), len(codes))
    return codes, response
