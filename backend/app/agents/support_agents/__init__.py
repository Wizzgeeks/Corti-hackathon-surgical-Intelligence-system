"""Support agents — infrastructure, not clinical work.

These prepare a run rather than contributing to the triage output: sessions,
credentials, and anything else a skilled agent needs in place before it can
do its job. Kept apart from `skilled_agents` so the clinical roster stays
readable as it grows.
"""

from app.agents.base import Agent
from app.agents.support_agents.corti_authenticator import CortiAuthenticator

SUPPORT_CLASSES: tuple[type[Agent], ...] = (CortiAuthenticator,)

__all__ = [
    "SUPPORT_CLASSES",
    "CortiAuthenticator",
]
