"""Create direct file:// graph pages for the offline browser smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from llm_wiki_runtime.graph_models import DomainGraph, GraphEdge, GraphNode
from llm_wiki_runtime.graph_render import render_domain_html, render_index_html


def main(output_root: Path) -> None:
    graph = DomainGraph(
        domain={"display_name": "Human Resources", "id": "hr"},
        stats={"edges": 3, "nodes": 4},
        nodes=(
            _node(
                "candidate-a",
                "record",
                "Alice",
                -1.0,
                0.0,
                metadata={"age": "30", "education_level": "bachelors", "years_experience": "7"},
            ),
            _node("role-b", "record", "Platform Engineer", 1.0, 0.0),
            _node("brief-c", "document", "Hiring brief", 0.0, 1.0),
            _node("source-d", "source", "Candidate notes", 0.0, -1.0),
        ),
        edges=(
            _edge("a-b", "candidate-a", "role-b"),
            _edge("b-c", "role-b", "brief-c"),
            _edge("a-d", "candidate-a", "source-d"),
        ),
    )
    domain_dir = output_root / "hr"
    domain_dir.mkdir(parents=True, exist_ok=True)
    (output_root / "index.html").write_text(
        render_index_html(
            {
                "domains": [
                    {
                        "counts": {"edges": 3, "nodes": 4},
                        "display_name": "Human Resources",
                        "id": "hr",
                        "status": "ok",
                    }
                ],
                "title": "Domain graphs",
            }
        ),
        encoding="utf-8",
    )
    (domain_dir / "graph.html").write_text(render_domain_html(graph.to_dict()), encoding="utf-8")


def _node(
    node_id: str,
    node_type: str,
    label: str,
    x: float,
    y: float,
    metadata: dict[str, str] | None = None,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        subtype=node_type,
        label=label,
        summary=f"Fixture {label}",
        status="active",
        tags=("fixture",),
        path=f"domains/hr/{node_id}.md",
        metadata=metadata or {},
        x=x,
        y=y,
        search_text=f"{label} {node_type}".lower(),
    )


def _edge(edge_id: str, source: str, target: str) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        source=source,
        target=target,
        type="reference",
        label="reference",
        evidence=({"path": f"domains/hr/{source}.md"},),
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_fixture.py OUTPUT_DIRECTORY")
    main(Path(sys.argv[1]).resolve())
