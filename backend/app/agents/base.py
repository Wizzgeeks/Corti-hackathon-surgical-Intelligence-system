"""Shared contract every agent in the roster follows.

Deliberately free of any workflow import: the base contract cannot depend on
one workflow's state, or the same agent could not be reused by another.
`AgentState` is the loose view — each workflow defines a concrete `TypedDict`
(e.g. `TriageState`) and individual agents annotate against that.
"""

from dataclasses import dataclass
from typing import Any

AgentState = dict[str, Any]


@dataclass(frozen=True)
class AgentSpec:
    """Declarative description of an agent — no behaviour, just identity."""

    name: str  # graph node name
    title: str  # human-readable
    purpose: str  # what it is responsible for
    consumes: tuple[str, ...]  # state keys it reads
    produces: tuple[str, ...]  # state keys it writes


class Agent:
    """Base class for roster agents.

    Subclasses declare a `spec` and implement `run()`. `run()` takes the graph
    state and returns a **partial** state update, so an agent plugs straight
    into the graph as a node.
    """

    spec: AgentSpec

    async def run(self, state: AgentState) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.run is not implemented yet")

    def __call__(self, state: AgentState):
        return self.run(state)
