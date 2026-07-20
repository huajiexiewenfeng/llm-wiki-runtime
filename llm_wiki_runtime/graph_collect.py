"""Scope-local, deterministic graph node collection without relationship extraction."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .frontmatter import FrontmatterScalar, FrontmatterValue, parse_frontmatter
from .graph_adapter import GraphAdapter
from .graph_models import GraphDiagnostic, GraphNode, stable_node_id
from .models import Profile, WriteRule
from .paths import ensure_under_root, validate_slug


_SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_VARIABLE_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class DomainDiscovery:
    domain_ids: tuple[str, ...]
    diagnostics: tuple[GraphDiagnostic, ...]


@dataclass(frozen=True)
class CollectedDomain:
    nodes: tuple[GraphNode, ...]
    diagnostics: tuple[GraphDiagnostic, ...]
    frontmatter_by_node: Mapping[str, Mapping[str, FrontmatterValue]]
    body_by_node: Mapping[str, str]
    identity_index: Mapping[str, tuple[str, ...]]
    path_index: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda node: node.id)))
        object.__setattr__(
            self,
            "diagnostics",
            tuple(sorted(self.diagnostics, key=_diagnostic_sort_key)),
        )
        object.__setattr__(self, "frontmatter_by_node", _freeze_frontmatter_by_node(self.frontmatter_by_node))
        object.__setattr__(self, "body_by_node", _freeze_mapping(self.body_by_node))
        object.__setattr__(self, "identity_index", _freeze_index(self.identity_index))
        object.__setattr__(self, "path_index", _freeze_index(self.path_index))


def discover_domains(wiki_root: Path, profile: Profile) -> DomainDiscovery:
    """Intersect declared profile domains with real immediate scope directories."""
    declared: set[str] = set()
    diagnostics: list[GraphDiagnostic] = []
    for directory in profile.directories:
        normalized = _normalized_profile_directory(directory)
        if normalized is None:
            continue
        parts = normalized.split("/")
        if len(parts) < 3 or parts[0] != "domains":
            continue
        try:
            declared.add(validate_slug(parts[1]))
        except ValueError:
            diagnostics.append(
                GraphDiagnostic("warning", "invalid_declared_domain", "", "Profile declares an invalid domain identifier")
            )

    actual: set[str] = set()
    domains_root = wiki_root / "domains"
    if _is_safe_directory(domains_root, wiki_root):
        for child in sorted(domains_root.iterdir(), key=lambda item: item.name):
            if child.is_symlink() or not _is_safe_directory(child, wiki_root):
                continue
            try:
                actual.add(validate_slug(child.name))
            except ValueError:
                diagnostics.append(
                    GraphDiagnostic("warning", "invalid_domain_directory", "domains", "Scope contains an invalid domain directory")
                )

    for domain_id in sorted(declared - actual):
        diagnostics.append(
            GraphDiagnostic(
                "warning",
                "declared_domain_missing",
                f"domains/{domain_id}",
                "Profile declares a domain directory that is not present in this scope",
            )
        )
    for domain_id in sorted(actual - declared):
        diagnostics.append(
            GraphDiagnostic(
                "warning",
                "undeclared_domain_directory",
                f"domains/{domain_id}",
                "Scope contains a domain directory not declared by the profile",
            )
        )
    return DomainDiscovery(tuple(sorted(declared & actual)), tuple(sorted(diagnostics, key=_diagnostic_sort_key)))


def collect_domain_nodes(
    wiki_root: Path,
    profile: Profile,
    adapter: GraphAdapter,
    domain_id: str,
) -> CollectedDomain:
    """Collect only nodes owned by one validated Domain within one wiki scope."""
    domain_id = validate_slug(domain_id)
    discovery = discover_domains(wiki_root, profile)
    if domain_id not in discovery.domain_ids:
        raise ValueError(f"domain is not available in this scope: {domain_id}")
    if adapter.domain_id != domain_id:
        raise ValueError("graph adapter domain_id does not match collected domain")

    diagnostics = list(discovery.diagnostics)
    nodes: list[GraphNode] = [
        _node(
            domain_id,
            "scope",
            "scope",
            profile.display_name or profile.id,
            ".meta/profile.yml",
        ),
        _node(domain_id, "domain", "domain", adapter.display_name or domain_id, f"domains/{domain_id}"),
    ]
    frontmatter_by_node: dict[str, Mapping[str, FrontmatterValue]] = {}
    body_by_node: dict[str, str] = {}
    identity_candidates: dict[str, set[str]] = {}
    path_candidates: dict[str, set[str]] = {}
    templates = _compile_write_rule_templates(profile.write_rules, diagnostics)

    for path in _iter_domain_markdown_paths(wiki_root, domain_id):
        logical_path = _scope_path(wiki_root, path)
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, body_offset = parse_frontmatter(text)
        except (OSError, UnicodeError, ValueError):
            diagnostics.append(
                GraphDiagnostic(
                    "warning",
                    "malformed_frontmatter",
                    logical_path,
                    "Markdown frontmatter could not be collected",
                )
            )
            continue

        matching_rule = next(
            (rule for rule, pattern in templates if pattern.fullmatch(logical_path)),
            None,
        )
        node_type = "record" if matching_rule is not None else "document"
        subtype_fallback = matching_rule.record_type if matching_rule is not None else "document"
        node = _markdown_node(domain_id, node_type, subtype_fallback, logical_path, frontmatter, adapter, diagnostics)
        nodes.append(node)
        frontmatter_by_node[node.id] = frontmatter
        body_by_node[node.id] = text[body_offset:]
        path_candidates.setdefault(logical_path, set()).add(node.id)
        _index_frontmatter_identities(frontmatter, node.id, identity_candidates)

    referenced_values = set(identity_candidates)
    _collect_sources(wiki_root, domain_id, referenced_values, nodes, identity_candidates, diagnostics)
    _collect_artifacts(
        wiki_root,
        domain_id,
        len(discovery.domain_ids) == 1,
        nodes,
        identity_candidates,
        diagnostics,
    )
    _collect_logs(wiki_root, domain_id, profile, nodes, diagnostics)
    return CollectedDomain(
        nodes=tuple(nodes),
        diagnostics=tuple(diagnostics),
        frontmatter_by_node=frontmatter_by_node,
        body_by_node=body_by_node,
        identity_index={key: tuple(sorted(value)) for key, value in identity_candidates.items()},
        path_index={key: tuple(sorted(value)) for key, value in path_candidates.items()},
    )


def _normalized_profile_directory(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or "/../" in f"/{normalized}/" or not normalized:
        return None
    return normalized


def _is_safe_directory(path: Path, wiki_root: Path) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        path.resolve().relative_to(wiki_root.resolve())
    except ValueError:
        return False
    return True


def _iter_domain_markdown_paths(wiki_root: Path, domain_id: str) -> tuple[Path, ...]:
    root = ensure_under_root(wiki_root, Path("domains") / domain_id)
    if not _is_safe_directory(root, wiki_root):
        return ()
    paths: list[Path] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if _is_safe_directory(current_path / name, wiki_root)
        )
        for name in sorted(file_names):
            path = current_path / name
            if path.suffix.lower() != ".md" or path.is_symlink() or not path.is_file():
                continue
            try:
                path.resolve().relative_to(wiki_root.resolve())
            except ValueError:
                continue
            paths.append(path)
    return tuple(sorted(paths, key=lambda item: _scope_path(wiki_root, item)))


def _scope_path(wiki_root: Path, path: Path) -> str:
    return path.relative_to(wiki_root).as_posix()


def _compile_write_rule_templates(
    rules: Mapping[str, WriteRule], diagnostics: list[GraphDiagnostic]
) -> tuple[tuple[WriteRule, re.Pattern[str]], ...]:
    compiled: list[tuple[WriteRule, re.Pattern[str]]] = []
    for record_type, rule in sorted(rules.items()):
        try:
            normalized = _template_path(rule.path)
            position = 0
            fragments: list[str] = ["^"]
            for match in _VARIABLE_PATTERN.finditer(normalized):
                fragments.append(re.escape(normalized[position : match.start()]))
                fragments.append(f"(?:{_SEGMENT_PATTERN})")
                position = match.end()
            fragments.append(re.escape(normalized[position:]))
            fragments.append("$")
            if "{" in _VARIABLE_PATTERN.sub("", normalized) or "}" in _VARIABLE_PATTERN.sub("", normalized):
                raise ValueError("unmatched write-rule variable marker")
            compiled.append((rule, re.compile("".join(fragments))))
        except (TypeError, ValueError, re.error):
            diagnostics.append(
                GraphDiagnostic("warning", "invalid_write_rule_template", "", f"Write rule {record_type!r} was ignored")
            )
    return tuple(compiled)


def _template_path(template: str) -> str:
    if not isinstance(template, str) or not template:
        raise ValueError("empty write-rule path")
    normalized = template.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//") or ":" in normalized:
        raise ValueError("unsafe write-rule path")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("unsafe write-rule path")
    return normalized


def _markdown_node(
    domain_id: str,
    node_type: str,
    subtype_fallback: str,
    logical_path: str,
    frontmatter: Mapping[str, FrontmatterValue],
    adapter: GraphAdapter,
    diagnostics: list[GraphDiagnostic],
) -> GraphNode:
    defaults = adapter.defaults
    subtype_value = _string_field(frontmatter, defaults.subtype_field)
    subtype = adapter.subtype_map.get(subtype_value or subtype_fallback, subtype_value or subtype_fallback)
    label = _string_field(frontmatter, defaults.label_field) or Path(logical_path).stem
    summary = _string_field(frontmatter, defaults.summary_field) or ""
    status = _string_field(frontmatter, defaults.status_field) or ""
    tags = _string_list_field(frontmatter, defaults.tags_field)
    metadata: dict[str, FrontmatterScalar] = {}
    for field in defaults.metadata_allowlist:
        if field not in frontmatter:
            continue
        value = frontmatter[field]
        if isinstance(value, list):
            diagnostics.append(
                GraphDiagnostic(
                    "warning",
                    "non_scalar_metadata",
                    logical_path,
                    "Allowlisted metadata must be a scalar value",
                )
            )
        else:
            metadata[field] = value
    return GraphNode(
        id=stable_node_id(domain_id, node_type, logical_path),
        type=node_type,
        subtype=subtype,
        label=label,
        summary=summary,
        status=status,
        tags=tags,
        path=logical_path,
        metadata=metadata,
    )


def _string_field(frontmatter: Mapping[str, FrontmatterValue], field: str | None) -> str | None:
    if not field:
        return None
    value = frontmatter.get(field)
    return value if isinstance(value, str) and value else None


def _string_list_field(frontmatter: Mapping[str, FrontmatterValue], field: str | None) -> tuple[str, ...]:
    if not field:
        return ()
    value = frontmatter.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return ()
    return tuple(sorted(set(value)))


def _index_frontmatter_identities(
    frontmatter: Mapping[str, FrontmatterValue], node_id: str, candidates: dict[str, set[str]]
) -> None:
    for key, value in sorted(frontmatter.items()):
        if key.endswith("_id") and not isinstance(value, list):
            identity = _identity_value(value)
            if identity is not None:
                candidates.setdefault(identity, set()).add(node_id)
        elif key.endswith("_ids") and isinstance(value, list):
            for item in value:
                identity = _identity_value(item)
                if identity is not None:
                    candidates.setdefault(identity, set()).add(node_id)


def _identity_value(value: FrontmatterScalar) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _collect_sources(
    wiki_root: Path,
    domain_id: str,
    referenced_values: set[str],
    nodes: list[GraphNode],
    identities: dict[str, set[str]],
    diagnostics: list[GraphDiagnostic],
) -> None:
    registry = _load_registry(wiki_root, "sources/registry.json", "sources", "source", diagnostics)
    entries = registry.get("sources", []) if isinstance(registry, dict) else []
    if not isinstance(entries, list):
        diagnostics.append(GraphDiagnostic("warning", "malformed_source_registry", "sources/registry.json", "Source registry entries are invalid"))
        return
    for entry in sorted((item for item in entries if isinstance(item, dict)), key=_registry_sort_key):
        source_id = entry.get("source_id")
        path = entry.get("path")
        if not isinstance(source_id, str) or not source_id or not isinstance(path, str):
            diagnostics.append(GraphDiagnostic("warning", "invalid_source_registry_entry", "sources/registry.json", "Source registry entry was ignored"))
            continue
        logical_path = _safe_registry_path(path, "sources/registry.json", "invalid_source_registry_entry", diagnostics)
        if logical_path is None:
            continue
        owned_prefixes = (f"sources/originals/{domain_id}/", f"sources/extracts/{domain_id}/")
        if source_id not in referenced_values and not logical_path.startswith(owned_prefixes):
            continue
        node = _node(domain_id, "source", _nonempty_string(entry.get("source_type"), "source"), source_id, logical_path)
        if any(existing.id == node.id for existing in nodes):
            continue
        nodes.append(node)
        identities.setdefault(source_id, set()).add(node.id)


def _collect_artifacts(
    wiki_root: Path,
    domain_id: str,
    single_domain_scope: bool,
    nodes: list[GraphNode],
    identities: dict[str, set[str]],
    diagnostics: list[GraphDiagnostic],
) -> None:
    registry = _load_registry(wiki_root, "artifacts/index.json", "artifacts", "artifact", diagnostics)
    entries = registry.get("artifacts", []) if isinstance(registry, dict) else []
    if not isinstance(entries, list):
        diagnostics.append(GraphDiagnostic("warning", "malformed_artifact_index", "artifacts/index.json", "Artifact index entries are invalid"))
        return
    for entry in sorted((item for item in entries if isinstance(item, dict)), key=_registry_sort_key):
        artifact_id = entry.get("artifact_id")
        path = entry.get("path")
        if not isinstance(artifact_id, str) or not artifact_id or not isinstance(path, str):
            diagnostics.append(GraphDiagnostic("warning", "invalid_artifact_index_entry", "artifacts/index.json", "Artifact index entry was ignored"))
            continue
        declared_domain = entry.get("domain")
        if declared_domain != domain_id:
            if declared_domain is not None or not single_domain_scope:
                continue
            diagnostics.append(
                GraphDiagnostic(
                    "warning",
                    "legacy_artifact_domain_assumed",
                    "artifacts/index.json",
                    "Legacy artifact was assigned to the only discovered domain",
                )
            )
        logical_path = _safe_registry_path(path, "artifacts/index.json", "invalid_artifact_index_entry", diagnostics)
        if logical_path is None:
            continue
        node = _node(domain_id, "artifact", _nonempty_string(entry.get("artifact_type"), "artifact"), artifact_id, logical_path)
        if any(existing.id == node.id for existing in nodes):
            continue
        nodes.append(node)
        identities.setdefault(artifact_id, set()).add(node.id)


def _collect_logs(
    wiki_root: Path,
    domain_id: str,
    profile: Profile,
    nodes: list[GraphNode],
    diagnostics: list[GraphDiagnostic],
) -> None:
    del wiki_root
    for log_type, rule in sorted(profile.log_rules.items()):
        logical_path = _safe_registry_path(rule.path, "", "invalid_log_path", diagnostics)
        if logical_path is None:
            continue
        nodes.append(
            GraphNode(
                id=stable_node_id(domain_id, "log", logical_path),
                type="log",
                subtype=log_type,
                label=log_type,
                summary="",
                status="",
                tags=(),
                path=logical_path,
                metadata={"profile_id": profile.id},
            )
        )


def _load_registry(
    wiki_root: Path,
    logical_path: str,
    expected_key: str,
    kind: str,
    diagnostics: list[GraphDiagnostic],
) -> dict[str, object]:
    path = wiki_root / logical_path
    if not path.exists():
        return {expected_key: []}
    if path.is_symlink() or not path.is_file():
        diagnostics.append(GraphDiagnostic("warning", f"malformed_{kind}_registry", logical_path, f"{kind.title()} registry was ignored"))
        return {expected_key: []}
    try:
        path.resolve().relative_to(wiki_root.resolve())
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        diagnostics.append(GraphDiagnostic("warning", f"malformed_{kind}_registry", logical_path, f"{kind.title()} registry was ignored"))
        return {expected_key: []}
    return value if isinstance(value, dict) else {expected_key: []}


def _safe_registry_path(
    value: str,
    diagnostic_path: str,
    code: str,
    diagnostics: list[GraphDiagnostic],
) -> str | None:
    try:
        normalized = value.replace("\\", "/")
        if not normalized or normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
            raise ValueError("unsafe registry path")
        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("unsafe registry path")
        return normalized
    except (AttributeError, ValueError):
        diagnostics.append(GraphDiagnostic("warning", code, diagnostic_path, "Registry path was ignored"))
        return None


def _node(domain_id: str, node_type: str, subtype: str, label: str, path: str) -> GraphNode:
    return GraphNode(
        id=stable_node_id(domain_id, node_type, path),
        type=node_type,
        subtype=subtype,
        label=label,
        summary="",
        status="",
        tags=(),
        path=path,
    )


def _nonempty_string(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _registry_sort_key(entry: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(entry.get("source_id") or entry.get("artifact_id") or ""),
        str(entry.get("path") or ""),
        str(entry.get("source_type") or entry.get("artifact_type") or ""),
    )


def _diagnostic_sort_key(item: GraphDiagnostic) -> tuple[str, str, str, str]:
    return (item.severity, item.code, item.path, item.message)


def _freeze_mapping(mapping: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType({key: mapping[key] for key in sorted(mapping)})


def _freeze_index(mapping: Mapping[str, tuple[str, ...]]) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({key: tuple(sorted(set(mapping[key]))) for key in sorted(mapping)})


def _freeze_frontmatter_by_node(
    mapping: Mapping[str, Mapping[str, FrontmatterValue]]
) -> Mapping[str, Mapping[str, FrontmatterValue]]:
    frozen: dict[str, Mapping[str, FrontmatterValue]] = {}
    for node_id in sorted(mapping):
        values: dict[str, FrontmatterValue] = {}
        for key, value in sorted(mapping[node_id].items()):
            values[key] = tuple(value) if isinstance(value, list) else value
        frozen[node_id] = MappingProxyType(values)
    return MappingProxyType(frozen)
