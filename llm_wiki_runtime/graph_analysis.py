"""Deterministic, linear-time analysis and layout for a single Domain graph."""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from typing import TypeVar

from .graph_models import DomainGraph, GraphDiagnostic, GraphEdge, GraphNode
from .paths import validate_slug


_RING_GAP = 120.0
_NODE_MARGIN = 40.0
_COMPONENT_GAP = 80.0
_BYTE_BUCKETS = 257
_T = TypeVar("_T")


class _EdgeCandidate:
    __slots__ = ("edge", "key", "evidence")

    def __init__(
        self,
        edge: GraphEdge,
        key: bytes,
        evidence: tuple[tuple[bytes, dict[str, str]], ...],
    ) -> None:
        self.edge = edge
        self.key = key
        self.evidence = evidence


def analyze_domain_graph(
    domain_id: str,
    display_name: str,
    nodes: Iterable[GraphNode],
    edges: Iterable[GraphEdge],
    diagnostics: Iterable[GraphDiagnostic],
) -> DomainGraph:
    """Return a canonical, laid-out DomainGraph without modifying the inputs.

    Analysis is O(N + E + B), where B is the total bounded UTF-8 byte length
    used for identity and evidence canonicalization. Stable byte-radix ranks
    replace comparison sorting; all adjacency, component, and layout work then
    uses linear traversals and rank-indexed buckets.
    """
    domain_id = validate_slug(domain_id)
    if not isinstance(display_name, str) or not (display_name := display_name.strip()):
        raise ValueError("display name must be a non-empty string")

    analysis_diagnostics = list(diagnostics)
    nodes_by_id, node_order = _canonical_nodes(nodes, analysis_diagnostics)
    node_rank = {node_id: rank for rank, node_id in enumerate(node_order)}
    visible_edges, edge_order = _canonical_visible_edges(edges, nodes_by_id, analysis_diagnostics)
    adjacency = _build_adjacency(node_order, visible_edges)
    components = _components(node_order, adjacency)
    coordinates = _layout_components(components, adjacency, node_rank)

    analyzed_nodes = tuple(_with_analysis(nodes_by_id[node_id], coordinates[node_id]) for node_id in node_order)
    if len(analyzed_nodes) > 10_000:
        analysis_diagnostics.append(
            GraphDiagnostic("warning", "graph_size_warning", "", "Graph exceeds 10,000 nodes")
        )

    stats = {
        "node_count": len(analyzed_nodes),
        "edge_count": len(visible_edges),
        "type_count": len({node.type for node in analyzed_nodes}),
        "component_count": len(components),
        "orphan_count": sum(1 for node_id in node_order if not adjacency[node_id]),
    }
    return DomainGraph(
        nodes=analyzed_nodes,
        edges=tuple(visible_edges[edge_rank] for edge_rank in range(len(edge_order))),
        diagnostics=_canonical_diagnostics(analysis_diagnostics),
        domain={"id": domain_id, "display_name": display_name},
        stats=stats,
    )


def _canonical_nodes(
    nodes: Iterable[GraphNode], diagnostics: list[GraphDiagnostic]
) -> tuple[dict[str, GraphNode], list[str]]:
    grouped: dict[str, list[GraphNode]] = defaultdict(list)
    for node in nodes:
        grouped[node.id].append(node)

    node_order = _utf8_radix_order(grouped)
    result: dict[str, GraphNode] = {}
    for node_id in node_order:
        candidates = [(key := _node_key_bytes(node), node) for node in grouped[node_id]]
        ordered_candidates = _stable_byte_radix_sort(candidates)
        if ordered_candidates[0][0] != ordered_candidates[-1][0]:
            diagnostics.append(
                GraphDiagnostic("warning", "conflicting_duplicate_node_id", "", "Duplicate node ID has incompatible fields")
            )
        result[node_id] = ordered_candidates[0][1]
    return result, node_order


