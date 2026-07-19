from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ConfigResult:
    status: str
    enabled: bool
    scope_root: Path
    wiki_root: Path | None
    storage_mode: str | None
    scope_id: str | None
    primary_profile: str | None
    wiki_home: Path | None = None
    scope_type: str | None = None
    privacy: str | None = None
    fallback_mode: str = "markdown"


@dataclass(frozen=True)
class WriteRule:
    record_type: str
    path: str
    mode: str
    required_vars: list[str] = field(default_factory=list)
    required_refs: list[str] = field(default_factory=list)
    register_artifact: bool = False
    artifact_type: str | None = None


@dataclass(frozen=True)
class ContextPackRule:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=lambda: [".meta/**"])
    max_files: int = 30
    max_chars_per_file: int = 4000


@dataclass(frozen=True)
class LogRule:
    log_type: str
    path: str
    mode: str = "append_only"


@dataclass(frozen=True)
class Profile:
    id: str
    version: str
    display_name: str | None = None
    scope_type: str | None = None
    privacy_default: str | None = None
    directories: list[str] = field(default_factory=list)
    write_rules: dict[str, WriteRule] = field(default_factory=dict)
    context_pack: ContextPackRule = field(default_factory=ContextPackRule)
    artifact_types: list[str] = field(default_factory=list)
    log_rules: dict[str, LogRule] = field(default_factory=dict)
