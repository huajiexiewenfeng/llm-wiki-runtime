"""Deterministic graph contracts shared by graph collection and export code."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TypeAlias


GraphScalar: TypeAlias = str | int | float | bool | None
GraphMetadata: TypeAlias = dict[str, GraphScalar | list[GraphScalar]]


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    subtype: str
    label: str
    summary: str
    status: str
    tags: tuple[str, ...]
    path: str
    metadata: GraphMetadata = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    search_text: str = ""


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source: str
    target: str
    type: str
    label: str
    evidence: tuple[dict[str, str], ...]
    metadata: GraphMetadata = field(default_factory=dict)


@dataclass(frozen=True)
class GraphDiagnostic:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class DomainGraph:
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    diagnostics: tuple[GraphDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, list[dict[str, object]]]:
        return {
            "nodes": [_node_to_dict(node) for node in sorted(self.nodes, key=lambda node: node.id)],
            "edges": [_edge_to_dict(edge) for edge in sorted(self.edges, key=lambda edge: edge.id)],
            "diagnostics": [
                _diagnostic_to_dict(diagnostic)
                for diagnostic in sorted(
                    self.diagnostics,
                    key=lambda diagnostic: (
                        diagnostic.severity,
                        diagnostic.code,
                        diagnostic.path,
                        diagnostic.message,
                    ),
                )
            ],
        }


def stable_node_id(node_type: str, path: str) -> str:
    """Return a deterministic ID for a node's canonical type and path."""
    return _stable_id("node", node_type, path)


def stable_edge_id(source: str, target: str, edge_type: str) -> str:
    """Return a deterministic ID for a directed edge's canonical inputs."""
    return _stable_id("edge", source, target, edge_type)


def normalize_scope_path(path: str) -> str:
    """Normalize a relative scope path without accepting traversal or host paths."""
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")

    normalized_input = path.replace("\\", "/")
    if normalized_input.startswith("/") or normalized_input.startswith("//"):
        raise ValueError("path must be relative to the configured scope")
    if len(normalized_input) >= 2 and normalized_input[1] == ":" and normalized_input[0].isalpha():
        raise ValueError("path must not use a drive letter")

    parts = normalized_input.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path contains unsafe traversal segments")

    result = PurePosixPath(*parts).as_posix()
    if result in {"", "."}:
        raise ValueError("path must not normalize to an empty path")
    return result


def _stable_id(prefix: str, *parts: str) -> str:
    canonical = "\x1f".join(parts)
    digest = sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _sorted_metadata(metadata: GraphMetadata) -> dict[str, GraphScalar | list[GraphScalar]]:
    return {key: metadata[key] for key in sorted(metadata)}


def _node_to_dict(node: GraphNode) -> dict[str, object]:
    return {
        "id": node.id,
        "type": node.type,
        "subtype": node.subtype,
        "label": node.label,
        "summary": node.summary,
        "status": node.status,
        "tags": sorted(node.tags),
        "path": node.path,
        "metadata": _sorted_metadata(node.metadata),
        "x": node.x,
        "y": node.y,
        "search_text": node.search_text,
    }


def _edge_to_dict(edge: GraphEdge) -> dict[str, object]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "type": edge.type,
        "label": edge.label,
        "evidence": [dict(item) for item in edge.evidence],
        "metadata": _sorted_metadata(edge.metadata),
    }


def _diagnostic_to_dict(diagnostic: GraphDiagnostic) -> dict[str, str]:
    return {
        "severity": diagnostic.severity,
        "code": diagnostic.code,
        "path": diagnostic.path,
        "message": diagnostic.message,
    }