def _canonical_visible_edges(
    edges: Iterable[GraphEdge],
    nodes_by_id: Mapping[str, GraphNode],
    diagnostics: list[GraphDiagnostic],
) -> tuple[list[GraphEdge], list[str]]:
    grouped: dict[str, list[_EdgeCandidate]] = defaultdict(list)
    for edge in edges:
        grouped[edge.id].append(_edge_candidate(edge))

    edge_order = _utf8_radix_order(grouped)
    visible: list[GraphEdge] = []
    visible_order: list[str] = []
    for edge_id in edge_order:
        candidates = grouped[edge_id]
        endpoints = {(candidate.edge.source, candidate.edge.target, candidate.edge.type) for candidate in candidates}
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

        canonical = _stable_byte_radix_sort([(candidate.key, candidate) for candidate in candidates])[0][1]
        edge = canonical.edge
        if edge.source not in nodes_by_id or edge.target not in nodes_by_id:
            diagnostics.append(GraphDiagnostic("warning", "dangling_edge", "", "Edge endpoint is not present in the graph"))
            continue
        if edge.source == edge.target:
            diagnostics.append(GraphDiagnostic("warning", "self_edge", "", "Self edge is retained for graph fidelity"))

        visible.append(
            GraphEdge(
                id=edge.id,
                source=edge.source,
                target=edge.target,
                type=edge.type,
                label=edge.label,
                evidence=_merged_evidence(candidates),
                metadata=edge.metadata,
            )
        )
        visible_order.append(edge_id)
    return visible, visible_order


def _build_adjacency(node_order: Iterable[str], edges: Iterable[GraphEdge]) -> dict[str, set[str]]:
    adjacency = {node_id: set() for node_id in node_order}
    for edge in edges:
        adjacency[edge.source].add(edge.target)
        if edge.source != edge.target:
            adjacency[edge.target].add(edge.source)
    return adjacency


