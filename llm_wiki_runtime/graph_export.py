"""Scope-locked graph export transaction."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .audit import append_change_event
from .graph_adapter import default_graph_adapter, graph_adapter_snapshot_path, load_graph_adapter
from .graph_analysis import analyze_domain_graph
from .graph_collect import collect_domain_nodes, discover_domains
from .graph_links import build_domain_edges
from .graph_render import render_domain_html, render_index_html
from .io import atomic_write_json, atomic_write_text
from .locking import ScopeLock
from .profile import load_profile


_WORK_DIRECTORY = re.compile(r"^\.([a-z0-9][a-z0-9-]{0,63})\.(staging|backup)-[a-f0-9]+$")


def export_graphs(
    scope_root: str | Path,
    requested_domain: str | None = None,
    lock_timeout_seconds: int | float = 30,
) -> dict:
    """Export one or all discovered Domains without replacing prior successes on failure."""
    scope_root = Path(scope_root).resolve()
    wiki_root = scope_root / ".llm-wiki"
    with ScopeLock(wiki_root, command="graph-export", timeout_seconds=lock_timeout_seconds):
        profile = load_profile(wiki_root / ".meta" / "profile.yml")
        discovery = discover_domains(wiki_root, profile)
        available = discovery.domain_ids
        if requested_domain is not None and requested_domain not in available:
            return {
                "status": "validation_error",
                "domains": {},
                "errors": ["unknown_domain"],
                "warnings": [],
            }
        domain_ids = (requested_domain,) if requested_domain is not None else available
        graph_root = wiki_root / ".meta" / "graph"
        graph_root.mkdir(parents=True, exist_ok=True)
        _recover_work_directories(graph_root, domain_ids)
        previous = _load_json(graph_root / "graph-manifest.json", {})
        previous_domains = {
            item["id"]: item
            for item in previous.get("domains", [])
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        }
        generated_at = _now()
        results: dict[str, dict[str, object]] = {}
        manifest_domains: list[dict[str, object]] = []
        successful = 0

        for domain_id in domain_ids:
            try:
                adapter_path = graph_adapter_snapshot_path(wiki_root, domain_id)
                adapter = (
                    load_graph_adapter(adapter_path, domain_id)
                    if adapter_path.is_file()
                    else default_graph_adapter(domain_id)
                )
                collected = collect_domain_nodes(wiki_root, profile, adapter, domain_id)
                edges, link_diagnostics = build_domain_edges(collected)
                graph = analyze_domain_graph(
                    domain_id,
                    adapter.display_name or domain_id,
                    collected.nodes,
                    edges,
                    (*collected.diagnostics, *link_diagnostics),
                )
                graph_payload = graph.to_dict()
                json.dumps(graph_payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
                domain_html = render_domain_html(graph_payload)
                _publish_domain(graph_root, domain_id, graph_payload, domain_html)
                counts = {
                    "nodes": int(graph.stats.get("node_count", len(graph.nodes))),
                    "edges": int(graph.stats.get("edge_count", len(graph.edges))),
                }
                warning_codes = sorted({item.code for item in graph.diagnostics if item.severity == "warning"})
                error_codes = sorted({item.code for item in graph.diagnostics if item.severity == "error"})
                entry = {
                    "id": domain_id,
                    "display_name": adapter.display_name or domain_id,
                    "status": "ok",
                    "counts": counts,
                    "warnings": warning_codes,
                    "errors": error_codes,
                    "last_success_at": generated_at,
                    "paths": {
                        "html": f".meta/graph/{domain_id}/graph.html",
                        "json": f".meta/graph/{domain_id}/graph.json",
                    },
                }
                results[domain_id] = dict(entry)
                manifest_domains.append(entry)
                successful += 1
            except (ValueError, TypeError, OSError) as exc:
                code = _stable_error_code(exc)
                prior = previous_domains.get(domain_id, {})
                prior_display_name = prior.get("display_name")
                entry = {
                    "id": domain_id,
                    "display_name": (
                        prior_display_name
                        if isinstance(prior_display_name, str) and not _looks_absolute(prior_display_name)
                        else domain_id
                    ),
                    "status": "failed",
                    "counts": prior.get("counts", {"nodes": 0, "edges": 0}),
                    "warnings": [],
                    "errors": [code],
                }
                if isinstance(prior.get("last_success_at"), str):
                    entry["last_success_at"] = prior["last_success_at"]
                prior_paths = _portable_paths(prior.get("paths"))
                if prior_paths:
                    entry["paths"] = prior_paths
                results[domain_id] = dict(entry)
                manifest_domains.append(entry)

        failed = len(domain_ids) - successful
        status = "ok" if failed == 0 and successful > 0 else "partial_failure" if successful else "validation_error"
        manifest = {
            "schema_version": "v0.1",
            "title": "LLM Wiki graph",
            "generated_at": generated_at,
            "scope_root": str(scope_root),
            "domains": sorted(manifest_domains, key=lambda item: item["id"]),
        }
        output_paths = [
            ".meta/graph/index.html",
            ".meta/graph/graph-manifest.json",
            ".meta/graph/graph-export-report.json",
        ]
        report = {
            "status": status,
            "generated_at": generated_at,
            "domains": results,
            "counts": {"requested": len(domain_ids), "successful": successful, "failed": failed},
            "warnings": [],
            "errors": sorted({code for item in results.values() for code in item.get("errors", [])}),
            "output_paths": output_paths,
        }
        atomic_write_json(graph_root / "graph-export-report.json", report)
        atomic_write_json(graph_root / "graph-manifest.json", manifest)
        atomic_write_text(graph_root / "index.html", render_index_html(manifest))
        append_change_event(
            wiki_root,
            {
                "event": "graph_export",
                "status": status,
                "domains": list(domain_ids),
                "counts": report["counts"],
                "warnings": report["warnings"],
                "errors": report["errors"],
                "output_paths": output_paths,
            },
        )
        return report


def _publish_domain(graph_root: Path, domain_id: str, payload: object, page: str) -> None:
    token = uuid.uuid4().hex
    staging = graph_root / f".{domain_id}.staging-{token}"
    backup = graph_root / f".{domain_id}.backup-{token}"
    final = graph_root / domain_id
    _assert_under(graph_root, staging)
    _assert_under(graph_root, backup)
    staging.mkdir()
    atomic_write_json(staging / "graph.json", payload)
    atomic_write_text(staging / "graph.html", page)
    moved_old = False
    try:
        if final.exists():
            os.replace(final, backup)
            moved_old = True
        os.replace(staging, final)
    except OSError:
        if moved_old and backup.exists() and not final.exists():
            os.replace(backup, final)
        _remove_tree(graph_root, staging)
        raise
    if backup.exists():
        _remove_tree(graph_root, backup)


def _recover_work_directories(graph_root: Path, domain_ids: tuple[str, ...]) -> None:
    if not graph_root.exists():
        return
    for domain_id in domain_ids:
        final = graph_root / domain_id
        backups = sorted(
            (
                child
                for child in graph_root.iterdir()
                if child.is_dir() and (match := _WORK_DIRECTORY.fullmatch(child.name))
                and match.group(1) == domain_id and match.group(2) == "backup"
            ),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        if not final.exists() and backups:
            os.replace(backups.pop(0), final)
        for backup in backups:
            _remove_tree(graph_root, backup)
        for child in list(graph_root.iterdir()):
            match = _WORK_DIRECTORY.fullmatch(child.name)
            if child.is_dir() and match and match.group(1) == domain_id and match.group(2) == "staging":
                _remove_tree(graph_root, child)


def _remove_tree(root: Path, path: Path) -> None:
    _assert_under(root, path)
    if path.exists():
        shutil.rmtree(path)


def _assert_under(root: Path, path: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("graph work path escapes graph root")


def _stable_error_code(exc: Exception) -> str:
    if isinstance(exc, OSError):
        return "domain_io_error"
    if isinstance(exc, TypeError):
        return "domain_serialization_error"
    return "domain_validation_error"


def _portable_paths(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key in ("html", "json"):
        path = value.get(key)
        if isinstance(path, str) and path and not _looks_absolute(path) and ".." not in Path(path).parts:
            result[key] = path.replace("\\", "/")
    return result


def _looks_absolute(value: str) -> bool:
    return value.startswith(("/", "\\")) or (len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in "\\/")


def _load_json(path: Path, fallback: object) -> object:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
