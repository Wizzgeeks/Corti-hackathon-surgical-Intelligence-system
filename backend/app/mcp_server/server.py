"""MCP server for the referral triage database.

Exposes patient records to any MCP-capable client (Claude Desktop, an agent
runtime, Corti's MCP connector).

    Two transports:

    * **stdio** (default) — the client launches this server as a subprocess.
      Nothing listens on a port; only that client can reach it.
    * **http** — a long-running server on a port, so clients elsewhere (another
      machine, a container, a hosted MCP client) can connect.

    Run it:

        python -m app.mcp_server.server                    # stdio
        python -m app.mcp_server.server --transport http   # http on :8080

    Over HTTP the endpoint is:

        http://<host>:<port>/mcp

    This serves patient records, so authentication is not optional once it
    leaves localhost: set `MCP_AUTH_TOKEN` and every request must carry
    `Authorization: Bearer <token>`. The server refuses to bind to a
    non-loopback address without one.

    Behind a tunnel or proxy (ngrok, Cloudflare, an ingress), name the public
    hostname or the SDK rejects the request with `421 Misdirected Request`:

        --allowed-hosts abc123.ngrok-free.app

    Environment: MCP_TRANSPORT, MCP_HOST, MCP_PORT, MCP_PATH, MCP_AUTH_TOKEN,
    MCP_ALLOWED_HOSTS.

    Register it with an MCP client (e.g. Claude Desktop's config):

        {
          "mcpServers": {
            "referral-triage": {
              "command": "/absolute/path/to/backend/venv/bin/python",
              "args": ["-m", "app.mcp_server.server"],
              "cwd": "/absolute/path/to/backend"
            }
          }
        }

    Tools:

        get_full_patient_record(patient_id | patient_name)
            {"patient": {...},
             "cases": [{..., "consultations": [...], "appointments": [...]}]}

        search_patients(name)
            [{"_id": "...", "name": "...", "age": 47, ...}]
"""

import argparse
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.db.mongodb import close_mongo_connection, connect_to_mongo
from app.mcp_server.records import (
    consultant_availability,
    full_case_record,
    full_patient_record,
    search_patients,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_server: "MCPServer"):
    """Hold one Mongo connection open for the life of the server.

    A failed connection is logged, not raised: over HTTP this process may be
    long-running and reachable by others, and refusing to start over a
    database blip helps nobody. Tools then fail individually, with a message
    saying why.
    """
    try:
        await connect_to_mongo()
        logger.info("MCP server: connected to Mongo.")
    except Exception as exc:  # noqa: BLE001 — reported per tool call instead
        logger.error("MCP server: no database connection (%s).", exc)

    try:
        yield {}
    finally:
        await close_mongo_connection()