def _components(node_order: list[str], adjacency: Mapping[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    visited: set[str] = set()
    membership: dict[str, int] = {}
    discovered: list[list[str]] = []
    for start in node_order:
        if start in visited:
            continue
        component_index = len(discovered)
        component: list[str] = []
        queue = deque((start,))
        visited.add(start)
        while queue:
            node_id = queue.popleft()
            membership[node_id] = component_index
            component.append(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        discovered.append(component)

    ranked_components = [[] for _ in discovered]
    for node_id in node_order:
        ranked_components[membership[node_id]].append(node_id)

    components_by_size = [[] for _ in range(len(node_order) + 1)]
    for component in ranked_components:
        components_by_size[len(component)].append(tuple(component))
    return tuple(
        component
        for size in range(len(node_order), 0, -1)
        for component in components_by_size[size]
    )


def _layout_components(
    components: tuple[tuple[str, ...], ...], adjacency: Mapping[str, set[str]], node_rank: Mapping[str, int]
) -> dict[str, tuple[float, float]]:
    layouts = [_component_layout(component, adjacency, node_rank) for component in components]
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


def _component_layout(
    component: tuple[str, ...], adjacency: Mapping[str, set[str]], node_rank: Mapping[str, int]
) -> _ComponentLayout:
    root = component[0]
    highest_degree = len(adjacency[root])
    for node_id in component[1:]:
        degree = len(adjacency[node_id])
        if degree > highest_degree:
            root = node_id
            highest_degree = degree

    depths = _bfs_depths(root, adjacency)
    layers: list[list[str]] = [[]]
    for node_id in component:
        depth = depths[node_id]
        while len(layers) <= depth:
            layers.append([])
        layers[depth].append(node_id)

    local_coordinates: dict[str, tuple[float, float]] = {}
    for depth, layer in enumerate(layers):
        if depth == 0:
            local_coordinates[layer[0]] = (0.0, 0.0)
            continue
        radius = depth * _RING_GAP
        for index, node_id in enumerate(layer):
            angle = 2.0 * math.pi * index / len(layer)
            local_coordinates[node_id] = (radius * math.cos(angle), radius * math.sin(angle))
    max_depth = len(layers) - 1
    return _ComponentLayout(local_coordinates, max(_NODE_MARGIN, max_depth * _RING_GAP + _NODE_MARGIN))


def _bfs_depths(root: str, adjacency: Mapping[str, set[str]]) -> dict[str, int]:
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
    values.extend(_utf8_radix_order(node.tags))
    for key in _utf8_radix_order(node.metadata):
        value = node.metadata[key]
        values.extend(value if isinstance(value, tuple) else (value,))
    return " ".join(_search_value(value) for value in values if value is not None).lower()


def _search_value(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _edge_candidate(edge: GraphEdge) -> _EdgeCandidate:
    evidence = tuple(_evidence_entry(item) for item in edge.evidence)
    evidence_bytes = _json_array_bytes(key for key, _ in _stable_byte_radix_sort(evidence))
    key = _json_object_bytes(
        (
            ("evidence", evidence_bytes),
            ("id", _json_bytes(edge.id)),
            ("label", _json_bytes(edge.label)),
            ("metadata", _metadata_bytes(edge.metadata)),
            ("source", _json_bytes(edge.source)),
            ("target", _json_bytes(edge.target)),
            ("type", _json_bytes(edge.type)),
        )
    )
    return _EdgeCandidate(edge, key, evidence)


def _merged_evidence(candidates: Iterable[_EdgeCandidate]) -> tuple[dict[str, str], ...]:
    unique: dict[bytes, dict[str, str]] = {}
    for candidate in candidates:
        for key, entry in candidate.evidence:
            unique.setdefault(key, entry)
    return tuple(entry for _, entry in _stable_byte_radix_sort(unique.items()))


def _evidence_entry(evidence: Mapping[str, str]) -> tuple[bytes, dict[str, str]]:
    keys = _utf8_radix_order(evidence)
    entry = {key: evidence[key] for key in keys}
    return _json_object_bytes(tuple((key, _json_bytes(entry[key])) for key in keys)), entry


def _node_key_bytes(node: GraphNode) -> bytes:
    return _json_object_bytes(
        (
            ("id", _json_bytes(node.id)),
            ("label", _json_bytes(node.label)),
            ("metadata", _metadata_bytes(node.metadata)),
            ("path", _json_bytes(node.path)),
            ("search_text", _json_bytes(node.search_text)),
            ("status", _json_bytes(node.status)),
            ("subtype", _json_bytes(node.subtype)),
            ("summary", _json_bytes(node.summary)),
            ("tags", _json_array_bytes(_json_bytes(tag) for tag in _utf8_radix_order(node.tags))),
            ("type", _json_bytes(node.type)),
            ("x", _json_bytes(node.x)),
            ("y", _json_bytes(node.y)),
        )
    )


def _metadata_bytes(metadata: Mapping[str, object]) -> bytes:
    keys = _utf8_radix_order(metadata)
    return _json_object_bytes(tuple((key, _json_value_bytes(metadata[key])) for key in keys))


def _json_value_bytes(value: object) -> bytes:
    if isinstance(value, tuple):
        return _json_array_bytes(_json_bytes(item) for item in value)
    return _json_bytes(value)


def _json_object_bytes(fields: tuple[tuple[str, bytes], ...]) -> bytes:
    return b"{" + b",".join(_json_bytes(key) + b":" + value for key, value in fields) + b"}"


def _json_array_bytes(values: Iterable[bytes]) -> bytes:
    return b"[" + b",".join(values) + b"]"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _canonical_diagnostics(diagnostics: Iterable[GraphDiagnostic]) -> tuple[GraphDiagnostic, ...]:
    ordered = list(set(diagnostics))
    for value in (
        lambda item: item.message,
        lambda item: item.path,
        lambda item: item.code,
        lambda item: item.severity,
    ):
        ordered = [item for _, item in _stable_byte_radix_sort((_utf8_bytes(value(item)), item) for item in ordered)]
    return tuple(ordered)


def _utf8_radix_order(values: Iterable[str]) -> list[str]:
    """Return a stable lexicographic order using UTF-8 bytes and no comparisons."""
    return [value for _, value in _stable_byte_radix_sort((_utf8_bytes(value), value) for value in values)]


def _utf8_bytes(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("canonical graph identities must be strings")
    return value.encode("utf-8")


def _stable_byte_radix_sort(entries: Iterable[tuple[bytes, _T]]) -> list[tuple[bytes, _T]]:
    """Stably sort byte keys in O(items + key bytes) with iterative MSD radix passes."""
    pending: list[tuple[list[tuple[bytes, _T]], int]] = [(list(entries), 0)]
    ordered: list[tuple[bytes, _T]] = []
    while pending:
        group, depth = pending.pop()
        if len(group) < 2:
            ordered.extend(group)
            continue
        counts = [0] * _BYTE_BUCKETS
        for key, _ in group:
            counts[key[depth] + 1 if depth < len(key) else 0] += 1
        starts = [0] * _BYTE_BUCKETS
        next_index = 0
        for bucket, count in enumerate(counts):
            starts[bucket] = next_index
            next_index += count
        positions = starts.copy()
        partitioned: list[tuple[bytes, _T] | None] = [None] * len(group)
        for entry in group:
            key = entry[0]
            bucket = key[depth] + 1 if depth < len(key) else 0
            partitioned[positions[bucket]] = entry
            positions[bucket] += 1
        terminal_count = counts[0]
        ordered.extend(partitioned[:terminal_count])
        for bucket in range(_BYTE_BUCKETS - 1, 0, -1):
            start = starts[bucket]
            end = start + counts[bucket]
            if end > start:
                pending.append(([entry for entry in partitioned[start:end] if entry is not None], depth + 1))
    return [entry for entry in ordered if entry is not None]


def _round_coordinate(value: float) -> float:
    rounded = round(value, 6)
    return 0.0 if rounded == 0 else rounded
