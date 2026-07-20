from dataclasses import FrozenInstanceError

import pytest

from llm_wiki_runtime.graph_models import (
    DomainGraph,
    GraphDiagnostic,
    GraphEdge,
    GraphNode,
    normalize_scope_path,
    stable_edge_id,
    stable_node_id,
)


def _node(node_id: str, *, tags: tuple[str, ...] = ()) -> GraphNode:
    return GraphNode(
        id=node_id,
        type="domain",
        subtype="team",
        label=node_id,
        summary="summary",
        status="active",
        tags=tags,
        path=f"domains/{node_id}.md",
        metadata={"z": True, "a": ["later", 1, None]},
    )


def test_graph_contracts_are_frozen():
    node = _node("hr")
    edge = GraphEdge("edge", "hr", "ops", "depends_on", "depends", ())
    diagnostic = GraphDiagnostic("warning", "missing", "domains/hr.md", "Missing owner")

    with pytest.raises(FrozenInstanceError):
        node.label = "People"
    with pytest.raises(FrozenInstanceError):
        edge.label = "Depends on"
    with pytest.raises(FrozenInstanceError):
        diagnostic.message = "Changed"


def test_stable_ids_use_readable_prefix_and_canonical_inputs():
    assert stable_node_id("domain", "domains/hr.md") == stable_node_id("domain", "domains/hr.md")
    assert stable_node_id("domain", "domains/hr.md").startswith("node_")
    assert len(stable_node_id("domain", "domains/hr.md")) == 21

    assert stable_edge_id("hr", "ops", "depends_on") == stable_edge_id("hr", "ops", "depends_on")
    assert stable_edge_id("hr", "ops", "depends_on").startswith("edge_")
    assert len(stable_edge_id("hr", "ops", "depends_on")) == 21
    assert stable_edge_id("hr", "ops", "depends_on") != stable_edge_id("ops", "hr", "depends_on")


def test_domain_graph_to_dict_is_deterministically_sorted():
    graph = DomainGraph(
        nodes=(_node("ops", tags=("z", "a")), _node("hr", tags=("b", "a"))),
        edges=(
            GraphEdge("edge_z", "ops", "hr", "owns", "owns", (), {"z": "last", "a": "first"}),
            GraphEdge("edge_a", "hr", "ops", "uses", "uses", (), {"b": 2, "a": 1}),
        ),
        diagnostics=(
            GraphDiagnostic("warning", "z", "domains/z.md", "z message"),
            GraphDiagnostic("error", "a", "domains/a.md", "a message"),
        ),
    )

    assert graph.to_dict() == {
        "nodes": [
            {
                "id": "hr",
                "type": "domain",
                "subtype": "team",
                "label": "hr",
                "summary": "summary",
                "status": "active",
                "tags": ["a", "b"],
                "path": "domains/hr.md",
                "metadata": {"a": ["later", 1, None], "z": True},
                "x": 0.0,
                "y": 0.0,
                "search_text": "",
            },
            {
                "id": "ops",
                "type": "domain",
                "subtype": "team",
                "label": "ops",
                "summary": "summary",
                "status": "active",
                "tags": ["a", "z"],
                "path": "domains/ops.md",
                "metadata": {"a": ["later", 1, None], "z": True},
                "x": 0.0,
                "y": 0.0,
                "search_text": "",
            },
        ],
        "edges": [
            {
                "id": "edge_a",
                "source": "hr",
                "target": "ops",
                "type": "uses",
                "label": "uses",
                "evidence": [],
                "metadata": {"a": 1, "b": 2},
            },
            {
                "id": "edge_z",
                "source": "ops",
                "target": "hr",
                "type": "owns",
                "label": "owns",
                "evidence": [],
                "metadata": {"a": "first", "z": "last"},
            },
        ],
        "diagnostics": [
            {"severity": "error", "code": "a", "path": "domains/a.md", "message": "a message"},
            {"severity": "warning", "code": "z", "path": "domains/z.md", "message": "z message"},
        ],
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("domains/hr/profile.md", "domains/hr/profile.md"),
        ("domains\\hr\\profile.md", "domains/hr/profile.md"),
        ("domains/hr\\profile.md", "domains/hr/profile.md"),
    ],
)
def test_normalize_scope_path_returns_posix_relative_paths(value, expected):
    assert normalize_scope_path(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "../secret.md",
        "domains/../secret.md",
        "domains/hr/../secret.md",
        "/etc/passwd",
        "C:\\secret.md",
        "C:secret.md",
        "\\\\server\\share\\secret.md",
    ],
)
def test_normalize_scope_path_rejects_unsafe_paths(value):
    with pytest.raises(ValueError):
        normalize_scope_path(value)
