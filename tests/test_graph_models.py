from dataclasses import FrozenInstanceError
from types import MappingProxyType

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


@pytest.mark.parametrize(
    "coordinate",
    [True, False, float("nan"), float("inf"), float("-inf"), "1.5", None, object()],
)
@pytest.mark.parametrize("field", ["x", "y"])
def test_graph_node_rejects_non_finite_or_non_numeric_coordinates(field, coordinate):
    with pytest.raises(ValueError):
        GraphNode(
            id="hr",
            type="domain",
            subtype="team",
            label="hr",
            summary="summary",
            status="active",
            tags=(),
            path="domains/hr.md",
            **{field: coordinate},
        )


@pytest.mark.parametrize(("x", "y"), [(3, -2), (1.5, -2.75)])
def test_graph_node_serializes_finite_integer_and_float_coordinates(x, y):
    node = GraphNode(
        id="hr",
        type="domain",
        subtype="team",
        label="hr",
        summary="summary",
        status="active",
        tags=(),
        path="domains/hr.md",
        x=x,
        y=y,
    )

    assert node.to_dict()["x"] == x
    assert node.to_dict()["y"] == y


def test_graph_node_serialization_refuses_non_finite_coordinates():
    node = _node("hr")
    object.__setattr__(node, "x", float("nan"))

    with pytest.raises(ValueError):
        node.to_dict()


def test_graph_node_normalizes_its_scope_relative_path_at_construction():
    node = GraphNode(
        id="hr",
        type="domain",
        subtype="team",
        label="hr",
        summary="summary",
        status="active",
        tags=(),
        path="domains\\hr\\profile.md",
    )

    assert node.path == "domains/hr/profile.md"
    assert node.to_dict()["path"] == "domains/hr/profile.md"


@pytest.mark.parametrize("path", ["/etc/passwd", "C:\\secret.md", "domains/../secret.md"])
def test_graph_node_rejects_unsafe_scope_relative_paths(path):
    with pytest.raises(ValueError):
        GraphNode(
            id="hr",
            type="domain",
            subtype="team",
            label="hr",
            summary="summary",
            status="active",
            tags=(),
            path=path,
        )


def test_graph_node_serialization_refuses_mutated_unsafe_path():
    node = _node("hr")
    object.__setattr__(node, "path", "C:\\secret.md")

    with pytest.raises(ValueError):
        node.to_dict()


def test_graph_diagnostic_normalizes_non_empty_path_and_allows_empty_scope_path():
    diagnostic = GraphDiagnostic("warning", "missing", "domains\\hr\\profile.md", "Missing owner")
    scope_diagnostic = GraphDiagnostic("warning", "missing", "", "Missing domain metadata")

    assert diagnostic.path == "domains/hr/profile.md"
    assert diagnostic.to_dict()["path"] == "domains/hr/profile.md"
    assert scope_diagnostic.to_dict()["path"] == ""


@pytest.mark.parametrize("path", ["/etc/passwd", "C:\\secret.md", "domains/../secret.md"])
def test_graph_diagnostic_rejects_unsafe_non_empty_paths(path):
    with pytest.raises(ValueError):
        GraphDiagnostic("warning", "missing", path, "Missing owner")


def test_graph_diagnostic_serialization_refuses_mutated_unsafe_path():
    diagnostic = GraphDiagnostic("warning", "missing", "domains/hr.md", "Missing owner")
    object.__setattr__(diagnostic, "path", "../secret.md")

    with pytest.raises(ValueError):
        diagnostic.to_dict()


def test_graph_edge_normalizes_evidence_path_without_changing_other_strings():
    edge = GraphEdge(
        "edge",
        "hr",
        "ops",
        "depends_on",
        "depends",
        ({"path": "domains\\hr\\profile.md", "reference": "C:\\literal"},),
    )

    assert edge.evidence[0] == {"path": "domains/hr/profile.md", "reference": "C:\\literal"}
    assert edge.to_dict()["evidence"] == [{"path": "domains/hr/profile.md", "reference": "C:\\literal"}]


