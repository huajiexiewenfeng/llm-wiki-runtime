"""Deterministic, evidence-backed relationships between collected graph nodes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping

from .graph_collect import CollectedDomain
from .graph_models import GraphDiagnostic, GraphEdge, stable_edge_id


_WIKILINK_PATTERN = re.compile(r"\[\[([^\[\]]+)\]\]")
_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class LinkResolution:
    """A local-link resolution result without source-body content."""

    path: str | None
    node_id: str | None
    status: str


def build_domain_edges(collected: CollectedDomain) -> tuple[tuple[GraphEdge, ...], tuple[GraphDiagnostic, ...]]:
    """Build only explicit registered, structured-reference, and body-link edges."""
    nodes = {node.id: node for node in collected.nodes}
    domain_node = next((node for node in collected.nodes if node.type == "domain"), None)
    scope_node = next((node for node in collected.nodes if node.type == "scope"), None)
    domain_root = domain_node.path if domain_node is not None else ""
    edges: dict[tuple[str, str, str], _EdgeParts] = {}
    diagnostics: list[GraphDiagnostic] = []

    if domain_node is not None and scope_node is not None:
        _add_edge(edges, scope_node.id, domain_node.id, "REGISTERED", "scope", ".meta/profile.yml", "profile-registration")
    if domain_node is not None:
        for node in sorted(collected.nodes, key=lambda item: item.id):
            if node.type in {"record", "document"}:
                _add_edge(edges, domain_node.id, node.id, "REGISTERED", node.type, ".meta/profile.yml", "profile-registration")

    for node in sorted(collected.nodes, key=lambda item: item.id):
        if node.type not in {"record", "document"}:
            continue
        frontmatter = collected.frontmatter_by_node.get(node.id, {})
        for field, value in sorted(frontmatter.items()):
            if not _is_reference_field(field, value):
                continue
            for identity in _reference_values(value):
                _add_structured_reference(edges, diagnostics, node, field, identity, collected.identity_index)

        body = collected.body_by_node.get(node.id)
        if not isinstance(body, str) or not domain_root:
            continue
        for target in _iter_wikilink_targets(body):
            resolution = resolve_wikilink(node.path, target, domain_root, collected.path_index)
            _add_link_result(edges, diagnostics, node, resolution, "wikilink")
        for target in _iter_markdown_targets(body):
            resolution = resolve_markdown_link(node.path, target, domain_root, collected.path_index)
            _add_link_result(edges, diagnostics, node, resolution, "markdown-link")

    graph_edges = tuple(
        GraphEdge(
            id=stable_edge_id(source, target, edge_type),
            source=source,
            target=target,
            type=edge_type,
            label=min(parts.labels),
            evidence=tuple({"method": method, "path": path} for method, path in sorted(parts.evidence)),
        )
        for (source, target, edge_type), parts in sorted(edges.items(), key=lambda item: stable_edge_id(*item[0]))
    )
    return graph_edges, tuple(sorted(diagnostics, key=_diagnostic_key))


def resolve_wikilink(
    source_path: str, target: str, domain_root: str, path_index: Mapping[str, tuple[str, ...]]
) -> LinkResolution:
    """Resolve a WikiLink using the bounded same-Domain algorithm from design Section 10."""
    cleaned = _clean_wikilink_target(target)
    if cleaned is None:
        return _ignored()
    source = _safe_path(source_path)
    root = _safe_path(domain_root)
    if source is None or root is None or not _under_domain(source, root):
        return _unresolved()

    if cleaned.startswith(("./", "../")) or cleaned.startswith((".\\", "..\\")):
        candidates = _with_markdown_suffixes(_join_path(source, cleaned), cleaned)
        return _resolve_candidates(candidates, root, path_index)
    if "/" in cleaned or "\\" in cleaned:
        candidates = _with_markdown_suffixes(_join_directory(root, cleaned), cleaned)
        return _resolve_candidates(candidates, root, path_index)

    exact = _with_markdown_suffixes(_join_path(source, cleaned), cleaned)
    result = _resolve_candidates(exact, root, path_index)
    if result.status != "unresolved":
        return result
    root_candidates = _with_markdown_suffixes(_join_directory(root, cleaned), cleaned)
    result = _resolve_candidates(root_candidates, root, path_index)
    if result.status != "unresolved":
        return result
    filename = _filename_with_suffix(cleaned)
    matches = sorted(
        path
        for path in path_index
        if _under_domain(path, root) and PurePosixPath(path).name.casefold() == filename.casefold()
    )
    return _resolve_paths(matches, root, path_index)


def resolve_markdown_link(
    source_path: str, target: str, domain_root: str, path_index: Mapping[str, tuple[str, ...]]
) -> LinkResolution:
    """Resolve a local Markdown destination relative to the source document only."""
    cleaned = _clean_markdown_destination(target)
    source = _safe_path(source_path)
    root = _safe_path(domain_root)
    if cleaned is None:
        return _ignored()
    if source is None or root is None or not _under_domain(source, root):
        return _unresolved()
    candidate = _join_path(source, cleaned)
    return _resolve_candidates((candidate,), root, path_index)


@dataclass
class _EdgeParts:
    labels: set[str]
    evidence: set[tuple[str, str]]


def _add_edge(
    edges: dict[tuple[str, str, str], _EdgeParts], source: str, target: str, edge_type: str, label: str, path: str, method: str
) -> None:
    key = (source, target, edge_type)
    parts = edges.setdefault(key, _EdgeParts(set(), set()))
    parts.labels.add(label)
    parts.evidence.add((method, path))


def _add_structured_reference(
    edges: dict[tuple[str, str, str], _EdgeParts],
    diagnostics: list[GraphDiagnostic],
    node: object,
    field: str,
    identity: str,
    identity_index: Mapping[str, tuple[str, ...]],
) -> None:
    candidates = tuple(sorted(set(identity_index.get(identity, ()))))
    source_id = getattr(node, "id")
    path = getattr(node, "path")
    if len(candidates) == 0:
        diagnostics.append(GraphDiagnostic("warning", "unresolved_structured_reference", path, "Structured reference does not resolve to a collected identity"))
    elif len(candidates) > 1:
        diagnostics.append(GraphDiagnostic("warning", "ambiguous_structured_reference", path, "Structured reference resolves to multiple collected identities"))
    elif candidates[0] == source_id:
        diagnostics.append(GraphDiagnostic("warning", "self_structured_reference", path, "Structured self-references do not create graph edges"))
    else:
        _add_edge(edges, source_id, candidates[0], "REFERENCED", field, path, f"frontmatter-reference:{field}")


def _add_link_result(
    edges: dict[tuple[str, str, str], _EdgeParts],
    diagnostics: list[GraphDiagnostic],
    node: object,
    resolution: LinkResolution,
    method: str,
) -> None:
    source_id = getattr(node, "id")
    path = getattr(node, "path")
    if resolution.status == "resolved" and resolution.node_id is not None:
        if resolution.node_id == source_id:
            diagnostics.append(GraphDiagnostic("warning", f"self_{method}", path, "Self-links do not create graph edges"))
        else:
            _add_edge(edges, source_id, resolution.node_id, "LINKED", method, path, method)
    elif resolution.status in {"unresolved", "ambiguous"}:
        diagnostics.append(
            GraphDiagnostic(
                "warning",
                f"{resolution.status}_{method}",
                path,
                "Local link does not resolve to one collected Markdown node",
            )
        )


def _is_reference_field(field: str, value: object) -> bool:
    return field.endswith("_id") or field.endswith("_ids") or isinstance(value, tuple)


def _reference_values(value: object) -> tuple[str, ...]:
    values = value if isinstance(value, tuple) else (value,)
    return tuple(sorted({str(item) for item in values if item is not None and not isinstance(item, (tuple, list, dict))}))


def _iter_wikilink_targets(body: str):
    yield from (match.group(1) for match in _WIKILINK_PATTERN.finditer(body))


def _iter_markdown_targets(body: str):
    index = 0
    while index < len(body):
        start = body.find("[", index)
        if start < 0:
            return
        if start > 0 and body[start - 1] == "!":
            index = start + 1
            continue
        close = body.find("](", start + 1)
        if close < 0:
            return
        depth = 1
        cursor = close + 2
        destination_start = cursor
        while cursor < len(body) and depth:
            char = body[cursor]
            if char == "\\" and cursor + 1 < len(body):
                cursor += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            cursor += 1
        if depth == 0:
            yield body[destination_start : cursor - 1]
            index = cursor
        else:
            index = close + 2


def _clean_wikilink_target(target: str) -> str | None:
    if not isinstance(target, str):
        return None
    value = target.split("|", 1)[0].split("#", 1)[0].split("?", 1)[0].strip()
    return _validate_local_target(value)


def _clean_markdown_destination(target: str) -> str | None:
    if not isinstance(target, str):
        return None
    value = target.strip()
    if value.startswith("<"):
        closing = value.find(">")
        if closing < 0:
            return None
        value = value[1:closing]
    else:
        value = _first_unescaped_word(value)
    value = value.split("#", 1)[0].split("?", 1)[0]
    value = _decode_markdown_path(value)
    return _validate_local_target(value)


def _first_unescaped_word(value: str) -> str:
    result: list[str] = []
    escaped = False
    for char in value:
        if char.isspace() and not escaped:
            break
        result.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    return "".join(result)


def _decode_markdown_path(value: str) -> str:
    result: list[str] = []
    cursor = 0
    while cursor < len(value):
        if value[cursor] == "\\" and cursor + 1 < len(value) and value[cursor + 1] in "()[]<>":
            result.append(value[cursor + 1])
            cursor += 2
        else:
            result.append(value[cursor])
            cursor += 1
    return "".join(result)


def _validate_local_target(value: str) -> str | None:
    if not value or value.startswith("//") or _SCHEME_PATTERN.match(value):
        return None
    return value


def _with_markdown_suffixes(candidate: str | None, target: str) -> tuple[str, ...]:
    if candidate is None:
        return ()
    if PurePosixPath(target.replace("\\", "/")).suffix.casefold() == ".md":
        return (candidate,)
    return (f"{candidate}.md", f"{candidate}/index.md")


def _filename_with_suffix(value: str) -> str:
    return value if PurePosixPath(value).suffix.casefold() == ".md" else f"{value}.md"


def _resolve_candidates(candidates: tuple[str, ...], root: str, path_index: Mapping[str, tuple[str, ...]]) -> LinkResolution:
    for candidate in candidates:
        result = _resolve_paths((candidate,), root, path_index)
        if result.status != "unresolved":
            return result
    return _unresolved()


def _resolve_paths(paths: list[str] | tuple[str, ...], root: str, path_index: Mapping[str, tuple[str, ...]]) -> LinkResolution:
    matches: list[tuple[str, str]] = []
    for path in paths:
        if not _under_domain(path, root):
            continue
        node_ids = tuple(sorted(set(path_index.get(path, ()))))
        if len(node_ids) == 1:
            matches.append((path, node_ids[0]))
        elif len(node_ids) > 1:
            return LinkResolution(None, None, "ambiguous")
    unique = tuple(sorted(set(matches)))
    if len(unique) == 1:
        return LinkResolution(unique[0][0], unique[0][1], "resolved")
    if len(unique) > 1:
        return LinkResolution(None, None, "ambiguous")
    return _unresolved()


def _join_path(base_file: str, target: str) -> str | None:
    base = PurePosixPath(base_file).parent
    return _join_directory(base.as_posix(), target)


def _join_directory(base_directory: str, target: str) -> str | None:
    base = PurePosixPath(base_directory)
    target_path = PurePosixPath(target.replace("\\", "/"))
    parts: list[str] = list(base.parts)
    for part in target_path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or None


def _safe_path(path: str) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//") or re.match(r"^[A-Za-z]:", normalized):
        return None
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return PurePosixPath(*parts).as_posix()


def _under_domain(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def _unresolved() -> LinkResolution:
    return LinkResolution(None, None, "unresolved")


def _ignored() -> LinkResolution:
    return LinkResolution(None, None, "ignored")


def _diagnostic_key(item: GraphDiagnostic) -> tuple[str, str, str, str]:
    return (item.severity, item.code, item.path, item.message)
