"""Case Summariser — the Corti agent that writes a case up in full.

    curl -X POST \
      'https://api.eu.corti.app/v2/agentic/agents/agt.a8f527e0-ec46-4809-96d0-6afcf21ed199/a2a/message:send' \
      -H 'Authorization: Bearer <token>' \
      -H 'Tenant-Name: base' \
      -H 'A2A-Version: 1.0' \
      -H 'Content-Type: application/json' \
      -d '{
        "message": {
          "role": "ROLE_USER",
          "parts": [
            {"text": "Use the get_full_case_record tool to extract the case details and provide full summary as per the given instructions"},
            {"data": {"case_id": "6a870af1673e6e16229531a0"}}
          ]
        }
      }'

Takes a case id and nothing else: the agent pulls the record itself through
our MCP server's `get_full_case_record`, so it summarises what is stored
rather than whatever we chose to send it. The instructions it writes to —
what a full summary contains, and in what order — live with the agent in the
Console.

Sibling of `urgency_identifier`, which grades the same case by patient name.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.services import corti_endpoints as urls
from app.services.corti_agents import (
    A2A_HEADERS,
    read_agent_reply,
    read_context_id,
)
from app.services.corti_client import CortiClient

logger = logging.getLogger(__name__)

# Agentic agents are addressed with the `agt.` prefix; the Console shows the
# bare uuid, so it is added here rather than expected in config.
CASE_SUMMARY_AGENT_ID = (
    f"agt.{settings.corti_case_summary_agent_id.removeprefix('agt.')}"
)

# The tool name is the one our MCP server registers, so the agent's connector
# can find it. It must not drift from `app/mcp_server/server.py`.
INSTRUCTION = (
    "Use the get_full_case_record tool to extract the case details and "
    "provide full summary as per the given instructions"
)


@dataclass
class CaseSummaryReply:
    """The agent's write-up, plus the exchange that produced it."""

    text: str = ""
    # Returned so a follow-up question continues the same conversation.
    context_id: str = ""
    request: Any = None
    response: Any = None
    # Anything the agent returned as structured data alongside its prose —
    # the record its tool call fetched, typically.
    data: list[dict[str, Any]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """The write-up itself, exactly as the agent wrote it."""
        return self.text

    @property
    def points(self) -> list[str]:
        """The write-up split into its individual points.

        The agent returns a comma-separated list of quoted strings — one per
        point — rather than prose or JSON. This decodes that into a list;
        anything that does not parse comes back as a single point, so the
        text is never lost to a format change at the agent's end.
        """
        return split_points(self.text)

    def as_call(self, agent_name: str = "case_summariser") -> dict[str, Any]:
        """The shape the APIs log Corti round trips in."""
        return {
            "agent_name": agent_name,
            "corti_request": self.request,
            "corti_response": self.response,
        }


def build_payload(
    case_id: str,
    *,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> dict[str, Any]:
    """The A2A body: what to do in `text`, which case in `data`.

    Two parts rather than one sentence — the agent's tool call reads the id
    from the structured part, so it does not have to parse it back out of
    prose.
    """
    parts: list[dict[str, Any]] = [
        {"text": instruction},
        {"data": {"case_id": case_id, **(data or {})}},
    ]
    message: dict[str, Any] = {"role": "ROLE_USER", "parts": parts}
    if context_id:
        message["contextId"] = context_id

    return {"message": message}


def split_points(text: str) -> list[str]:
    """Decode the agent's quoted-string list into its points."""
    body = (text or "").strip()
    if not body:
        return []
    # Wrapping it makes the agent's bare comma-separated list valid JSON.
    for candidate in (body, f"[{body.rstrip(',').rstrip('}')}]"):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, str):
            return [parsed.strip()]
    # Fall back to the quoted spans, then to the whole reply.
    quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', body)
    return [q.strip() for q in quoted if q.strip()] or [body]


def read_data_parts(response: dict[str, Any]) -> list[dict[str, Any]]:
    """The structured parts of the reply, if the agent returned any."""
    task = (response or {}).get("task") or {}
    found: list[dict[str, Any]] = []
    for artifact in task.get("artifacts") or []:
        for part in artifact.get("parts") or []:
            if isinstance(part.get("data"), dict):
                found.append(part["data"])
    return found


async def summarise_case(
    *,
    case_id: str,
    access_token: str | None = None,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> CaseSummaryReply:
    """Ask the summariser agent to write up a case.

    `access_token` is the token the caller already holds; passing None logs in
    under the agent project's credentials, which is usually what you want — a
    token minted for the clinical APIs belongs to a different project and gets
    `expert_not_found`. A 401 raises `CortiUnauthorizedError`, which the
    orchestrator handles by re-authenticating and retrying.
    """
    case = (case_id or "").strip()
    if not case:
        logger.warning("case_summariser: no case id to summarise.")
        return CaseSummaryReply()

    payload = build_payload(
        case, instruction=instruction, data=data, context_id=context_id
    )
    url = urls.api_url(urls.Paths.AGENT_MESSAGE_SEND, agent_id=CASE_SUMMARY_AGENT_ID)

    # Agents are owned by the Console project that created them, so this goes
    # out under the agent credentials rather than the clinical-API ones.
    response = await CortiClient.for_agents().post(
        url,
        json=payload,
        extra_headers={
            **A2A_HEADERS,
            "X-Corti-Retention-Policy": settings.corti_retention_policy,
        },
        access_token=access_token,
    )

    reply = read_agent_reply(response or {})
    logger.info(
        "case_summariser: case %s -> %d chars from agent %s.",
        case,
        len(reply),
        CASE_SUMMARY_AGENT_ID,
    )
    return CaseSummaryReply(
        text=reply,
        context_id=read_context_id(response or {}),
        request=payload,
        response=response,
        data=read_data_parts(response or {}),
    )
