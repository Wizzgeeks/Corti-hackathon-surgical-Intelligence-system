"""Workflows — how agents are wired into runnable graphs.

Each subpackage is one self-contained workflow holding its own state, nodes,
edges and graph, composed from the shared roster in `app.agents`:

    app/graph_workflow/
        chat_orchestration/   orchestrator-driven referral triage
        referral_intake/      fixed-sequence referral intake pipeline

Add a workflow by adding a package here, not by changing `app.agents`.
"""
