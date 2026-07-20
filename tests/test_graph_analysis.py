from __future__ import annotations

import math
import time

import pytest

from llm_wiki_runtime.graph_models import GraphDiagnostic, GraphEdge, GraphNode


def _node(
    node_id: str,
    *,
    node_type: str = "record",
    label: str | None = None,
    metadata: dict[str, object] | None = None,
    tags: tuple[str, ...] = (),
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        subtype="profile",
        label=label or node_id,
        summary="private body text must never be searchable",
        status="active",
        tags=tags,
        path=f"domains/hr/{node_id}.md",
        metadata=metadata or {},
    )


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    edge_type: str = "REFERENCED",
    label: str = "reference",
    evidence: tuple[dict[str, str], ...] = (),
) -> GraphEdge:
    return GraphEdge(edge_id, source, target, edge_type, label, evidence)


def _analyze(*args, **kwargs):
    from llm_wiki_runtime.graph_analysis import analyze_domain_graph

    return analyze_domain_graph(*args, **kwargs)


def test_analysis_is_deterministic_for_reordered_iterators_and_preserves_inputs():
    nodes = (
        _node("a", metadata={"years": 7, "region": ("APAC", "US")}, tags=("Hiring", "Urgent")),
        _node("b", node_type="source"),
        _node("c"),
        _node("orphan"),
    )
    edges = (
        _edge("ab", "a", "b", evidence=({"path": "domains/hr/a.md", "method": "frontmatter"},)),
        _edge("bc", "b", "c"),
    )
    diagnostics = (GraphDiagnostic("warning", "input_warning", "", "Input warning"),)

    first = _analyze("hr", "Human Resources", iter(nodes), iter(edges), iter(diagnostics))
    second = _analyze("hr", "Human Resources", reversed(nodes), reversed(edges), reversed(diagnostics))

    assert first.to_dict() == second.to_dict()
    assert [node.x for node in nodes] == [0.0, 0.0, 0.0, 0.0]
    assert [edge.evidence for edge in edges] == [
        ({"path": "domains/hr/a.md", "method": "frontmatter"},),
        (),
    ]
    assert first.domain == {"id": "hr", "display_name": "Human Resources"}
    assert first.stats == {
        "node_count": 4,
        "edge_count": 2,
        "type_count": 2,
        "component_count": 2,
        "orphan_count": 1,
    }


def test_layout_separates_components_builds_search_text_and_rounds_coordinates():
    nodes = (
        _node("root"),
        _node("left"),
        _node("right"),
        _node("solo", node_type="source"),
    )
    edges = (_edge("root-left", "root", "left"), _edge("root-right", "root", "right"))

    result = _analyze("hr", "HR", nodes, edges, ())
    by_id = {node.id: node for node in result.nodes}

    assert result.stats["component_count"] == 2
    assert len({(node.x, node.y) for node in result.nodes}) == len(nodes)
    assert by_id["root"].x != by_id["left"].x or by_id["root"].y != by_id["left"].y
    assert "root record profile root active" in by_id["root"].search_text
    assert "private body text" not in by_id["root"].search_text
    assert all(node.search_text == node.search_text.lower() for node in result.nodes)
    assert all(math.isfinite(node.x) and math.isfinite(node.y) for node in result.nodes)
    assert all(node.x == round(node.x, 6) and node.y == round(node.y, 6) for node in result.nodes)


def test_search_text_uses_only_approved_fields_and_deterministic_metadata_values():
    node = _node(
        "candidate",
        label="Ada Lovelace",
        tags=("Python", "Platform"),
        metadata={"level": "Senior", "years": 8, "regions": ("US", None, True)},
    )

    result = _analyze("hr", "HR", (node,), (), ())

    assert result.nodes[0].search_text == (
        "candidate record profile ada lovelace active platform python senior us true 8"
    )


def test_empty_and_singleton_graphs_have_canonical_stats_and_coordinates():
    empty = _analyze("hr", "HR", (), (), ())
    singleton = _analyze("hr", "HR", (_node("only"),), (), ())

    assert empty.to_dict()["nodes"] == []
    assert empty.stats == {
        "node_count": 0,
        "edge_count": 0,
        "type_count": 0,
        "component_count": 0,
        "orphan_count": 0,
    }
    assert singleton.stats["component_count"] == 1
    assert singleton.stats["orphan_count"] == 1
    assert (singleton.nodes[0].x, singleton.nodes[0].y) == (0.0, 0.0)


def test_duplicate_edges_merge_sorted_unique_evidence_and_conflicts_are_diagnosed():
    nodes = (_node("a"), _node("b"), _node("c"))
    compatible = (
        _edge("same", "a", "b", evidence=({"method": "second", "path": "domains/hr/b.md"},)),
        _edge("same", "a", "b", evidence=({"method": "first", "path": "domains/hr/a.md"},)),
        _edge("same", "a", "b", evidence=({"method": "first", "path": "domains/hr/a.md"},)),
    )
    conflicting = (
        _edge("conflict", "a", "b"),
        _edge("conflict", "a", "c"),
    )

    result = _analyze("hr", "HR", nodes, (*compatible, *conflicting), ())

    assert [edge.id for edge in result.edges] == ["same"]
    assert result.edges[0].evidence == (
        {"method": "first", "path": "domains/hr/a.md"},
        {"method": "second", "path": "domains/hr/b.md"},
    )
    assert [item.code for item in result.diagnostics] == ["conflicting_duplicate_edge_id"]


def test_dangling_and_self_edges_are_handled_without_nonfinite_layout_values():
    nodes = (_node("a"), _node("b"))
    edges = (
        _edge("self", "a", "a"),
        _edge("missing-source", "missing", "a"),
        _edge("missing-target", "a", "missing"),
    )

    result = _analyze("hr", "HR", nodes, edges, ())

    assert [edge.id for edge in result.edges] == ["self"]
    assert result.stats["edge_count"] == 1
    assert result.stats["orphan_count"] == 1
    assert [item.code for item in result.diagnostics] == ["dangling_edge", "self_edge"]
    assert all(math.isfinite(node.x) and math.isfinite(node.y) for node in result.nodes)


@pytest.mark.parametrize("count, warning_expected", [(10_000, False), (10_001, True)])
def test_graph_size_warning_has_an_exact_boundary(count, warning_expected):
    nodes = (_node(f"n-{index}") for index in range(count))

    result = _analyze("hr", "HR", nodes, (), ())

    assert ("graph_size_warning" in {item.code for item in result.diagnostics}) is warning_expected


def test_analysis_handles_ten_thousand_nodes_and_thirty_thousand_edges_without_truncation():
    node_count = 10_000
    nodes = tuple(_node(f"n-{index}") for index in range(node_count))
    edges = tuple(
        _edge(
            f"edge-{index}",
            f"n-{index % node_count}",
            f"n-{(index * 7 + 1) % node_count}",
            evidence=({"method": "generated", "path": "domains/hr/fixture.md"},),
        )
        for index in range(30_000)
    )

    started = time.perf_counter()
    result = _analyze("hr", "HR", nodes, edges, ())
    elapsed = time.perf_counter() - started
    print(f"analysis scale fixture: {elapsed:.3f}s")

    assert len(result.nodes) == node_count
    assert len(result.edges) == 30_000
    assert result.stats["node_count"] == node_count
    assert result.stats["edge_count"] == 30_000
    assert all(math.isfinite(node.x) and math.isfinite(node.y) for node in result.nodes)
