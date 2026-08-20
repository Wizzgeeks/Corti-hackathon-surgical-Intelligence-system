"""Corti agentic agents — sending a message and reading the reply.

Corti's agents speak A2A: you post a message to an agent and get back either a
`task` (long-running work, the reply sitting in its history) or a `message`
(answered directly). Agents are created and configured in the Console, so the
only thing to supply here is the agent id and what to say.
"""

import logging
from typing import Any

from app.core.config import settings
from app.services import corti_endpoints as urls
from app.services.corti_client import CortiClient
from app.services.corti_textgen import CortiResult

logger = logging.getLogger(__name__)

# The A2A binding is versioned, and the header is required.
A2A_HEADERS = {"A2A-Version": "1.0"}

ROLE_AGENT = "ROLE_AGENT"


def build_message_payload(
    text: str, context_id: str | None = None, blocking: bool = True
) -> dict[str, Any]:
    """An A2A `message:send` body.

    `returnImmediately: False` (the default) waits for the task to finish, so
    a single call returns the answer rather than an id to poll.
    """
    message: dict[str, Any] = {
        "role": "ROLE_USER",
        "parts": [{"text": text}],
    }
    if context_id:
        message["contextId"] = context_id

    return {
        "message": message,
        "configuration": {"returnImmediately": not blocking},
    }


def read_agent_reply(response: dict[str, Any]) -> str:
    """Pull the agent's answer out of an A2A response.

    A `message` reply carries the text directly; a `task` reply keeps it in
    the history, as the last message from the agent.
    """
    response = response or {}

    def parts_text(parts: list[dict] | None) -> str:
        return "\n".join(
            str(p.get("text") or "").strip() for p in (parts or []) if p.get("text")
        ).strip()

    direct = response.get("message")
    if direct:
        text = parts_text(direct.get("parts"))
        if text:
            return text

    task = response.get("task") or {}
    for entry in reversed(task.get("history") or []):
        if entry.get("role") == ROLE_AGENT:
            text = parts_text(entry.get("parts"))
            if text:
                return text

    # Some agents answer with artifacts rather than a message.
    for artifact in task.get("artifacts") or []:
        text = parts_text(artifact.get("parts"))
        if text:
            return text

    return ""


def read_context_id(response: dict[str, Any]) -> str:
    """The context id, so a follow-up message continues the conversation."""
    task = (response or {}).get("task") or {}
    return task.get("contextId") or (response or {}).get("message", {}).get(
        "contextId", ""
    )


async def send_agent_message(
    *,
    agent_id: str,
    text: str,
    access_token: str | None,
    context_id: str | None = None,
) -> CortiResult:
    """Send one message to a Corti agent and return its reply.

    `access_token` is the token the workflow already holds in graph state; a
    401 sends the run back through the authenticator and resumes here.
    """
    payload = build_message_payload(text, context_id)
    url = urls.api_url(urls.Paths.AGENT_MESSAGE_SEND, agent_id=agent_id)

    response = await CortiClient().post(
        url,
        json=payload,
        extra_headers={
            **A2A_HEADERS,
            "X-Corti-Retention-Policy": settings.corti_retention_policy,
        },
        access_token=access_token,
    )

    reply = read_agent_reply(response or {})
    logger.info("Agent %s replied with %d chars.", agent_id, len(reply))
    return CortiResult(text=reply, request=payload, response=response)
