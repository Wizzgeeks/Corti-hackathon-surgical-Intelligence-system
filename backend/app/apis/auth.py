"""Hands the browser what it needs to open a Corti socket.

Corti's realtime sockets authenticate through query parameters, so the client
needs a bearer token to open one. It gets that here: the client id and secret
stay on the server, and what leaves is a token that expires in minutes.

There are two sockets, and they are not interchangeable:

* `/scoped_auth` -> the `/transcribe` socket. Dictation: one voice, no
  speaker separation. Used by the dictated text fields.
* `/consultation_auth` -> an interaction's `/streams` socket. A conversation
  between two people, diarized, so each transcript says who spoke. This is
  the only one that can tell the doctor from the patient, which is why
  recording a consultation goes through an interaction rather than dictation.

    GET /scoped_auth

    200 {
      "access_token": "eyJhbGciOi...",
      "token_type": "Bearer",
      "expires_in": 300,
      "tenant_name": "base",
      "transcribe_url": "wss://api.eu.corti.app/audio-bridge/v2/transcribe?..."
    }

    POST /consultation_auth

    201 {
      "access_token": "eyJhbGciOi...",
      "tenant_name": "base",
      "interaction_id": "40d0e90a-0e8f-46d3-818e-359292bf765c",
      "stream_url": "wss://api.eu.corti.app/audio-bridge/v2/interactions/40d0.../streams?..."
    }

    502 when Corti will not issue a token.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.services import corti_endpoints as urls
from app.services.corti_client import CortiClient, CortiError
from app.services.corti_endpoints import transcribe_ws_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    # Corti tokens are short-lived; the client should fetch a fresh one per
    # dictation rather than holding on to this.
    expires_in: int = 300
    tenant_name: str
    # Ready to open, so the browser never has to know Corti's hosts.
    transcribe_url: str


@router.get("/scoped_auth", response_model=AuthResponse)
async def get_dictation_token() -> AuthResponse:
    """Mint a Corti access token for the browser's dictation session."""
    try:
        token = await CortiClient().login("openid")
    except CortiError as exc:
        logger.warning("Could not issue a dictation token: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Corti login failed: {exc}",
        ) from exc

    return AuthResponse(
        access_token=token,
        tenant_name=settings.corti_tenant_name,
        transcribe_url=transcribe_ws_url(token),
    )


class ConsultationAuthRequest(BaseModel):
    """Optional labelling for the interaction Corti records this against."""

    title: str | None = None
    # The case this consultation belongs to, so the interaction can be traced
    # back to it in Corti.
    case_id: str | None = None


class ConsultationAuthResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 300
    tenant_name: str
    interaction_id: str
    # Ready to open, token included.
    stream_url: str


@router.post(
    "/consultation_auth",
    response_model=ConsultationAuthResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_consultation_stream(
    payload: ConsultationAuthRequest | None = None,
) -> ConsultationAuthResponse:
    """Open an interaction and hand back its diarized stream socket.

    A consultation is two people on one microphone, and only the interaction
    stream separates them. The interaction has to exist before the socket
    does, so it is created here rather than in the browser — that also keeps
    the token server-side until the last moment.
    """
    payload = payload or ConsultationAuthRequest()
    client = CortiClient()

    # Corti stores `identifier` as ExternalId and rejects a repeat with 409,
    # so it must be unique per interaction — not the case id, which would
    # fail the second time a case is recorded. Prefixing with the case keeps
    # the interaction traceable while the suffix keeps it unique.
    unique = uuid.uuid4().hex[:12]
    identifier = f"case-{payload.case_id}-{unique}" if payload.case_id else f"consultation-{unique}"
    encounter: dict[str, Any] = {
        "identifier": identifier,
        "status": "in-progress",
        "type": "consultation",
        "period": {"startedAt": datetime.now(timezone.utc).isoformat()},
    }
    if payload.title:
        encounter["title"] = payload.title

    try:
        token = await client.login("openid")
        interaction = await client.post(
            urls.api_url(urls.Paths.INTERACTIONS),
            json={"encounter": encounter},
            access_token=token,
        )
    except CortiError as exc:
        logger.warning("Could not start a consultation stream: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Corti would not start the consultation: {exc}",
        ) from exc

    interaction_id = (interaction or {}).get("interactionId") or ""
    websocket_url = (interaction or {}).get("websocketUrl") or ""
    if not websocket_url:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Corti created the interaction but returned no socket URL.",
        )

    logger.info("Started consultation interaction %s", interaction_id)
    return ConsultationAuthResponse(
        access_token=token,
        tenant_name=settings.corti_tenant_name,
        interaction_id=interaction_id,
        stream_url=urls.with_ws_token(websocket_url, token),
    )
