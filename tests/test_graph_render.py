import json

import pytest

from llm_wiki_runtime.graph_models import DomainGraph, GraphEdge, GraphNode
from llm_wiki_runtime.graph_render import (
    assert_self_contained_html,
    render_domain_html,
    render_index_html,
)


def _sample_graph() -> DomainGraph:
    return DomainGraph(
        domain={"display_name": "Human Resources", "id": "hr"},
        stats={"edges": 1, "nodes": 2},
        nodes=(
            GraphNode(
                id="candidate-a",
                type="record",
                subtype="candidate",
                label="Alice",
                summary="A concise candidate record.",
                status="active",
                tags=("engineering",),
                path="domains/hr/candidates/alice.md",
                x=-1,
                y=0,
                search_text="alice candidate engineering",
            ),
            GraphNode(
                id="role-b",
                type="record",
                subtype="role",
                label="Platform Engineer",
                summary="An open role.",
                status="open",
                tags=("engineering",),
                path="domains/hr/roles/platform.md",
                x=1,
                y=0,
                search_text="platform engineer role",
            ),
        ),
        edges=(
            GraphEdge(
                id="candidate-role",
                source="candidate-a",
                target="role-b",
                type="matches",
                label="matches",
                evidence=({"path": "domains/hr/candidates/alice.md"},),
            ),
        ),
    )


def test_domain_html_embeds_canonical_escaped_data_and_no_external_resources():
    payload = _sample_graph().to_dict()
    payload["domain"]["display_name"] = "</script><script>alert(1)</script>&\u2028\u2029"

    html = render_domain_html(payload)

    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html
    assert "\\u0026" in html
    assert "\\u2028" in html
    assert "\\u2029" in html
    assert 'id="graph-data" type="application/json"' in html
    embedded = html.split('<script id="graph-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert json.loads(embedded) == payload
    assert "fetch(" not in html
    assert "https://" not in html
    assert_self_contained_html(html)


def test_index_html_contains_relative_domain_navigation_and_embedded_manifest():
    manifest = {
        "domains": [
            {
                "counts": {"edges": 1, "nodes": 2},
                "display_name": "Human Resources",
                "id": "hr",
                "status": "ok",
            }
        ],
        "title": "Domain graphs",
    }

    html = render_index_html(manifest)

    assert "hr/graph.html" in html
    assert "file://" not in html
    assert 'id="graph-index-data" type="application/json"' in html
    assert_self_contained_html(html)


@pytest.mark.parametrize(
    "html",
    [
        '<script src="graph.js"></script>',
        '<link rel="stylesheet" href="graph.css">',
        '<script>fetch("/graph.json")</script>',
        '<script>new XMLHttpRequest()</script>',
        '<script>new WebSocket("ws://example.test")</script>',
        '<script>import("graph.js")</script>',
        '<a href="https://example.test">external</a>',
        '<img src="//example.test/image.png">',
    ],
)
def test_self_contained_html_rejects_external_resources_and_runtime_apis(html):
    with pytest.raises(ValueError):
        assert_self_contained_html(html)


def test_self_contained_html_allows_graphology_import_method_name():
    assert_self_contained_html("<script>graph.import({nodes: []});</script>")


def test_domain_html_drops_unrecognized_body_fields():
    payload = _sample_graph().to_dict()
    payload["nodes"][0]["body"] = "This source body must never enter the graph page."

    html = render_domain_html(payload)

    assert "This source body must never enter the graph page." not in html
