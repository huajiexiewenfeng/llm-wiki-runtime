"""Deterministic graph contracts shared by graph collection and export code."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Mapping, TypeAlias


GraphScalar: TypeAlias = str | int | float | bool | None
GraphMetadata: TypeAlias = Mapping[str, GraphScalar | tuple[GraphScalar, ...]]


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "subtype": self.subtype,
            "label": self.label,
            "summary": self.summary,
            "status": self.status,
            "tags": sorted(self.tags),
            "path": self.path,
            "metadata": _metadata_to_dict(self.metadata),
            "x": self.x,
            "y": self.y,
            "search_text": self.search_text,
        }


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source: str
    target: str
    type: str
    label: str
    evidence: tuple[Mapping[str, str], ...]
    metadata: GraphMetadata = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(_freeze_evidence(item) for item in self.evidence))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "label": self.label,
            "evidence": _evidence_to_list(self.evidence),
            "metadata": _metadata_to_dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphDiagnostic:
    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class DomainGraph:
    # Keep the original positional ordering for Tasks 3-4 callers.
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    diagnostics: tuple[GraphDiagnostic, ...] = ()
    schema_version: str = "v0.1"
    domain: GraphMetadata = field(default_factory=dict)
    stats: GraphMetadata = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "domain", _freeze_metadata(self.domain))
        object.__setattr__(self, "stats", _freeze_metadata(self.stats))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "domain": _metadata_to_dict(self.domain),
            "stats": _metadata_to_dict(self.stats),
            "nodes": [node.to_dict() for node in sorted(self.nodes, key=lambda node: node.id)],
            "edges": [edge.to_dict() for edge in sorted(self.edges, key=lambda edge: edge.id)],
            "diagnostics": [
                diagnostic.to_dict()
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


def stable_node_id(domain_id: str, node_type: str, path: str) -> str:
    """Return a stable ID for a node's canonical domain, type, and path."""
    return _stable_id(
        _identity_text(node_type, "node type"),
        _identity_text(domain_id, "domain ID"),
        _identity_text(node_type, "node type"),
        normalize_scope_path(path),
    )


def stable_edge_id(source: str, target: str, edge_type: str) -> str:
    """Return a stable ID for a directed edge's canonical inputs."""
    return _stable_id(
        "edge",
        _identity_text(source, "edge source"),
        _identity_text(target, "edge target"),
        _identity_text(edge_type, "edge type"),
    )


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


def _identity_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise ValueError(f"{name} must be a non-empty string")
    return normalized


def _stable_id(prefix: str, *parts: str) -> str:
    canonical = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    digest = sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _freeze_metadata(metadata: GraphMetadata) -> GraphMetadata:
    if not isinstance(metadata, Mapping):
        raise ValueError("graph metadata must be a mapping")

    frozen: dict[str, GraphScalar | tuple[GraphScalar, ...]] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise ValueError("graph metadata keys must be strings")
        if isinstance(value, (list, tuple)):
            frozen[key] = tuple(_validate_scalar(item) for item in value)
        else:
            frozen[key] = _validate_scalar(value)
    return MappingProxyType(frozen)


def _validate_scalar(value: object) -> GraphScalar:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("graph values must be finite JSON scalars")


def _freeze_evidence(item: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(item, Mapping):
        raise ValueError("edge evidence must be mappings")
    frozen: dict[str, str] = {}
    for key, value in item.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("edge evidence keys and values must be strings")
        frozen[key] = value
    return MappingProxyType(frozen)


def _metadata_to_dict(metadata: GraphMetadata) -> dict[str, GraphScalar | list[GraphScalar]]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in sorted(metadata.items())
    }


def _evidence_to_list(evidence: tuple[Mapping[str, str], ...]) -> list[dict[str, str]]:
    return [dict(sorted(item.items())) for item in sorted(evidence, key=lambda item: tuple(sorted(item.items())))]
