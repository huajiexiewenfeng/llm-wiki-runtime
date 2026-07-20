"""Scope-local, deterministic graph node collection without relationship extraction."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, TypeAlias

from .frontmatter import FrontmatterScalar, FrontmatterValue, parse_frontmatter
from .graph_adapter import GraphAdapter
from .graph_models import GraphDiagnostic, GraphNode, stable_node_id
from .models import Profile, WriteRule
from .paths import ensure_under_root, validate_slug


_VARIABLE_SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")

# Task 4 intentionally scans these frozen sequences for *_ids references.
CollectedFrontmatterSequence: TypeAlias = tuple[FrontmatterScalar, ...]
CollectedFrontmatterValue: TypeAlias = FrontmatterScalar | CollectedFrontmatterSequence


@dataclass(frozen=True)
class DomainDiscovery:
    domain_ids: tuple[str, ...]
    diagnostics: tuple[GraphDiagnostic, ...]


@dataclass(frozen=True)
class CollectedDomain:
    nodes: tuple[GraphNode, ...]
    diagnostics: tuple[GraphDiagnostic, ...]
    frontmatter_by_node: Mapping[str, Mapping[str, CollectedFrontmatterValue]]
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
    referenced_values: set[str] = set()

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

        matching = next(
            (
                (rule, variables, match)
                for rule, pattern, variables in templates
                if (match := pattern.fullmatch(logical_path)) is not None and _matched_variables_are_slugs(match, variables)
            ),
            None,
        )
        matching_rule = matching[0] if matching is not None else None
        owned_fields = _owned_identity_fields(matching_rule, matching[1] if matching is not None else (), adapter)
        node_type = "record" if matching_rule is not None else "document"
        subtype_fallback = matching_rule.record_type if matching_rule is not None else "document"
        node = _markdown_node(domain_id, node_type, subtype_fallback, logical_path, frontmatter, adapter, diagnostics)
        nodes.append(node)
        frontmatter_by_node[node.id] = frontmatter
        body_by_node[node.id] = text[body_offset:]
        path_candidates.setdefault(logical_path, set()).add(node.id)
        _index_owned_frontmatter_identities(frontmatter, owned_fields, node.id, identity_candidates)
        if matching is not None:
            _index_template_variable_identities(matching[2], matching[1], node.id, identity_candidates)
        referenced_values.update(
            _frontmatter_reference_values(
                frontmatter,
                owned_fields,
                tuple(matching_rule.required_refs) if matching_rule is not None else (),
            )
        )

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
) -> tuple[tuple[WriteRule, re.Pattern[str], tuple[str, ...]], ...]:
    compiled: list[tuple[WriteRule, re.Pattern[str], tuple[str, ...]]] = []
    for record_type, rule in sorted(rules.items()):
        try:
            normalized = _template_path(rule.path)
            fragments: list[str] = ["^"]
            variables: list[str] = []
            for part in normalized.split("/"):
                match = _PLACEHOLDER_PATTERN.fullmatch(part)
                if match is not None:
                    variable = match.group(1)
                    if variable in variables:
                        raise ValueError("repeated write-rule variable")
                    variables.append(variable)
                    fragments.append(f"(?P<{variable}>{_VARIABLE_SEGMENT_PATTERN})")
                elif "{" in part or "}" in part:
                    raise ValueError("write-rule variables must occupy one full path segment")
                else:
                    fragments.append(re.escape(part))
                fragments.append("/")
            fragments.pop()
            fragments.append("$")
            required_variables = _rule_variable_names(rule.required_vars)
            if required_variables and set(required_variables) != set(variables):
                raise ValueError("write-rule variables do not match required_vars")
            compiled.append((rule, re.compile("".join(fragments)), tuple(variables)))
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


def _rule_variable_names(values: object) -> tuple[str, ...]:
    if not isinstance(values, list) or len(set(values)) != len(values):
        raise ValueError("invalid required_vars")
    names: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _PLACEHOLDER_PATTERN.fullmatch(f"{{{value}}}"):
            raise ValueError("invalid required_vars")
        names.append(value)
    return tuple(names)


def _matched_variables_are_slugs(match: re.Match[str], variables: tuple[str, ...]) -> bool:
    try:
        for variable in variables:
            validate_slug(match.group(variable))
    except ValueError:
        return False
    return True


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


def _owned_identity_fields(
    rule: WriteRule | None, template_variables: tuple[str, ...], adapter: GraphAdapter
) -> frozenset[str]:
    fields = set(template_variables)
    if rule is not None:
        fields.update(_rule_variable_names(rule.required_vars))
    if adapter.defaults.label_field:
        fields.add(adapter.defaults.label_field)
    if rule is not None:
        fields.difference_update(rule.required_refs)
    return frozenset(fields)


def _index_owned_frontmatter_identities(
    frontmatter: Mapping[str, FrontmatterValue], owned_fields: frozenset[str], node_id: str, candidates: dict[str, set[str]]
) -> None:
    for field in sorted(owned_fields):
        identity = _identity_value(frontmatter.get(field))
        if identity is not None:
            candidates.setdefault(identity, set()).add(node_id)


def _index_template_variable_identities(
    match: re.Match[str], variables: tuple[str, ...], node_id: str, candidates: dict[str, set[str]]
) -> None:
    for variable in variables:
        candidates.setdefault(match.group(variable), set()).add(node_id)


def _frontmatter_reference_values(
    frontmatter: Mapping[str, FrontmatterValue], owned_fields: frozenset[str], required_refs: tuple[str, ...]
) -> set[str]:
    values: set[str] = set()
    for key, value in sorted(frontmatter.items()):
        if key in owned_fields:
            continue
        if key.endswith("_id") or key in required_refs:
            values.update(_reference_identity_values(value))
        elif key.endswith("_ids"):
            values.update(_reference_identity_values(value))
    return values


def _reference_identity_values(value: object) -> set[str]:
    if isinstance(value, (list, tuple)):
        return {identity for item in value if (identity := _identity_value(item)) is not None}
    identity = _identity_value(value)
    return {identity} if identity is not None else set()


def _identity_value(value: object) -> str | None:
    if isinstance(value, (list, tuple)):
        return None
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
    entries = _registry_entries(wiki_root, "sources/registry.json", "sources", "source", diagnostics)
    seen_nodes: dict[str, GraphNode] = {}
    indexed_ids: dict[str, set[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            diagnostics.append(
                GraphDiagnostic("warning", "invalid_source_registry_entry", "sources/registry.json", "Source registry entry was ignored")
            )
            continue
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
        existing = seen_nodes.get(node.id)
        if existing is None:
            seen_nodes[node.id] = node
            nodes.append(node)
        else:
            diagnostics.append(
                GraphDiagnostic(
                    "warning",
                    "duplicate_source_registry_path",
                    "sources/registry.json",
                    "Multiple source registry entries resolve to one path",
                )
            )
        identities.setdefault(source_id, set()).add(node.id)
        indexed_ids.setdefault(source_id, set()).add(node.id)
    _diagnose_ambiguous_registry_ids("source", "sources/registry.json", indexed_ids, diagnostics)


def _collect_artifacts(
    wiki_root: Path,
    domain_id: str,
    single_domain_scope: bool,
    nodes: list[GraphNode],
    identities: dict[str, set[str]],
    diagnostics: list[GraphDiagnostic],
) -> None:
    entries = _registry_entries(wiki_root, "artifacts/index.json", "artifacts", "artifact", diagnostics)
    seen_nodes: dict[str, GraphNode] = {}
    indexed_ids: dict[str, set[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            diagnostics.append(
                GraphDiagnostic("warning", "invalid_artifact_registry_entry", "artifacts/index.json", "Artifact index entry was ignored")
            )
            continue
        artifact_id = entry.get("artifact_id")
        path = entry.get("path")
        if not isinstance(artifact_id, str) or not artifact_id or not isinstance(path, str):
            diagnostics.append(GraphDiagnostic("warning", "invalid_artifact_index_entry", "artifacts/index.json", "Artifact index entry was ignored"))
            continue
        logical_path = _safe_registry_path(path, "artifacts/index.json", "invalid_artifact_index_entry", diagnostics)
        if logical_path is None:
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
        node = _node(domain_id, "artifact", _nonempty_string(entry.get("artifact_type"), "artifact"), artifact_id, logical_path)
        if node.id in seen_nodes:
            diagnostics.append(
                GraphDiagnostic(
                    "warning",
                    "duplicate_artifact_registry_path",
                    "artifacts/index.json",
                    "Multiple artifact registry entries resolve to one path",
                )
            )
        else:
            seen_nodes[node.id] = node
            nodes.append(node)
        identities.setdefault(artifact_id, set()).add(node.id)
        indexed_ids.setdefault(artifact_id, set()).add(node.id)
    _diagnose_ambiguous_registry_ids("artifact", "artifacts/index.json", indexed_ids, diagnostics)


def _collect_logs(
    wiki_root: Path,
    domain_id: str,
    profile: Profile,
    nodes: list[GraphNode],
    diagnostics: list[GraphDiagnostic],
) -> None:
    del wiki_root
    if domain_id != profile.id:
        return
    paths: set[str] = set()
    for log_type, rule in sorted(profile.log_rules.items()):
        logical_path = _safe_registry_path(rule.path, "", "invalid_log_path", diagnostics)
        if logical_path is None:
            continue
        if logical_path in paths:
            diagnostics.append(
                GraphDiagnostic("warning", "duplicate_log_path", "", "Multiple log rules resolve to one path")
            )
            continue
        paths.add(logical_path)
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


def _registry_entries(
    wiki_root: Path,
    logical_path: str,
    expected_key: str,
    kind: str,
    diagnostics: list[GraphDiagnostic],
) -> tuple[object, ...]:
    path = wiki_root / logical_path
    if not path.exists():
        return ()
    if path.is_symlink() or not path.is_file():
        diagnostics.append(GraphDiagnostic("warning", f"malformed_{kind}_registry", logical_path, f"{kind.title()} registry was ignored"))
        return ()
    try:
        path.resolve().relative_to(wiki_root.resolve())
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        diagnostics.append(GraphDiagnostic("warning", f"malformed_{kind}_registry", logical_path, f"{kind.title()} registry was ignored"))
        return ()
    if not isinstance(value, dict):
        diagnostics.append(
            GraphDiagnostic("warning", f"invalid_{kind}_registry_root", logical_path, f"{kind.title()} registry root must be an object")
        )
        return ()
    if expected_key not in value:
        diagnostics.append(
            GraphDiagnostic("warning", f"missing_{kind}_registry_entries", logical_path, f"{kind.title()} registry entries are missing")
        )
        return ()
    entries = value[expected_key]
    if not isinstance(entries, list):
        diagnostics.append(
            GraphDiagnostic("warning", f"invalid_{kind}_registry_entries", logical_path, f"{kind.title()} registry entries must be a list")
        )
        return ()
    return tuple(sorted(entries, key=_registry_entry_sort_key))


def _diagnose_ambiguous_registry_ids(
    kind: str, logical_path: str, indexed_ids: Mapping[str, set[str]], diagnostics: list[GraphDiagnostic]
) -> None:
    for node_ids in (indexed_ids[value] for value in sorted(indexed_ids)):
        if len(node_ids) > 1:
            diagnostics.append(
                GraphDiagnostic(
                    "warning",
                    f"ambiguous_{kind}_registry_id",
                    logical_path,
                    f"One {kind} registry ID resolves to multiple paths",
                )
            )


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


def _registry_entry_sort_key(entry: object) -> tuple[str, str, str, str]:
    if not isinstance(entry, dict):
        return ("", "", "", json.dumps(entry, ensure_ascii=True, sort_keys=True, default=repr))
    return (
        str(entry.get("source_id") or entry.get("artifact_id") or ""),
        str(entry.get("path") or ""),
        str(entry.get("source_type") or entry.get("artifact_type") or ""),
        json.dumps(entry, ensure_ascii=True, sort_keys=True, default=repr),
    )


def _diagnostic_sort_key(item: GraphDiagnostic) -> tuple[str, str, str, str]:
    return (item.severity, item.code, item.path, item.message)


def _freeze_mapping(mapping: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType({key: mapping[key] for key in sorted(mapping)})


def _freeze_index(mapping: Mapping[str, tuple[str, ...]]) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({key: tuple(sorted(set(mapping[key]))) for key in sorted(mapping)})


def _freeze_frontmatter_by_node(
    mapping: Mapping[str, Mapping[str, FrontmatterValue]]
) -> Mapping[str, Mapping[str, CollectedFrontmatterValue]]:
    frozen: dict[str, Mapping[str, CollectedFrontmatterValue]] = {}
    for node_id in sorted(mapping):
        values: dict[str, CollectedFrontmatterValue] = {}
        for key, value in sorted(mapping[node_id].items()):
            values[key] = tuple(value) if isinstance(value, list) else value
        frozen[node_id] = MappingProxyType(values)
    return MappingProxyType(frozen)
