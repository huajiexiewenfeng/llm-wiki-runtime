"""Sanitized, deterministic runtime audit events."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .io import atomic_write_text


_ALLOWED_FIELDS = frozenset(
    {"event", "logged_at", "status", "domains", "counts", "warnings", "errors", "output_paths"}
)
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|[/\\]{2}|file:)", re.IGNORECASE)
_DENIED_KEYS = frozenset({"body", "content", "raw", "source", "source_body"})
_DROP = object()


def append_change_event(wiki_root: Path, event: Mapping[str, object]) -> None:
    """Append one allowlisted event without persisting bodies or host paths."""
    if not isinstance(event, Mapping):
        raise ValueError("audit event must be a mapping")
    payload: dict[str, object] = {}
    for key in sorted(_ALLOWED_FIELDS & event.keys()):
        sanitized = _sanitize(event[key])
        if sanitized is not _DROP:
            payload[key] = sanitized
    payload.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    if not isinstance(payload.get("event"), str) or not payload["event"]:
        raise ValueError("audit event name is required")
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    path = Path(wiki_root) / ".meta" / "change-log.jsonl"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write_text(path, existing + line + "\n")


def _sanitize(value: object) -> object:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, str):
        if value.startswith(("/", "\\")) or _ABSOLUTE_PATH.match(value):
            return _DROP
        return value
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            sanitized = _sanitize(item)
            if sanitized is not _DROP:
                result.append(sanitized)
        return result
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key in sorted(
            key for key in value if isinstance(key, str) and key.lower() not in _DENIED_KEYS
        ):
            sanitized = _sanitize(value[key])
            if sanitized is not _DROP:
                result[key] = sanitized
        return result
    return _DROP
