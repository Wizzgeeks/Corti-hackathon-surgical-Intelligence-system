"""The agent library: skilled agents plus the orchestrators that route them.

This package deliberately knows nothing about graphs. It exposes *what agents
exist*; how they are wired into a runnable pipeline is a workflow's job, and
those live under `app.graph_workflow`. That split is what lets several
workflows share one roster.

    app/agents/
        base.py            shared Agent / AgentSpec contract
        skilled_agents/    the agents that produce triage output
        support_agents/    infrastructure agents that prepare a run
        orchestrators/     the control agents that choose what runs next
"""

from app.agents.base import Agent, AgentSpec
from app.agents.orchestrators import (
    DONE,
    ORCHESTRATOR_CLASSES,
    ORCHESTRATORS,
    ChatOrchestrator,
    ReferralOrchestrator,
)
from app.agents.skilled_agents import WORKER_CLASSES
from app.agents.support_agents import SUPPORT_CLASSES

# Everything an orchestrator can dispatch to, support first — a run needs its
# session before any skilled agent can work.
DISPATCHABLE_CLASSES: tuple[type[Agent], ...] = (*SUPPORT_CLASSES, *WORKER_CLASSES)

# Every agent in the library, orchestrators included. This is an inventory,
# not a node list: a workflow builds its nodes from its own orchestrator plus
# `DISPATCHABLE_CLASSES`, so adding an orchestrator here does not add a node
# to an unrelated graph.
AGENT_CLASSES: tuple[type[Agent], ...] = (
    *ORCHESTRATOR_CLASSES,
    *DISPATCHABLE_CLASSES,
)
AGENTS: dict[str, type[Agent]] = {cls.spec.name: cls for cls in AGENT_CLASSES}

# What an orchestrator is allowed to return as `next_agent`.
ROUTABLE_AGENTS: frozenset[str] = frozenset(
    {cls.spec.name for cls in DISPATCHABLE_CLASSES} | {DONE}
)

__all__ = [
    "AGENTS",
    "AGENT_CLASSES",
    "DISPATCHABLE_CLASSES",
    "DONE",
    "ORCHESTRATORS",
    "ORCHESTRATOR_CLASSES",
    "ROUTABLE_AGENTS",
    "SUPPORT_CLASSES",
    "WORKER_CLASSES",
    "Agent",
    "AgentSpec",
    "ChatOrchestrator",
    "ReferralOrchestrator",
]
