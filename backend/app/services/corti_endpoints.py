"""Every Corti URL lives here — nothing else in the codebase builds one.

Corti has three separate hosts, so they are kept apart deliberately:

* auth  -> https://auth.{env}.corti.app   (OAuth2 token issuing)
* api   -> https://api.{env}.corti.app    (clinical + agentic REST, /v2)
* models-> https://ai.eu.corti.app        (OpenAI-compatible LLM, EU only)
"""

from app.core.config import settings

API_VERSION = "v2"


# --- Hosts -----------------------------------------------------------------


def auth_base_url() -> str:
    """e.g. https://auth.eu.corti.app"""
    return settings.corti_auth_base_url or f"https://auth.{settings.corti_environment}.corti.app"


def api_base_url() -> str:
    """e.g. https://api.eu.corti.app"""
    return settings.corti_api_base_url or f"https://api.{settings.corti_environment}.corti.app"


def models_base_url() -> str:
    """OpenAI-compatible base, EU only."""
    return settings.corti_models_base_url


# --- Auth ------------------------------------------------------------------


def token_url() -> str:
    """OAuth2 client-credentials token endpoint for the configured realm."""
    return (
        f"{auth_base_url()}/realms/{settings.corti_tenant_name}"
        "/protocol/openid-connect/token"
    )


def transcribe_ws_url(token: str) -> str:
    """Realtime dictation socket.

    Corti authenticates the socket through query parameters — there are no
    headers on a browser-style WebSocket handshake — so the bearer token is
    passed here rather than in an Authorization header.
    """
    from urllib.parse import quote

    host = api_base_url().replace("https://", "wss://").replace("http://", "ws://")
    return (
        f"{host}/audio-bridge/v2/transcribe"
        f"?tenant-name={quote(settings.corti_tenant_name)}"
        f"&token={quote(f'Bearer {token}')}"
    )


def with_ws_token(websocket_url: str, token: str) -> str:
    """Add the bearer token to a socket URL Corti handed back.

    `POST /interactions/` returns a ready `websocketUrl` (already carrying
    `tenant-name`), but never the credentials — a browser WebSocket handshake
    cannot send an Authorization header, so the token rides in the query
    string the same way it does for dictation.
    """
    from urllib.parse import quote

    separator = "&" if "?" in websocket_url else "?"
    return f"{websocket_url}{separator}token={quote(f'Bearer {token}')}"


# --- Clinical / agentic REST (relative paths under {api_base_url}/v2) ------


class Paths:
    """Relative paths. Join with `api_url()` below."""

    # Interactions
    INTERACTIONS = "/interactions/"
    INTERACTION = "/interactions/{interaction_id}"

    # Facts
    EXTRACT_FACTS = "/tools/extract-facts"
    INTERACTION_FACTS = "/interactions/{interaction_id}/facts/"

    # Documents
    DOCUMENTS = "/documents/"
    INTERACTION_DOCUMENTS = "/interactions/{interaction_id}/documents/"

    # Transcripts / recordings
    INTERACTION_TRANSCRIPTS = "/interactions/{interaction_id}/transcripts/"
    INTERACTION_RECORDINGS = "/interactions/{interaction_id}/recordings/"

    # Coding
    INTERACTION_CODES = "/interactions/{interaction_id}/codes/"

    # Agentic (A2A)
    AGENTS = "/agentic/agents"
    AGENT = "/agentic/agents/{agent_id}"
    AGENT_MESSAGE_SEND = "/agentic/agents/{agent_id}/a2a/message:send"
    AGENT_TASK = "/agentic/agents/{agent_id}/a2a/tasks/{task_id}"
    AGENT_CARD = "/agentic/agents/{agent_id}/a2a"
    CONTEXT = "/agentic/contexts/{context_id}"
    REGISTRY_CONNECTORS = "/agentic/registry/connectors"


def api_url(path: str, **params: str) -> str:
    """Build an absolute API URL: api_url(Paths.INTERACTION, interaction_id=x)."""
    return f"{api_base_url()}/{API_VERSION}{path.format(**params)}"