@pytest.mark.parametrize("path", ["/etc/passwd", "C:\\secret.md", "domains/../secret.md"])
def test_graph_edge_rejects_unsafe_evidence_paths(path):
    with pytest.raises(ValueError):
        GraphEdge("edge", "hr", "ops", "depends_on", "depends", ({"path": path},))


def test_graph_edge_serialization_refuses_mutated_unsafe_evidence_path():
    edge = GraphEdge("edge", "hr", "ops", "depends_on", "depends", ({"path": "domains/hr.md"},))
    object.__setattr__(edge, "evidence", ({"path": "../secret.md"},))

    with pytest.raises(ValueError):
        edge.to_dict()


def test_graph_contracts_deeply_freeze_caller_owned_collections():
    metadata = {"labels": ["internal"]}
    evidence = {"method": "wikilink", "path": "domains/hr/a.md"}
    node = _node("hr")
    node = GraphNode(**{**node.__dict__, "metadata": metadata})
    edge = GraphEdge("edge", "hr", "ops", "depends_on", "depends", (evidence,), metadata)

    metadata["labels"].append("changed")
    metadata["new"] = "changed"
    evidence["method"] = "changed"

    assert node.metadata == {"labels": ("internal",)}
    assert edge.metadata == {"labels": ("internal",)}
    assert edge.evidence == ({"method": "wikilink", "path": "domains/hr/a.md"},)
    assert isinstance(node.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        node.metadata["new"] = "value"
    with pytest.raises(AttributeError):
        node.metadata["labels"].append("value")
    with pytest.raises(TypeError):
        edge.evidence[0]["method"] = "changed"


def test_stable_node_id_uses_domain_type_and_path_with_record_prefix():
    first = stable_node_id("hr", "record", "domains/hr/a.md")

    assert first == stable_node_id("hr", "record", "domains\\hr\\a.md")
    assert first.startswith("record:")
    assert len(first) == len("record:") + 16
    assert first != stable_node_id("learning", "record", "domains/hr/a.md")
    assert first != stable_node_id("hr", "document", "domains/hr/a.md")


def test_stable_ids_use_collision_safe_framing():
    assert stable_edge_id("a\x1fb", "c", "d") != stable_edge_id("a", "b\x1fc", "d")
    assert stable_node_id("hr\x1frecord", "record", "domains/hr/a.md") != stable_node_id(
        "hr", "record\x1frecord", "domains/hr/a.md"
    )

    assert stable_edge_id("hr", "ops", "depends_on") == stable_edge_id("hr", "ops", "depends_on")
    assert stable_edge_id("hr", "ops", "depends_on").startswith("edge:")
    assert len(stable_edge_id("hr", "ops", "depends_on")) == len("edge:") + 16
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
        "schema_version": "v0.1",
        "domain": {},
        "stats": {},
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


def test_graph_serializers_canonicalize_nested_data_without_leaking_references():
    node = _node("hr", tags=("z", "a"))
    edge = GraphEdge(
        "edge",
        "hr",
        "ops",
        "depends_on",
        "depends",
        (
            {"z": "last", "a": "first"},
            {"path": "domains/hr/a.md", "method": "wikilink"},
        ),
        {"z": ["last"], "a": ["first"]},
    )
    graph = DomainGraph(
        nodes=(node,),
        edges=(edge,),
        domain={"z": "last", "a": "first"},
        stats={"z": 2, "a": 1},
    )

    assert node.to_dict()["metadata"] == {"a": ["later", 1, None], "z": True}
    assert edge.to_dict()["evidence"] == [
        {"a": "first", "z": "last"},
        {"method": "wikilink", "path": "domains/hr/a.md"},
    ]
    rendered = graph.to_dict()
    assert list(rendered) == ["schema_version", "domain", "stats", "nodes", "edges", "diagnostics"]
    assert rendered["domain"] == {"a": "first", "z": "last"}
    assert rendered["stats"] == {"a": 1, "z": 2}
    rendered["nodes"][0]["metadata"]["a"].append("changed")
    rendered["edges"][0]["evidence"][0]["a"] = "changed"
    assert node.to_dict()["metadata"] == {"a": ["later", 1, None], "z": True}
    assert edge.to_dict()["evidence"][0] == {"a": "first", "z": "last"}


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
