"""Orchestrators — control agents that decide which agent runs next.

An orchestrator is an `Agent` like any other, but it produces routing rather
than clinical output. Keeping them here means a workflow can pick the
orchestrator it wants while reusing the same skilled agents.

    chat_orchestrator.py      model-driven routing for the chat workflow
    referral_orchestrator.py  fixed-sequence routing for referral intake,
                              plus assembly of the referral JSON

There is deliberately **no default orchestrator**. Each workflow names the one
it uses, so adding an orchestrator here never silently changes another
workflow's entry point.
"""

from app.agents.base import Agent
from app.agents.orchestrators.chat_orchestrator import DONE, ChatOrchestrator
from app.agents.orchestrators.referral_orchestrator import (
    OUTPUT_FIELDS,
    SAMPLE_OUTPUT,
    ReferralOrchestrator,
)

ORCHESTRATOR_CLASSES: tuple[type[Agent], ...] = (
    ChatOrchestrator,
    ReferralOrchestrator,
)

# Node name -> orchestrator class, for lookup by name.
ORCHESTRATORS: dict[str, type[Agent]] = {
    cls.spec.name: cls for cls in ORCHESTRATOR_CLASSES
}

__all__ = [
    "DONE",
    "ORCHESTRATORS",
    "ORCHESTRATOR_CLASSES",
    "OUTPUT_FIELDS",
    "SAMPLE_OUTPUT",
    "ChatOrchestrator",
    "ReferralOrchestrator",
]
