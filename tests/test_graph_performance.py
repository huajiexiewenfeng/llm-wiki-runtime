import time

import pytest

from llm_wiki_runtime.graph_analysis import analyze_domain_graph
from llm_wiki_runtime.graph_models import GraphEdge, GraphNode
from llm_wiki_runtime.graph_render import render_domain_html


def _fixture(node_count: int):
    started = time.perf_counter()
    nodes = tuple(
        GraphNode(
            id=f"n-{index:05d}",
            type="record",
            subtype="fixture",
            label=f"Node {index}",
            summary="Performance fixture",
            status="active",
            tags=("fixture",),
            path=f"domains/hr/records/n-{index:05d}.md",
            search_text=f"node {index} fixture",
        )
        for index in range(node_count)
    )
    edges = tuple(
        GraphEdge(
            id=f"e-{index:05d}-{offset}",
            source=f"n-{index:05d}",
            target=f"n-{(index + offset + 1) % node_count:05d}",
            type="LINKED",
            label="fixture",
            evidence=({"method": "fixture", "path": f"domains/hr/records/n-{index:05d}.md"},),
        )
        for index in range(node_count)
        for offset in range(3)
    )
    return nodes, edges, time.perf_counter() - started


@pytest.mark.parametrize("node_count", [1_000, 5_000])
def test_graph_pipeline_scale_budgets(node_count):
    _assert_pipeline_budget(node_count)


@pytest.mark.performance
def test_graph_pipeline_ten_thousand_nodes_thirty_thousand_edges():
    _assert_pipeline_budget(10_000)


def _assert_pipeline_budget(node_count: int):
    nodes, edges, collection_seconds = _fixture(node_count)
    analysis_started = time.perf_counter()
    graph = analyze_domain_graph("hr", "Human Resources", nodes, edges, ())
    analysis_seconds = time.perf_counter() - analysis_started
    render_started = time.perf_counter()
    page = render_domain_html(graph.to_dict())
    render_seconds = time.perf_counter() - render_started
    print(
        f"graph scale nodes={node_count} edges={len(edges)} "
        f"collection={collection_seconds:.3f}s analysis={analysis_seconds:.3f}s render={render_seconds:.3f}s"
    )
    assert len(graph.nodes) == node_count
    assert len(graph.edges) == node_count * 3
    assert f'"node_count":{node_count}' in page
    assert collection_seconds < 10
    assert analysis_seconds < 30
    assert render_seconds < 15
