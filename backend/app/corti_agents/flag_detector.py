"""Flag Detector — the Corti agent that raises the flags on a case.

    curl -X POST \
      'https://api.eu.corti.app/v2/agentic/agents/agt.7dcc2ffa-ff50-4aa7-88d7-bbe126d75f62/a2a/message:send' \
      -H 'Authorization: Bearer <token>' \
      -H 'Tenant-Name: base' \
      -H 'A2A-Version: 1.0' \
      -H 'Content-Type: application/json' \
      -d '{
        "message": {
          "role": "ROLE_USER",
          "parts": [
            {"text": "Use the get_full_case_record tool to look up the case and identify the flags as per the instruction"},
            {"data": {"case_id": "6a870af1673e6e16229531a0"}}
          ]
        }
      }'

Takes a case id and nothing else: the agent pulls the record itself through
our MCP server's `get_full_case_record`. What counts as a flag, and how it is
graded, lives with the agent in the Console.

Sibling of `case_summariser`, which writes the same case up from the same
tool call.
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
FLAG_AGENT_ID = f"agt.{settings.corti_flag_agent_id.removeprefix('agt.')}"

# The tool name is the one our MCP server registers, so the agent's connector
# can find it. It must not drift from `app/mcp_server/server.py`.
INSTRUCTION = (
    "Use the get_full_case_record tool to look up the case and identify the "
    "flags as per the instruction"
)

# Severity words the agent uses, mapped onto what `Case.flags` stores.
SEVERITY_WORDS = {
    "critical": "critical",
    "severe": "critical",
    "red": "critical",
    "high": "high",
    "urgent": "high",
    "medium": "medium",
    "moderate": "medium",
    "amber": "medium",
    "low": "low",
    "minor": "low",
    "green": "low",
}


@dataclass
class FlagReply:
    """The flags the agent raised, plus the exchange that produced it."""

    text: str = ""
    # One entry per flag: {"label", "severity", "rationale"}.
    flags: list[dict[str, Any]] = field(default_factory=list)
    # Returned so a follow-up question continues the same conversation.
    context_id: str = ""
    request: Any = None
    response: Any = None

    def as_call(self, agent_name: str = "flag_detector") -> dict[str, Any]:
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


def read_severity(value: Any, fallback: str = "medium") -> str:
    """Map whatever the agent called the severity onto our four levels.

    An unrecognised word becomes `medium` rather than being dropped: a flag
    with an odd label is still a flag, and silently discarding it would hide
    a clinical concern.
    """
    word = str(value or "").strip().lower()
    for key, level in SEVERITY_WORDS.items():
        if key in word:
            return level
    return fallback


def parse_flags(text: str) -> list[dict[str, Any]]:
    """Turn the agent's reply into flags.

    It answers as JSON when it can — an array of objects, or one wrapped
    under `flags` — but occasionally as a list of sentences. Both are
    accepted, and an unparseable reply becomes a single flag holding the whole
    text, so nothing the agent said is lost.
    """
    body = (text or "").strip()
    if not body:
        return []
    if body.startswith("```"):
        body = body.strip("`").removeprefix("json").strip()

    def _as_flag(item: Any) -> dict[str, Any] | None:
        if isinstance(item, str):
            label = item.strip()
            return {"label": label, "severity": read_severity(label), "rationale": ""}
        if not isinstance(item, dict):
            return None
        label = str(
            item.get("label")
            or item.get("flag")
            or item.get("name")
            or item.get("title")
            or ""
        ).strip()
        rationale = str(
            item.get("rationale")
            or item.get("reason")
            or item.get("evidence")
            or item.get("detail")
            or ""
        ).strip()
        if not label and not rationale:
            return None
        return {
            # A flag that is all rationale still needs a name to show under.
            "label": label or rationale,
            "severity": read_severity(item.get("severity") or item.get("level"), ),
            "rationale": rationale,
        }

    # A JSON array, an object wrapping one, or the agent's bare comma-separated
    # list of quoted strings.
    for candidate in (body, f"[{body.rstrip(',').rstrip('}')}]"):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed = (
                parsed.get("flags")
                or parsed.get("clinical_flags")
                or parsed.get("items")
                or [parsed]
            )
        if isinstance(parsed, list):
            found = [f for f in (_as_flag(item) for item in parsed) if f]
            if found:
                return found

    quoted = [q.strip() for q in re.findall(r'"((?:[^"\\]|\\.)*)"', body) if q.strip()]
    if quoted:
        return [f for f in (_as_flag(q) for q in quoted) if f]

    lines = parse_flag_lines(body)
    if lines:
        return lines

    logger.warning("flag_detector: reply did not parse as flags; kept as one.")
    return [{"label": body, "severity": read_severity(body), "rationale": ""}]


# "MEDIUM — Record-integrity concern: the case summary states..." — the shape
# the agent writes when it answers in prose rather than JSON. The dash may be
# an em dash, an en dash or a hyphen.
FLAG_LINE = re.compile(
    r"^\s*[-*\u2022]?\s*(?P<severity>%s)\b\s*[\u2014\u2013:-]+\s*(?P<body>.+)$"
    % "|".join(SEVERITY_WORDS),
    re.IGNORECASE,
)


def parse_flag_lines(text: str) -> list[dict[str, Any]]:
    """Read one flag per line from the agent's prose answer.

    Each line leads with its severity, then the concern, then the detail
    behind a colon. A line that does not lead with a severity is treated as a
    continuation of the flag above it rather than as a new one.
    """
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = FLAG_LINE.match(line)
        if not match:
            if found:
                found[-1]["rationale"] = f"{found[-1]['rationale']} {line}".strip()
            continue
        rest = match.group("body").strip()
        # The concern is the clause before the first colon; the rest is why.
        label, _, rationale = rest.partition(":")
        found.append(
            {
                "label": label.strip() or rest,
                "severity": read_severity(match.group("severity")),
                "rationale": rationale.strip(),
            }
        )
    return found


async def detect_flags(
    *,
    case_id: str,
    access_token: str | None = None,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> FlagReply:
    """Ask the flag agent what should be flagged on a case.

    `access_token` is the token the caller already holds; passing None logs in
    under the agent project's credentials, which is usually what you want — a
    token minted for the clinical APIs belongs to a different project and gets
    `expert_not_found`. A 401 raises `CortiUnauthorizedError`, which the
    orchestrator handles by re-authenticating and retrying.
    """
    case = (case_id or "").strip()
    if not case:
        logger.warning("flag_detector: no case id to look up.")
        return FlagReply()

    payload = build_payload(
        case, instruction=instruction, data=data, context_id=context_id
    )
    url = urls.api_url(urls.Paths.AGENT_MESSAGE_SEND, agent_id=FLAG_AGENT_ID)

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
    flags = parse_flags(reply)
    logger.info(
        "flag_detector: case %s -> %d flag(s) from agent %s.",
        case,
        len(flags),
        FLAG_AGENT_ID,
    )
    return FlagReply(
        text=reply,
        flags=flags,
        context_id=read_context_id(response or {}),
        request=payload,
        response=response,
    )
