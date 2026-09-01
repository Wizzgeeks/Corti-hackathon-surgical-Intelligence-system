"""Urgency Identifier — the Corti agent that grades a referral's urgency.

    curl -X POST \
      'https://api.eu.corti.app/v2/agentic/agents/agt.d8a2e8a1-496d-4a55-a4cf-629ab61519f2/a2a/message:send' \
      -H 'Authorization: Bearer <token>' \
      -H 'Tenant-Name: base' \
      -H 'A2A-Version: 1.0' \
      -H 'Content-Type: application/json' \
      -d '{
        "message": {
          "role": "ROLE_USER",
          "parts": [
            {"text": "Use the search_patients tool to look up the patient and classify the urgency of their orthopaedic referral."},
            {"data": {"name": "Janelle Henderson"}}
          ]
        }
      }'

The agent is configured in the Console and reaches our MCP server for the
record itself, so the message carries the patient's name rather than the case:
the instruction tells it which tool to use, and the `data` part gives it the
argument. Everything else — the prompt, the grading scale, the tools — lives
with the agent, not here.

It answers as JSON in a text part — recommendation, evidence, rationale — with
the patient the tool found alongside it. `parse_reply()` decodes that; the raw
text is kept either way, since the agent is free to answer in prose.
"""

import json
import logging
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
URGENCY_AGENT_ID = f"agt.{settings.corti_urgency_agent_id.removeprefix('agt.')}"

# What the agent is asked to do. The tool name is Corti's connector to our MCP
# server, so it must match the connector's tool, not our Python function.
INSTRUCTION = (
    "Use the search_patients tool to look up the patient and classify the "
    "urgency of their orthopaedic referral."
)


@dataclass
class UrgencyReply:
    """The agent's answer, plus the exchange that produced it."""

    text: str = ""
    # The decoded answer when the agent replies in JSON; empty otherwise.
    verdict: dict[str, Any] = field(default_factory=dict)
    # Returned so a follow-up question continues the same conversation.
    context_id: str = ""
    request: Any = None
    response: Any = None

    @property
    def recommendation(self) -> str:
        """The urgency grade — ROUTINE, URGENT, and so on.

        The agent names this `category` on some runs and `recommendation` on
        others, so both are read; reading only one leaves the grade empty and
        the case's urgency unset.
        """
        return str(
            self.verdict.get("recommendation") or self.verdict.get("category") or ""
        )

    @property
    def rationale(self) -> str:
        """Why the agent graded it that way, for the case's urgency reason.

        The agent names this field either way from run to run, so both are
        read and the plain text is the last resort.
        """
        for key in ("rationale", "concise_reasoning", "reasoning"):
            if self.verdict.get(key):
                return str(self.verdict[key])
        return "" if self.verdict else self.text

    @property
    def escalate(self) -> bool:
        """Whether the agent wants a clinician to look before booking."""
        return bool(self.verdict.get("requires_clinician_escalation"))

    @property
    def evidence(self) -> list[str]:
        """The referral lines the grade was drawn from."""
        return [str(item) for item in (self.verdict.get("evidence") or [])]

    def as_call(self, agent_name: str = "urgency_identifier") -> dict[str, Any]:
        """The shape the APIs log Corti round trips in."""
        return {
            "agent_name": agent_name,
            "corti_request": self.request,
            "corti_response": self.response,
        }


def build_payload(
    patient_name: str,
    *,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> dict[str, Any]:
    """The A2A body: what to do in `text`, what to do it to in `data`.

    Two parts rather than one sentence — the agent's tool call reads the name
    from the structured part, so it does not have to parse it back out of
    prose. No `configuration` block: the agent runs to completion and returns
    the finished task by default.
    """
    parts: list[dict[str, Any]] = [
        {"text": instruction},
        {"data": {"name": patient_name, **(data or {})}},
    ]
    message: dict[str, Any] = {"role": "ROLE_USER", "parts": parts}
    if context_id:
        message["contextId"] = context_id

    return {"message": message}


def parse_reply(text: str) -> dict[str, Any]:
    """Decode the agent's JSON verdict, tolerating prose around it."""
    body = (text or "").strip()
    if not body:
        return {}
    # Some replies fence the JSON as markdown.
    if body.startswith("```"):
        body = body.strip("`").removeprefix("json").strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(body[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("urgency_identifier: reply was not JSON.")
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def identify_urgency(
    *,
    patient_name: str,
    access_token: str | None = None,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> UrgencyReply:
    """Ask the urgency agent to grade this patient's referral.

    `access_token` is the token the caller already holds; passing None logs in
    under the agent project's credentials, which is usually what you want —
    a token minted for the clinical APIs belongs to a different project and
    gets `expert_not_found`. A 401 raises `CortiUnauthorizedError`, which the
    orchestrator handles by re-authenticating and retrying.
    """
    name = (patient_name or "").strip()
    if not name:
        logger.warning("urgency_identifier: no patient name to look up.")
        return UrgencyReply()

    payload = build_payload(
        name, instruction=instruction, data=data, context_id=context_id
    )
    url = urls.api_url(urls.Paths.AGENT_MESSAGE_SEND, agent_id=URGENCY_AGENT_ID)

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
    verdict = parse_reply(reply)
    logger.info(
        "urgency_identifier: %s -> %s (%d chars) from agent %s.",
        name,
        verdict.get("recommendation") or "no grade",
        len(reply),
        URGENCY_AGENT_ID,
    )
    return UrgencyReply(
        text=reply,
        verdict=verdict,
        context_id=read_context_id(response or {}),
        request=payload,
        response=response,
    )
