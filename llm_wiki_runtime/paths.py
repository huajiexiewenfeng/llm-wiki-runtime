from __future__ import annotations

import re
from pathlib import Path

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_slug(value: str) -> str:
    if not value or value in {".", ".."} or len(value) > 128:
        raise ValueError(f"unsafe path variable: {value!r}")
    if "/" in value or "\\" in value or ":" in value:
        raise ValueError(f"unsafe path variable: {value!r}")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(f"unsafe path variable: {value!r}")
    if not SLUG_RE.match(value):
        raise ValueError(f"unsafe path variable: {value!r}")
    return value


def render_logical_path(template: str, variables: dict[str, str]) -> Path:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", validate_slug(str(value)))
    if "{" in rendered or "}" in rendered:
        raise ValueError(f"unresolved path template: {template}")
    return Path(rendered)


def ensure_under_root(root: Path, logical_path: Path) -> Path:
    if logical_path.is_absolute():
        raise ValueError("absolute logical paths are not allowed")
    target = (root / logical_path).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes wiki root: {logical_path}") from exc
    return target
