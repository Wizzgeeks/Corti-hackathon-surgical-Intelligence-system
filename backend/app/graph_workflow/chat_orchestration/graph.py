"""Assembles the referral triage graph from the node and edge registries.

Adding a step to the pipeline means adding a node in `nodes.py` and its wiring
in `edges.py` — this file does not change.
"""

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph_workflow.chat_orchestration.edges import CONDITIONAL_EDGES, EDGES
from app.graph_workflow.chat_orchestration.nodes import ENTRY_NODE, NODES
from app.graph_workflow.chat_orchestration.state import TriageState, new_state


def build_graph() -> StateGraph:
    """Wire nodes and edges into an uncompiled graph."""
    builder = StateGraph(TriageState)

    for name, node in NODES.items():
        builder.add_node(name, node)

    builder.add_edge(START, ENTRY_NODE)

    for source, (router, mapping) in CONDITIONAL_EDGES.items():
        builder.add_conditional_edges(source, router, mapping)

    for source, destination in EDGES.items():
        builder.add_edge(source, destination)

    # Any node with no outgoing edge terminates the run.
    wired = set(EDGES) | set(CONDITIONAL_EDGES)
    for name in NODES:
        if name not in wired:
            builder.add_edge(name, END)

    return builder


@lru_cache
def get_graph():
    """Compiled graph, built once per process."""
    return build_graph().compile()


async def run_graph(
    referral_id: str,
    referral_text: str = "",
    document_path: str | None = None,
) -> TriageState:
    """Run the pipeline end to end.

    Supply `document_path` for a PDF referral; the document reader extracts it
    into `referral_transcription`.
    """
    return await get_graph().ainvoke(
        new_state(referral_id, referral_text, document_path)
    )
