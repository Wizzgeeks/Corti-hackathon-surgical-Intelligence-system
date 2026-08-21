"""Consultation Letter Writer — the Corti agent that drafts the letter.

    curl -X POST \
      'https://api.eu.corti.app/v2/agentic/agents/agt.c87093cd-975c-4de3-ac77-564eea80f96a/a2a/message:send' \
      -H 'Authorization: Bearer <token>' \
      -H 'Tenant-Name: base' \
      -H 'A2A-Version: 1.0' \
      -H 'Content-Type: application/json' \
      -d '{
        "message": {
          "role": "ROLE_USER",
          "parts": [
            {"text": "Write the consultation letter as per the instruction..."},
            {"data": {
              "current_consultation_summary": "...",
              "previous_consultation_letters": [],
              "patient": {"name": "...", "age": 29, "gender": "male"}
            }}
          ]
        }
      }'

Unlike the other four agents, this one reads no tools: everything it needs is
handed to it in the `data` part, because the letter is written from what the
clinician has on screen — including edits they have not saved yet. What a good
letter looks like lives with the agent in the Console.
"""

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
CONSULTATION_LETTER_AGENT_ID = (
    f"agt.{settings.corti_consultation_letter_agent_id.removeprefix('agt.')}"
)

INSTRUCTION = (
    "Write the consultation letter for this patient as per the instruction. "
    "Use the current consultation summary as the substance of the letter, the "
    "previous consultation letters for what has already been said and done, "
    "and the patient demographics to address it. Do not invent anything that "
    "is not in the material given."
)


@dataclass
class ConsultationLetterReply:
    """The drafted letter, plus the exchange that produced it."""

    text: str = ""
    # Returned so a follow-up — "make it shorter" — continues the same thread.
    context_id: str = ""
    request: Any = None
    response: Any = None
    data: list[dict[str, Any]] = field(default_factory=list)

    @property
    def letter(self) -> str:
        """The letter itself, exactly as the agent wrote it."""
        return self.text

    def as_call(
        self, agent_name: str = "consultation_letter_writer"
    ) -> dict[str, Any]:
        """The shape the APIs log Corti round trips in."""
        return {
            "agent_name": agent_name,
            "corti_request": self.request,
            "corti_response": self.response,
        }


def build_payload(
    *,
    current_consultation_summary: str,
    previous_consultation_letters: list[str] | None = None,
    patient: dict[str, Any] | None = None,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> dict[str, Any]:
    """The A2A body: what to write in `text`, what to write it from in `data`.

    Two parts rather than one long sentence — the material is structured, and
    the agent should not have to parse the demographics back out of prose.
    """
    parts: list[dict[str, Any]] = [
        {"text": instruction},
        {
            "data": {
                "current_consultation_summary": current_consultation_summary,
                # Always present, empty list included: an agent that is told
                # there are none writes a first letter rather than guessing.
                "previous_consultation_letters": previous_consultation_letters
                or [],
                "patient": patient or {},
                **(data or {}),
            }
        },
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


async def write_consultation_letter(
    *,
    current_consultation_summary: str,
    previous_consultation_letters: list[str] | None = None,
    patient: dict[str, Any] | None = None,
    access_token: str | None = None,
    instruction: str = INSTRUCTION,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> ConsultationLetterReply:
    """Ask the agent to draft the letter for one consultation.

    `access_token` is the token the caller already holds; passing None logs in
    under the agent project's credentials, which is usually what you want — a
    token minted for the clinical APIs belongs to a different project and gets
    `expert_not_found`.
    """
    summary = (current_consultation_summary or "").strip()
    if not summary:
        logger.warning("consultation_letter_writer: no summary to write from.")
        return ConsultationLetterReply()

    payload = build_payload(
        current_consultation_summary=summary,
        previous_consultation_letters=previous_consultation_letters,
        patient=patient,
        instruction=instruction,
        data=data,
        context_id=context_id,
    )
    url = urls.api_url(
        urls.Paths.AGENT_MESSAGE_SEND, agent_id=CONSULTATION_LETTER_AGENT_ID
    )

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
        "consultation_letter_writer: %d chars of summary and %d previous "
        "letter(s) -> %d chars from agent %s.",
        len(summary),
        len(previous_consultation_letters or []),
        len(reply),
        CONSULTATION_LETTER_AGENT_ID,
    )
    return ConsultationLetterReply(
        text=reply,
        context_id=read_context_id(response or {}),
        request=payload,
        response=response,
        data=read_data_parts(response or {}),
    )
