"""Renders a workflow graph to `graph.mmd` and `graph.png`.

Each diagram is written into its own workflow package, next to the code it
describes:

    app/graph_workflow/<workflow>/graph.mmd
    app/graph_workflow/<workflow>/graph.png

Run from anywhere with the backend venv active:

    python scripts/draw_graph.py                          # chat_orchestration
    python scripts/draw_graph.py referral_intake
    python scripts/draw_graph.py --all
    python scripts/draw_graph.py referral_intake --out-dir docs --local

The Mermaid source is written first and always: it needs no network and no
extra dependency, so a PNG failure still leaves you something to look at.

PNG rendering goes through the hosted mermaid.ink service by default, which
means the node and edge names leave the machine. Pass `--local` to render with
a bundled browser instead (requires `pyppeteer`).
"""

import argparse
import importlib
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Workflow name -> module holding its `get_graph()`.
WORKFLOWS = {
    "chat_orchestration": "app.graph_workflow.chat_orchestration.graph",
    "referral_intake": "app.graph_workflow.referral_intake.graph",
}
DEFAULT_WORKFLOW = "chat_orchestration"

WORKFLOW_ROOT = BACKEND_ROOT / "app" / "graph_workflow"


def workflow_dir(workflow: str) -> Path:
    """The package directory the diagram belongs beside."""
    return WORKFLOW_ROOT / workflow


def load_graph(workflow: str):
    """Import the named workflow and return its compiled graph."""
    module = importlib.import_module(WORKFLOWS[workflow])
    return module.get_graph().get_graph()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workflow",
        nargs="?",
        default=DEFAULT_WORKFLOW,
        choices=sorted(WORKFLOWS),
        help=f"workflow to render (default: {DEFAULT_WORKFLOW})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="render every workflow instead of just one",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "override the output directory (default: the workflow's own "
            "package under app/graph_workflow/)"
        ),
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="render the PNG locally via pyppeteer instead of mermaid.ink",
    )
    return parser.parse_args()


def render(workflow: str, out_dir: Path | None, local: bool) -> int:
    """Write `graph.mmd` (always) and `graph.png` (best effort).

    Defaults to the workflow's own package; `out_dir` overrides it.
    """
    target = out_dir or workflow_dir(workflow)
    target.mkdir(parents=True, exist_ok=True)
    drawable = load_graph(workflow)

    mmd_path = target / "graph.mmd"
    mmd_path.write_text(drawable.draw_mermaid(), encoding="utf-8")
    print(f"wrote {mmd_path.relative_to(BACKEND_ROOT)}")

    png_path = target / "graph.png"
    try:
        if local:
            from langchain_core.runnables.graph import MermaidDrawMethod

            png = drawable.draw_mermaid_png(
                draw_method=MermaidDrawMethod.PYPPETEER
            )
        else:
            png = drawable.draw_mermaid_png()
    except Exception as exc:  # network, rate limit, or missing pyppeteer
        print(f"could not render {png_path}: {exc}", file=sys.stderr)
        print(
            "the Mermaid source is still available — paste it into "
            "https://mermaid.live, or retry with --local",
            file=sys.stderr,
        )
        return 1

    png_path.write_bytes(png)
    print(f"wrote {png_path.relative_to(BACKEND_ROOT)}")
    return 0


def main() -> int:
    args = parse_args()
    out_dir: Path | None = args.out_dir

    workflows = sorted(WORKFLOWS) if args.all else [args.workflow]
    return max(render(w, out_dir, args.local) for w in workflows)


if __name__ == "__main__":
    raise SystemExit(main())
