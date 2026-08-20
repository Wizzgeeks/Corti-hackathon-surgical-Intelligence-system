"""Next Action Recommender — the Corti agent that says what to do next.

    curl -X POST \
      'https://api.eu.corti.app/v2/agentic/agents/agt.e1f26bf9-dc7c-419f-a29b-52ec35d26d85/a2a/message:send' \
      -H 'Authorization: Bearer <token>' \
      -H 'Tenant-Name: base' \
      -H 'A2A-Version: 1.0' \
      -H 'Content-Type: application/json' \
      -d '{
        "message": {
          "role": "ROLE_USER",
          "parts": [
            {"text": "Use the get_full_case_record tool to look up the case, the get_consultant_availability tool to identify the team'"'"'s availability and who are all there in the system, who is in the team and who is in the contacts and identify the next action recommender as per the instruction"},
            {"data": {"case_id": "6a870af1673e6e16229531a0"}}
          ]
        }
      }'

The only agent of the four that reads two tools: the case record for what is
wrong, and consultant availability for who could act on it and when. That is
what lets it name a team and a slot rather than only a next step. What counts
as a good recommendation lives with the agent in the Console.
"""

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
NEXT_ACTION_AGENT_ID = (
    f"agt.{settings.corti_next_action_agent_id.removeprefix('agt.')}"
)

# Both tool names are the ones our MCP server registers, so the agent's
# connector can find them. They must not drift from `app/mcp_server/server.py`.
INSTRUCTION = (
    "Use the get_full_case_record tool to look up the case, the "
    "get_consultant_availability tool to identify the team's availability and "
    "who are all there in the system, who is in the team and who is in the "
    "contacts and identify the next action recommender as per the instruction"
)

# A recommendation written as a numbered or bulleted list — the shape the
# agent uses when it has several steps rather than one.
STEP_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(?P<step>.+)$")


@dataclass
class NextActionReply:
    """What the agent recommends, plus the exchange that produced it."""

    text: str = ""
    # Returned so a follow-up question continues the same conversation.
    context_id: str = ""
    request: Any = None
    response: Any = None
    # Anything the agent returned as structured data alongside its prose.
    data: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recommendation(self) -> str:
        """The recommendation itself, exactly as the agent wrote it."""
        return self.text

    @property
    def steps(self) -> list[str]:
        """The recommendation split into its individual actions.

        A single-action recommendation comes back as one step, so a caller can
        always iterate rather than branching on the shape.
        """
        return split_steps(self.text)

    def as_call(self, agent_name: str = "next_action_recommender") -> dict[str, Any]:
        """The shape the APIs log Corti round trips in."""
        return {
            "agent_name": agent_name,
            "corti_request": self.request,
            "corti_response": self.response,
        }


def split_steps(text: str) -> list[str]:
    """Read the individual actions out of the agent's reply.

    A line that does not open a new step is treated as a continuation of the
    one above it, so a wrapped sentence stays with its action.
    """
    body = (text or "").strip()
    if not body:
        return []

    steps: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        match = STEP_LINE.match(line)
        if match:
            steps.append(match.group("step").strip())
        elif steps:
            steps[-1] = f"{steps[-1]} {line}".strip()
        else:
            steps.append(line)
    return steps


def build_payload(
    case_id: str,
    *,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> dict[str, Any]:
    """The A2A body: what to do in `text`, which case in `data`.

    Two parts rather than one sentence — the agent's tool calls read the id
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


def read_data_parts(response: dict[str, Any]) -> list[dict[str, Any]]:
    """The structured parts of the reply, if the agent returned any."""
    task = (response or {}).get("task") or {}
    found: list[dict[str, Any]] = []
    for artifact in task.get("artifacts") or []:
        for part in artifact.get("parts") or []:
            if isinstance(part.get("data"), dict):
                found.append(part["data"])
    return found


async def recommend_next_action(
    *,
    case_id: str,
    access_token: str | None = None,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> NextActionReply:
    """Ask the agent what should happen next on a case.

    `access_token` is the token the caller already holds; passing None logs in
    under the agent project's credentials, which is usually what you want — a
    token minted for the clinical APIs belongs to a different project and gets
    `expert_not_found`. A 401 raises `CortiUnauthorizedError`, which the
    orchestrator handles by re-authenticating and retrying.
    """
    case = (case_id or "").strip()
    if not case:
        logger.warning("next_action_recommender: no case id to look up.")
        return NextActionReply()

    payload = build_payload(
        case, instruction=instruction, data=data, context_id=context_id
    )
    url = urls.api_url(urls.Paths.AGENT_MESSAGE_SEND, agent_id=NEXT_ACTION_AGENT_ID)

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
        "next_action_recommender: case %s -> %d chars from agent %s.",
        case,
        len(reply),
        NEXT_ACTION_AGENT_ID,
    )
    return NextActionReply(
        text=reply,
        context_id=read_context_id(response or {}),
        request=payload,
        response=response,
        data=read_data_parts(response or {}),
    )
