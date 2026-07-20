"""Deterministic analysis and layout for a single Domain graph."""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping

from .graph_models import DomainGraph, GraphDiagnostic, GraphEdge, GraphNode
from .paths import validate_slug


_RING_GAP = 120.0
_NODE_MARGIN = 40.0
_COMPONENT_GAP = 80.0


def analyze_domain_graph(
    domain_id: str,
    display_name: str,
    nodes: Iterable[GraphNode],
    edges: Iterable[GraphEdge],
    diagnostics: Iterable[GraphDiagnostic],
) -> DomainGraph:
    """Return a canonical, laid-out DomainGraph without modifying the inputs."""
    domain_id = validate_slug(domain_id)
    if not isinstance(display_name, str) or not display_name:
        raise ValueError("display name must be a non-empty string")

    analysis_diagnostics = list(diagnostics)
    nodes_by_id = _canonical_nodes(nodes, analysis_diagnostics)
    visible_edges = _canonical_visible_edges(edges, nodes_by_id, analysis_diagnostics)
    adjacency = _build_adjacency(nodes_by_id, visible_edges)
    components = _components(nodes_by_id, adjacency)
    coordinates = _layout_components(components, adjacency)

    analyzed_nodes = tuple(
        _with_analysis(node, coordinates[node_id])
        for node_id, node in sorted(nodes_by_id.items())
    )
    graph_diagnostics = tuple(sorted(set(analysis_diagnostics), key=_diagnostic_key))
    stats = {
        "node_count": len(analyzed_nodes),
        "edge_count": len(visible_edges),
        "type_count": len({node.type for node in analyzed_nodes}),
        "component_count": len(components),
        "orphan_count": sum(1 for node_id in nodes_by_id if not adjacency[node_id]),
    }
    if len(analyzed_nodes) > 10_000:
        graph_diagnostics = tuple(
            sorted(
                set(
                    (*graph_diagnostics, GraphDiagnostic("warning", "graph_size_warning", "", "Graph exceeds 10,000 nodes"))
                ),
                key=_diagnostic_key,
            )
        )

    return DomainGraph(
        nodes=analyzed_nodes,
        edges=tuple(sorted(visible_edges, key=lambda edge: edge.id)),
        diagnostics=graph_diagnostics,
        domain={"id": domain_id, "display_name": display_name},
        stats=stats,
    )


def _canonical_nodes(nodes: Iterable[GraphNode], diagnostics: list[GraphDiagnostic]) -> dict[str, GraphNode]:
    grouped: dict[str, list[GraphNode]] = defaultdict(list)
    for node in nodes:
        grouped[node.id].append(node)

    result: dict[str, GraphNode] = {}
    for node_id in sorted(grouped):
        candidates = grouped[node_id]
        candidate_keys = {_node_key(candidate) for candidate in candidates}
        if len(candidate_keys) > 1:
            diagnostics.append(
                GraphDiagnostic("warning", "conflicting_duplicate_node_id", "", "Duplicate node ID has incompatible fields")
            )
        result[node_id] = min(candidates, key=_node_key)
    return result


def _canonical_visible_edges(
    edges: Iterable[GraphEdge],
    nodes_by_id: Mapping[str, GraphNode],
    diagnostics: list[GraphDiagnostic],
) -> tuple[GraphEdge, ...]:
    grouped: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in edges:
        grouped[edge.id].append(edge)

    visible: list[GraphEdge] = []
    for edge_id in sorted(grouped):
        candidates = grouped[edge_id]
        endpoints = {(edge.source, edge.target, edge.type) for edge in candidates}
        if len(endpoints) != 1:
            diagnostics.append(
                GraphDiagnostic(
                    "warning",
                    "conflicting_duplicate_edge_id",
                    "",
                    "Duplicate edge ID has incompatible endpoints or type",
                )
            )
            continue

        canonical = min(candidates, key=_edge_key)
        if canonical.source not in nodes_by_id or canonical.target not in nodes_by_id:
            diagnostics.append(
                GraphDiagnostic("warning", "dangling_edge", "", "Edge endpoint is not present in the graph")
            )
            continue
        if canonical.source == canonical.target:
            diagnostics.append(GraphDiagnostic("warning", "self_edge", "", "Self edge is retained for graph fidelity"))

        evidence = _merged_evidence(candidates)
        visible.append(
            GraphEdge(
                id=canonical.id,
                source=canonical.source,
                target=canonical.target,
                type=canonical.type,
                label=canonical.label,
                evidence=evidence,
                metadata=canonical.metadata,
            )
        )
    return tuple(visible)


def _build_adjacency(
    nodes_by_id: Mapping[str, GraphNode], edges: Iterable[GraphEdge]
) -> dict[str, tuple[str, ...]]:
    neighbors: dict[str, list[str]] = {node_id: [] for node_id in nodes_by_id}
    for edge in edges:
        neighbors[edge.source].append(edge.target)
        if edge.source != edge.target:
            neighbors[edge.target].append(edge.source)
    return {node_id: tuple(sorted(set(values))) for node_id, values in neighbors.items()}


