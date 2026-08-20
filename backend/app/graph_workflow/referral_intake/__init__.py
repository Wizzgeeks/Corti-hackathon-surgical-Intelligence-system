"""Referral intake workflow — a fixed, sequenced triage pipeline.

    state.py   the state that flows through this graph
    nodes.py   agents wrapped as graph nodes, in `SEQUENCE` order
    edges.py   the straight-line wiring plus failure / re-auth routing
    graph.py   assembly and entry point

Unlike `chat_orchestration`, no orchestrator decides what runs next — the
order is declared in `nodes.SEQUENCE`.

Nothing is re-exported here on purpose; import the module you need:

    from app.graph_workflow.referral_intake.graph import run_intake
    from app.graph_workflow.referral_intake.state import IntakeState
"""
