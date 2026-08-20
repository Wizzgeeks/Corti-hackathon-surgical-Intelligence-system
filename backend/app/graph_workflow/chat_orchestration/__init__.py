"""Chat orchestration workflow — orchestrator-driven referral triage.

    state.py   the state that flows through this graph
    nodes.py   agents wrapped as graph nodes
    edges.py   how control moves between them
    graph.py   assembly and entry point

Nothing is re-exported here on purpose. Agents annotate against this
workflow's `state`, so importing the package must not drag in `graph` — that
would close the loop back through `app.agents` and fail as a circular import.
Import the module you need:

    from app.graph_workflow.chat_orchestration.graph import run_graph
    from app.graph_workflow.chat_orchestration.state import TriageState
"""