def _components(
    nodes_by_id: Mapping[str, GraphNode], adjacency: Mapping[str, tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    visited: set[str] = set()
    components: list[tuple[str, ...]] = []
    for start in sorted(nodes_by_id):
        if start in visited:
            continue
        queue = deque((start,))
        visited.add(start)
        component: list[str] = []
        while queue:
            node_id = queue.popleft()
            component.append(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(tuple(sorted(component)))
    return tuple(sorted(components, key=lambda component: (-len(component), component[0])))


def _layout_components(
    components: tuple[tuple[str, ...], ...], adjacency: Mapping[str, tuple[str, ...]]
) -> dict[str, tuple[float, float]]:
    layouts = [_component_layout(component, adjacency) for component in components]
    if not layouts:
        return {}

    total_area = sum(math.pi * layout.radius * layout.radius for layout in layouts)
    target_width = max(2.0 * max(layout.radius for layout in layouts), math.sqrt(total_area))
    centers: list[tuple[float, float]] = []
    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0
    for layout in layouts:
        diameter = 2.0 * layout.radius
        if cursor_x and cursor_x + diameter > target_width:
            cursor_x = 0.0
            cursor_y += row_height + _COMPONENT_GAP
            row_height = 0.0
        centers.append((cursor_x + layout.radius, cursor_y + layout.radius))
        cursor_x += diameter + _COMPONENT_GAP
        row_height = max(row_height, diameter)

    origin_x, origin_y = centers[0]
    coordinates: dict[str, tuple[float, float]] = {}
    for layout, (center_x, center_y) in zip(layouts, centers):
        for node_id, (local_x, local_y) in layout.local_coordinates.items():
            coordinates[node_id] = (
                _round_coordinate(center_x - origin_x + local_x),
                _round_coordinate(center_y - origin_y + local_y),
            )
    return coordinates


class _ComponentLayout:
    __slots__ = ("local_coordinates", "radius")

    def __init__(self, local_coordinates: dict[str, tuple[float, float]], radius: float) -> None:
        self.local_coordinates = local_coordinates
        self.radius = radius


def _component_layout(component: tuple[str, ...], adjacency: Mapping[str, tuple[str, ...]]) -> _ComponentLayout:
    root = min(component, key=lambda node_id: (-len(adjacency[node_id]), node_id))
    depths = _bfs_depths(root, adjacency)
    layers: dict[int, list[str]] = defaultdict(list)
    for node_id in component:
        layers[depths[node_id]].append(node_id)

    local_coordinates: dict[str, tuple[float, float]] = {}
    for depth in sorted(layers):
        layer = sorted(layers[depth])
        if depth == 0:
            local_coordinates[layer[0]] = (0.0, 0.0)
            continue
        radius = depth * _RING_GAP
        for index, node_id in enumerate(layer):
            angle = 2.0 * math.pi * index / len(layer)
            local_coordinates[node_id] = (radius * math.cos(angle), radius * math.sin(angle))
    max_depth = max(layers)
    return _ComponentLayout(local_coordinates, max(_NODE_MARGIN, max_depth * _RING_GAP + _NODE_MARGIN))


def _bfs_depths(root: str, adjacency: Mapping[str, tuple[str, ...]]) -> dict[str, int]:
    depths = {root: 0}
    queue = deque((root,))
    while queue:
        node_id = queue.popleft()
        for neighbor in adjacency[node_id]:
            if neighbor not in depths:
                depths[neighbor] = depths[node_id] + 1
                queue.append(neighbor)
    return depths


def _with_analysis(node: GraphNode, coordinate: tuple[float, float]) -> GraphNode:
    return GraphNode(
        id=node.id,
        type=node.type,
        subtype=node.subtype,
        label=node.label,
        summary=node.summary,
        status=node.status,
        tags=node.tags,
        path=node.path,
        metadata=node.metadata,
        x=coordinate[0],
        y=coordinate[1],
        search_text=_search_text(node),
    )


def _search_text(node: GraphNode) -> str:
    values: list[object] = [node.id, node.type, node.subtype, node.label, node.status]
    values.extend(sorted(node.tags))
    for key in sorted(node.metadata):
        value = node.metadata[key]
        values.extend(value if isinstance(value, tuple) else (value,))
    return " ".join(_search_value(value) for value in values if value is not None).lower()


def _search_value(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _merged_evidence(edges: Iterable[GraphEdge]) -> tuple[dict[str, str], ...]:
    entries = {
        tuple(sorted(evidence.items()))
        for edge in edges
        for evidence in edge.evidence
    }
    return tuple(dict(entry) for entry in sorted(entries))


def _node_key(node: GraphNode) -> str:
    return json.dumps(node.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _edge_key(edge: GraphEdge) -> str:
    return json.dumps(edge.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _diagnostic_key(item: GraphDiagnostic) -> tuple[str, str, str, str]:
    return (item.severity, item.code, item.path, item.message)


def _round_coordinate(value: float) -> float:
    rounded = round(value, 6)
    return 0.0 if rounded == 0 else rounded