mcp_server = MCPServer(
    name="referral-triage",
    title="Referral Triage Records",
    instructions=(
        "Read-only access to the referral triage database. Use "
        "`get_full_patient_record` for a patient's complete history — their "
        "details, every case, and each case's consultations and appointments. "
        "Use `search_patients` first when you only know a name."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@mcp_server.tool(
    name="get_full_patient_record",
    title="Get full patient record",
    description=(
        "Return everything on file for one patient: their demographic details, "
        "every case, and for each case its consultations and appointments. "
        "Identify the patient by `patient_id` when you have it, otherwise by "
        "exact `patient_name`. Call `search_patients` first if you only know "
        "part of a name."
    ),
)
async def get_full_patient_record(
    patient_id: str | None = None, patient_name: str | None = None
) -> dict[str, Any]:
    """Full patient record: patient, cases, consultations, appointments."""
    try:
        record = await full_patient_record(patient_id, patient_name)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — e.g. the database is unreachable
        logger.exception("get_full_patient_record failed")
        return {"error": f"Could not read the database: {exc}"}

    if not record:
        return {
            "error": "No patient found.",
            "patient_id": patient_id,
            "patient_name": patient_name,
        }
    return record


@mcp_server.tool(
    name="get_full_case_record",
    title="Get full case record",
    description=(
        "Return everything on file for one case, given its `case_id`: the "
        "referral letter it was created from, who referred it, the patient, "
        "every past and future appointment, investigations and their reports, "
        "consultations with their transcripts and summaries, questions put to "
        "consultants and their replies, and any surgery. Use this when you "
        "know which case you are working on; `get_full_patient_record` is the "
        "one to call when you need every case a patient has."
    ),
)
async def get_full_case_record(case_id: str) -> dict[str, Any]:
    """Full case record: referral, patient, appointments, consultations."""
    try:
        record = await full_case_record(case_id)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — e.g. the database is unreachable
        logger.exception("get_full_case_record failed")
        return {"error": f"Could not read the database: {exc}"}

    if not record:
        return {"error": "No case found.", "case_id": case_id}
    return record


@mcp_server.tool(
    name="get_consultant_availability",
    title="Get consultant availability and contacts",
    description=(
        "Return every consultant team with their speciality and the procedures "
        "and diagnoses they cover, each one's upcoming appointments (surgery "
        "and consultation, with their slots), and the contacts on file with "
        "their service and organisation. Only future appointments are "
        "included. Use this to decide which team a referral belongs with and "
        "when the patient could be seen."
    ),
)
async def get_consultant_availability() -> dict[str, Any]:
    """Teams, what they cover, their upcoming diary, and the contact book."""
    try:
        return await consultant_availability()
    except Exception as exc:  # noqa: BLE001 — e.g. the database is unreachable
        logger.exception("get_consultant_availability failed")
        return {"error": f"Could not read the database: {exc}", "team": [],
                "contacts": []}


@mcp_server.tool(
    name="search_patients",
    title="Search patients by name",
    description=(
        "Find patients whose name contains the given text, returning their ids "
        "and basic details. Use this to resolve a name into the `patient_id` "
        "that `get_full_patient_record` takes."
    ),
)
async def search_patients_tool(name: str, limit: int = 20) -> dict[str, Any]:
    """Name search, so a caller can resolve an id."""
    if not name.strip():
        return {"error": "Supply a name to search for.", "patients": []}

    try:
        patients = await search_patients(name, limit)
    except Exception as exc:  # noqa: BLE001 — e.g. the database is unreachable
        logger.exception("search_patients failed")
        return {"error": f"Could not read the database: {exc}", "patients": []}

    return {"count": len(patients), "patients": patients}


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <token>` on every request.

    The MCP spec allows for full OAuth; this is the small version — one shared
    token compared in constant time. It exists because the alternative for a
    network-reachable server holding patient data is no authentication at all.
    """

    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        scheme, _, presented = request.headers.get("authorization", "").partition(" ")

        if scheme.lower() != "bearer" or not secrets.compare_digest(
            presented, self._token
        ):
            client = request.client.host if request.client else "unknown"
            logger.warning("Rejected unauthenticated request from %s", client)
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)


def transport_security(host: str, public_hosts: list[str]) -> TransportSecuritySettings | None:
    """DNS-rebinding protection, widened to whatever fronts this server.

    The SDK validates the `Host` header and rejects anything it does not
    recognise with `421 Misdirected Request`. Bound to localhost it allows
    only localhost, so a tunnel or reverse proxy (ngrok, Cloudflare, an
    ingress) is refused until its hostname is named here — that 421 is the
    guard doing its job, not a bug.
    """
    if not public_hosts:
        # Host validation off by default: this server is reached through
        # tunnels and proxies whose hostnames change, and a 421 on every new
        # ngrok URL costs more than the check is worth here. Access control is
        # MCP_AUTH_TOKEN's job. Set MCP_ALLOWED_HOSTS to turn it back on.
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

    for entry in public_hosts:
        entry = entry.strip()
        if not entry:
            continue
        if entry == "*":
            # Explicitly opting out of Host validation. Only sane behind a
            # proxy that already restricts who can reach this process.
            logger.warning("Host validation disabled (MCP_ALLOWED_HOSTS=*).")
            return TransportSecuritySettings(enable_dns_rebinding_protection=False)
        allowed_hosts += [entry, f"{entry}:*"]
        allowed_origins += [f"https://{entry}", f"http://{entry}", f"https://{entry}:*"]

    logger.info("Allowed Host headers: %s", ", ".join(allowed_hosts))
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def build_http_app(host: str, path: str, token: str, public_hosts: list[str] | None = None) -> Any:
    """The MCP ASGI app, with authentication when a token is configured."""
    app = mcp_server.streamable_http_app(
        streamable_http_path=path,
        host=host,
        transport_security=transport_security(host, public_hosts or []),
    )

    if token:
        app.add_middleware(BearerTokenMiddleware, token=token)
        logger.info("Bearer authentication enabled.")
    elif host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"Refusing to serve patient records on {host} without "
            "authentication. Set MCP_AUTH_TOKEN, or bind to 127.0.0.1."
        )
    else:
        logger.warning(
            "No MCP_AUTH_TOKEN set — reachable on %s only, unauthenticated.", host
        )

    return app


def run_http(
    host: str, port: int, path: str, token: str, public_hosts: list[str]
) -> None:
    """Serve MCP over HTTP so clients that cannot launch us can connect."""
    import uvicorn

    app = build_http_app(host, path, token, public_hosts)
    logger.info("MCP endpoint: http://%s:%d%s", host, port, path)
    uvicorn.run(app, host=host, port=port, log_level="info")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Referral triage MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="stdio for a client-launched subprocess, http to listen on a port",
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8080")))
    parser.add_argument("--path", default=os.getenv("MCP_PATH", "/mcp"))
    parser.add_argument(
        "--allowed-hosts",
        default=os.getenv("MCP_ALLOWED_HOSTS", ""),
        help=(
            "Comma-separated hostnames this server is reached by, beyond "
            "localhost — e.g. an ngrok or proxy hostname. Without them the "
            "SDK answers 421 Misdirected Request. '*' disables the check."
        ),
    )
    return parser.parse_args(argv)


def main() -> None:
    """Run over stdio, or over HTTP when a client cannot launch us."""
    args = parse_args()

    # Under stdio, stdout *is* the transport — logs must go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    if args.transport == "http":
        run_http(
            args.host,
            args.port,
            args.path,
            os.getenv("MCP_AUTH_TOKEN", ""),
            [h for h in args.allowed_hosts.split(",") if h.strip()],
        )
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
