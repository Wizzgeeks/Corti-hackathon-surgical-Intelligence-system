"""Corti agentic agents, addressed one file per agent.

Distinct from `app/agents/`, which is our own agent library: these are agents
built and configured in the Corti Console, reached over A2A `message:send`.
The Console owns the prompt and the tools; a file here only says which agent
to talk to and how to phrase the question.
"""

from app.corti_agents.case_summariser import (
    CASE_SUMMARY_AGENT_ID,
    CaseSummaryReply,
    summarise_case,
)
from app.corti_agents.consultation_letter_writer import (
    CONSULTATION_LETTER_AGENT_ID,
    ConsultationLetterReply,
    write_consultation_letter,
)
from app.corti_agents.flag_detector import (
    FLAG_AGENT_ID,
    FlagReply,
    detect_flags,
)
from app.corti_agents.next_action_recommender import (
    NEXT_ACTION_AGENT_ID,
    NextActionReply,
    recommend_next_action,
)
from app.corti_agents.urgency_identifier import (
    URGENCY_AGENT_ID,
    UrgencyReply,
    identify_urgency,
    parse_reply,
)

__all__ = [
    "CASE_SUMMARY_AGENT_ID",
    "CONSULTATION_LETTER_AGENT_ID",
    "ConsultationLetterReply",
    "write_consultation_letter",
    "FLAG_AGENT_ID",
    "NEXT_ACTION_AGENT_ID",
    "NextActionReply",
    "recommend_next_action",
    "FlagReply",
    "detect_flags",
    "CaseSummaryReply",
    "URGENCY_AGENT_ID",
    "UrgencyReply",
    "identify_urgency",
    "parse_reply",
    "summarise_case",
]
