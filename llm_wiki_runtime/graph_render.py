"""Self-contained, offline HTML rendering for deterministic graph payloads."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from importlib import resources


_ASSET_ROOT = resources.files("llm_wiki_runtime").joinpath("assets", "graph")
_DOMAIN_TEMPLATE = "domain.html.tpl"
_INDEX_TEMPLATE = "index.html.tpl"
_GRAPH_CSS = "graph.css"
_GRAPH_APP = "graph-app.bundle.js"
_INDEX_APP = "index-app.bundle.js"

_EXTERNAL_PATTERNS = (
    re.compile(r"<script\b[^>]*\bsrc\s*=", re.IGNORECASE),
    re.compile(r"<link\b[^>]*\bhref\s*=", re.IGNORECASE),
    re.compile(r"\bhttps?://", re.IGNORECASE),
    re.compile(r"(?:src|href|action)\s*=\s*(['\"])\s*//", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"\bXMLHttpRequest\b"),
    re.compile(r"\bWebSocket\b"),
    # A property method such as graph.import(...) is not a module import.
    re.compile(r"(?<![\w$.}])import\s*\("),
)

_NODE_FIELDS = frozenset(
    {"id", "type", "subtype", "label", "summary", "status", "tags", "path", "metadata", "x", "y", "search_text"}
)
_EDGE_FIELDS = frozenset({"id", "source", "target", "type", "label", "evidence", "metadata"})
_DIAGNOSTIC_FIELDS = frozenset({"severity", "code", "path", "message"})


def render_domain_html(payload: Mapping[str, object]) -> str:
    """Return a portable graph page with its data, CSS, and JS embedded."""
    graph_payload = _domain_payload(payload)
    title = _domain_title(graph_payload)
    return _render(
        _DOMAIN_TEMPLATE,
        {
            "__PAGE_TITLE__": html.escape(title, quote=True),
            "__GRAPH_CSS__": _read_asset(_GRAPH_CSS),
            "__GRAPH_DATA__": _embedded_json(graph_payload),
            "__GRAPH_APP__": _read_asset(_GRAPH_APP),
        },
    )


def render_index_html(manifest: Mapping[str, object]) -> str:
    """Return a portable entry page which only links to relative domain pages."""
    title = manifest.get("title") if isinstance(manifest.get("title"), str) else "Domain graphs"
    return _render(
        _INDEX_TEMPLATE,
        {
            "__PAGE_TITLE__": html.escape(title, quote=True),
            "__GRAPH_CSS__": _read_asset(_GRAPH_CSS),
            "__GRAPH_INDEX_DATA__": _embedded_json(manifest),
            "__DOMAIN_NAV__": _domain_navigation(manifest),
            "__INDEX_APP__": _read_asset(_INDEX_APP),
        },
    )


def assert_self_contained_html(page: str) -> None:
    """Reject rendered pages that would load code, data, or URLs externally."""
    if not isinstance(page, str) or not page:
        raise ValueError("rendered graph HTML must be a non-empty string")
    for pattern in _EXTERNAL_PATTERNS:
        if pattern.search(page):
            raise ValueError("rendered graph HTML is not self-contained")


def _domain_title(payload: Mapping[str, object]) -> str:
    domain = payload.get("domain")
    if isinstance(domain, Mapping):
        display_name = domain.get("display_name")
        if isinstance(display_name, str) and display_name:
            return display_name
        domain_id = domain.get("id")
        if isinstance(domain_id, str) and domain_id:
            return domain_id
    return "Domain graph"


def _embedded_json(value: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("graph payload must be JSON serializable") from exc
    return (
        encoded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _domain_navigation(manifest: Mapping[str, object]) -> str:
    domains = manifest.get("domains")
    if not isinstance(domains, list):
        return ""
    links: list[str] = []
    for domain in domains:
        if not isinstance(domain, Mapping):
            continue
        domain_id = domain.get("id")
        if not isinstance(domain_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", domain_id):
            continue
        display_name = domain.get("display_name")
        label = display_name if isinstance(display_name, str) and display_name else domain_id
        links.append(f'<a href="{domain_id}/graph.html">{html.escape(label, quote=False)}</a>')
    return "".join(links)


def _render(template_name: str, replacements: Mapping[str, str]) -> str:
    template = _read_asset(template_name)
    rendered = template
    for token, value in replacements.items():
        if template.count(token) != 1:
            raise ValueError(f"graph template token must occur exactly once: {token}")
        rendered = rendered.replace(token, value, 1)
    if any(token in rendered for token in replacements):
        raise ValueError("graph template has unreplaced tokens")
    assert_self_contained_html(rendered)
    return rendered


def _read_asset(name: str) -> str:
    return _ASSET_ROOT.joinpath(name).read_text(encoding="utf-8")


def _domain_payload(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("graph payload must be a mapping")
    return {
        "diagnostics": _records(payload.get("diagnostics"), _DIAGNOSTIC_FIELDS),
        "domain": _safe_mapping(payload.get("domain")),
        "edges": _records(payload.get("edges"), _EDGE_FIELDS),
        "nodes": _records(payload.get("nodes"), _NODE_FIELDS),
        "schema_version": payload.get("schema_version"),
        "stats": _safe_mapping(payload.get("stats")),
    }


def _records(value: object, fields: frozenset[str]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [{key: item[key] for key in sorted(fields & item.keys())} for item in value if isinstance(item, Mapping)]


def _safe_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in sorted(value) if isinstance(key, str) and key not in {"body", "content", "source"}}
