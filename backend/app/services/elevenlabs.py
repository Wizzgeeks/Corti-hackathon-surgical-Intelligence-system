"""Text to speech, through ElevenLabs.

The API key lives here and never leaves the server: the browser asks this
backend for audio, not ElevenLabs. That is the whole reason this is a proxy
rather than a fetch from the page.

The `with-timestamps` endpoint is used rather than plain synthesis because it
returns *when* each character is spoken, which is what lets the page follow
the briefing sentence by sentence as it plays.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 90.0
# 128 kbps mp3: small enough to start quickly, good enough for speech.
OUTPUT_FORMAT = "mp3_44100_128"


class SpeechError(Exception):
    """ElevenLabs would not synthesise this."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


async def speak(text: str, voice_id: str | None = None) -> dict[str, Any]:
    """Synthesise `text`, returning the audio and its character timings.

        {"audio_base64": "...", "alignment": {"characters": [...],
         "character_start_times_seconds": [...], ...}}

    Raised errors carry ElevenLabs' status so the endpoint can tell a missing
    key (401) from an exhausted quota (402) rather than reporting both as a
    generic failure.
    """
    if not settings.elevenlabs_api_key:
        raise SpeechError("No ElevenLabs API key is configured.", status_code=401)

    voice = voice_id or settings.elevenlabs_voice_id
    url = f"{settings.elevenlabs_base_url}/text-to-speech/{voice}/with-timestamps"
    payload = {
        "text": text,
        "model_id": settings.elevenlabs_model_id,
        "output_format": OUTPUT_FORMAT,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        response = await http.post(
            url,
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.is_error:
        detail = ""
        try:
            body = response.json().get("detail") or {}
            detail = body.get("message") if isinstance(body, dict) else str(body)
        except Exception:  # noqa: BLE001 — the message is a nicety, not the point
            detail = response.text[:200]
        logger.warning(
            "ElevenLabs %s for voice %s: %s", response.status_code, voice, detail
        )
        raise SpeechError(
            detail or f"ElevenLabs returned {response.status_code}.",
            status_code=response.status_code,
        )

    body = response.json()
    logger.info(
        "Spoke %d characters with %s.", len(text), settings.elevenlabs_model_id
    )
    return {
        "audio_base64": body.get("audio_base64") or "",
        "alignment": body.get("alignment") or {},
    }
