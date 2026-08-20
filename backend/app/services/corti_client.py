"""All Corti API calls live here.

Auth model: Corti uses OAuth2 client credentials. Every call to a Corti API
first calls the login endpoint to obtain an access token, then sends that token
as a Bearer header on the actual request. The token is **never persisted** — it
exists only for the duration of the call and is discarded afterwards.

Add new Corti calls as methods on `CortiClient`; put their URLs in
`corti_endpoints.py`.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services import corti_endpoints as urls

logger = logging.getLogger(__name__)


class CortiError(Exception):
    """Any failure talking to Corti."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class CortiAuthError(CortiError):
    """The login call failed — bad credentials, wrong realm, or auth is down."""


class CortiUnauthorizedError(CortiError):
    """An API call was rejected with 401 — token expired or not accepted.

    Raised separately so callers (and the orchestrator) can detect an auth
    rejection without inspecting message text.
    """

    def __init__(self, message: str, body: Any = None):
        super().__init__(message, status_code=401, body=body)


class CortiClient:
    """Thin wrapper over the Corti REST APIs."""

    @classmethod
    def for_agents(cls) -> "CortiClient":
        """A client for the Console project that owns our agentic agents.

        Agents are scoped to the project that created them: a token from
        another project gets `expert_not_found`, not a 403. Falls back to the
        main credentials when no separate pair is configured.
        """
        return cls(
            client_id=settings.corti_agent_client_id or None,
            client_secret=settings.corti_agent_client_secret or None,
        )

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        tenant_name: str | None = None,
        timeout: float | None = None,
    ):
        self.client_id = client_id or settings.corti_client_id
        self.client_secret = client_secret or settings.corti_client_secret
        self.tenant_name = tenant_name or settings.corti_tenant_name
        self.timeout = timeout or settings.corti_timeout_seconds

        if not self.client_id or not self.client_secret:
            raise CortiAuthError(
                "CORTI_CLIENT_ID / CORTI_CLIENT_SECRET are not configured."
            )

    # --- Auth --------------------------------------------------------------

    async def login(self, scope=settings.corti_scope) -> str:
        """Corti login. Returns a short-lived access token (~5 minutes).

        Called automatically before every other request — you rarely need to
        call this directly. Use `login_details()` when the caller also wants
        the expiry and scope Corti returned alongside the token.
        """
        return (await self.login_details(scope))["access_token"]

    async def login_details(self, scope=settings.corti_scope) -> dict[str, Any]:
        """Corti login, returning the whole token response.

        Same call as `login()`; this keeps `expires_in`, `token_type` and
        `scope`, which a caller handing the token onward needs in order to
        know when to ask for another.
        """
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": scope,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            response = await http.post(
                urls.token_url(),
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != httpx.codes.OK:
            raise CortiAuthError(
                f"Corti login failed ({response.status_code}).",
                status_code=response.status_code,
                body=_safe_body(response),
            )

        body = response.json()
        if not body.get("access_token"):
            raise CortiAuthError("Corti login returned no access_token.")
        return body

    # --- Core request path -------------------------------------------------

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        access_token: str | None = None,
    ) -> Any:
        """Make an authenticated Corti API call.

        Pass `access_token` to reuse a token the workflow already holds (the
        graph carries one per run); omit it to log in for this call. Every
        Corti call goes through here so the auth headers are applied in exactly
        one place.
        """
        token = access_token or await self.login()

        headers = {
            "Authorization": f"Bearer {token}",
            "Tenant-Name": self.tenant_name,
            "Accept": "application/json",
            **(extra_headers or {}),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            response = await http.request(
                method, url, json=json, params=params, headers=headers
            )

        if response.status_code == httpx.codes.UNAUTHORIZED:
            logger.warning("Corti %s %s -> 401 (token rejected)", method, url)
            raise CortiUnauthorizedError(
                f"Corti rejected the token (401) for {method} {url}.",
                body=_safe_body(response),
            )

        if response.is_error:
            logger.error("Corti %s %s -> %s", method, url, response.status_code)
            raise CortiError(
                f"Corti request failed ({response.status_code}) for {method} {url}.",
                status_code=response.status_code,
                body=_safe_body(response),
            )

        if not response.content:
            return None
        return response.json()

    async def get(self, url: str, **kwargs: Any) -> Any:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self.request("POST", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", url, **kwargs)


def _safe_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


def get_corti_client() -> CortiClient:
    """FastAPI dependency / helper for obtaining a client."""
    return CortiClient()
