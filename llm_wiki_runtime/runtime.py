from __future__ import annotations

import fnmatch
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import runtime_config_path
from .io import atomic_write_json, atomic_write_text, sha256_file
from .locking import ScopeLock
from .paths import ensure_under_root, render_logical_path
from .profile import load_profile


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_runtime_config_text() -> str:
    path = runtime_config_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def merge_home_config(existing: str, home: Path) -> str:
    remaining = [line for line in existing.splitlines() if not line.startswith("home:")]
    lines = [f"home: {home}", *remaining]
    return "\n".join(line for line in lines if line.strip()) + "\n"


def remove_profile_block(existing: str, profile: str) -> str:
    lines = existing.splitlines()
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "profiles:":
            output.append(line)
            i += 1
            while i < len(lines) and (not lines[i] or lines[i].startswith(" ")):
                if lines[i] == f"  {profile}:":
                    i += 1
                    while i < len(lines) and (not lines[i] or lines[i].startswith("    ")):
                        i += 1
                    continue
                output.append(lines[i])
                i += 1
            continue
        output.append(line)
        i += 1
    return "\n".join(line for line in output if line.strip())


def merge_profile_decline(existing: str, profile: str) -> str:
    cleaned = remove_profile_block(existing, profile)
    lines = cleaned.splitlines() if cleaned else []
    if "profiles:" not in lines:
        lines.append("profiles:")
    lines.extend(
        [
            f"  {profile}:",
            "    enabled: false",
            "    default_storage_mode: home",
            f"    declined_at: {now_iso()}",
        ]
    )
    return "\n".join(lines) + "\n"


def init_home(home: Path) -> dict:
    config = runtime_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config, merge_home_config(read_runtime_config_text(), home))
    home.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "wiki_home": str(home)}


def record_decline(profile: str, storage_mode: str, scope_root: Path) -> dict:
    if storage_mode == "home":
        config = runtime_config_path()
        config.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(config, merge_profile_decline(read_runtime_config_text(), profile))
        return {"status": "disabled", "profile": profile, "storage_mode": "home"}
    target = scope_root / ".llm-wiki.yml"
    atomic_write_text(target, "llm_wiki:\n  enabled: false\n")
    return {"status": "disabled", "profile": profile, "storage_mode": "local"}


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def copy_source(wiki_root: Path, source: Path, logical_path: str, source_type: str) -> dict:
    with ScopeLock(wiki_root, command="copy-source"):
        target = ensure_under_root(wiki_root, Path(logical_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        checksum = sha256_file(target)
        source_id = "src-" + checksum[:12]
        registry_path = wiki_root / "sources" / "registry.json"
        registry = load_json(registry_path, {"sources": []})
        registry["sources"].append(
            {
                "source_id": source_id,
                "source_type": source_type,
                "path": logical_path,
                "checksum": checksum,
                "registered_at": now_iso(),
            }
        )
        atomic_write_json(registry_path, registry)
        return {"status": "ok", "source_id": source_id, "path": logical_path, "checksum": checksum}


def register_artifact_unlocked(wiki_root: Path, record: dict) -> dict:
    index_path = wiki_root / "artifacts" / "index.json"
    index = load_json(index_path, {"artifacts": []})
    enriched = dict(record)
    enriched["registered_at"] = now_iso()
    index["artifacts"].append(enriched)
    atomic_write_json(index_path, index)
    return {"status": "ok", "artifact_id": record["artifact_id"]}


def register_artifact(wiki_root: Path, record: dict) -> dict:
    with ScopeLock(wiki_root, command="register-artifact"):
        return register_artifact_unlocked(wiki_root, record)


def append_log(wiki_root: Path, logical_log_path: str, record: dict) -> dict:
    with ScopeLock(wiki_root, command="append-log"):
        target = ensure_under_root(wiki_root, Path(logical_log_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"logged_at": now_iso(), **record}, ensure_ascii=False, sort_keys=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        atomic_write_text(target, existing + line + "\n")
        return {"status": "ok", "path": logical_log_path}


def init_profile(scope_root: Path, profile_path: Path, storage_mode: str, scope_id: str | None = None) -> dict:
    profile = load_profile(profile_path)
    wiki_root = scope_root / ".llm-wiki"
    with ScopeLock(wiki_root, command="init-profile"):
        wiki_root.mkdir(parents=True, exist_ok=True)
        (wiki_root / ".meta").mkdir(parents=True, exist_ok=True)
        for directory in profile.directories:
            ensure_under_root(wiki_root, Path(directory)).mkdir(parents=True, exist_ok=True)
        config = "\n".join(
            [
                "llm_wiki:",
                "  enabled: true",
                f"  storage_mode: {storage_mode}",
                "  storage: .llm-wiki",
                f"  scope_id: {scope_id or profile.id}",
                f"  primary_profile: {profile.id}",
                f"  scope_type: {profile.scope_type or ''}",
                f"  privacy: {profile.privacy_default or ''}",
                "",
            ]
        )
        atomic_write_text(scope_root / ".llm-wiki.yml", config)
        return {"status": "ok", "profile": profile.id, "wiki_root": str(wiki_root)}


def assert_source_exists(wiki_root: Path, source_id: str) -> None:
    registry_path = wiki_root / "sources" / "registry.json"
    registry = load_json(registry_path, {"sources": []})
    if not any(item.get("source_id") == source_id for item in registry["sources"]):
        raise ValueError(f"unknown source_id: {source_id}")


def validate_refs(wiki_root: Path, required_refs: list[str], refs: dict) -> None:
    for ref in required_refs:
        if ref not in refs:
            raise ValueError(f"missing required ref: {ref}")
        value = refs[ref]
        if value == "" or value == []:
            raise ValueError(f"empty required ref: {ref}")
        values = value if isinstance(value, list) else [value]
        if not all(isinstance(item, str) and item for item in values):
            raise ValueError(f"invalid required ref: {ref}")
        if ref == "source_id":
            for source_id in values:
                assert_source_exists(wiki_root, source_id)


def write_record(
    scope_root: Path,
    profile_path: Path,
    record_type: str,
    variables: dict[str, str],
    refs: dict,
    content_file: Path,
) -> dict:
    profile = load_profile(profile_path)
    if record_type not in profile.write_rules:
        raise ValueError(f"unknown record type: {record_type}")
    rule = profile.write_rules[record_type]
    for var in rule.required_vars:
        if var not in variables:
            raise ValueError(f"missing required variable: {var}")
    wiki_root = scope_root / ".llm-wiki"
    logical_path = render_logical_path(rule.path, variables)
    target = ensure_under_root(wiki_root, logical_path)
    content = content_file.read_text(encoding="utf-8")
    with ScopeLock(wiki_root, command="write-record"):
        validate_refs(wiki_root, rule.required_refs, refs)
        target.parent.mkdir(parents=True, exist_ok=True)
        if rule.mode == "create_only" and target.exists():
            raise FileExistsError(str(target))
        old_checksum = sha256_file(target) if target.exists() else None
        if rule.mode == "append_only":
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            atomic_write_text(target, existing + content)
        else:
            atomic_write_text(target, content)
        checksum = sha256_file(target)
        if rule.mode == "update_allowed" and old_checksum and old_checksum != checksum:
            append_meta_change_log(wiki_root, record_type, str(logical_path), old_checksum, checksum)
        if rule.register_artifact:
            register_artifact_unlocked(
                wiki_root,
                {
                    "artifact_id": f"{record_type}-{checksum[:12]}",
                    "artifact_type": rule.artifact_type or record_type,
                    "path": str(logical_path).replace("\\", "/"),
                    "checksum": checksum,
                },
            )
        return {"status": "ok", "record_type": record_type, "path": str(logical_path).replace("\\", "/"), "checksum": checksum}


def append_meta_change_log(wiki_root: Path, record_type: str, logical_path: str, old_checksum: str, new_checksum: str) -> None:
    path = wiki_root / ".meta" / "change-log.jsonl"
    line = json.dumps(
        {
            "logged_at": now_iso(),
            "record_type": record_type,
            "path": logical_path.replace("\\", "/"),
            "old_checksum": old_checksum,
            "new_checksum": new_checksum,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write_text(path, existing + line + "\n")


def is_excluded(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def is_included(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def load_context_pack(
    wiki_root: Path,
    include: list[str],
    exclude: list[str],
    max_files: int,
    max_chars_per_file: int,
) -> dict:
    effective_exclude = list(dict.fromkeys([*exclude, ".meta/**"]))
    items = []
    for path in sorted(wiki_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(wiki_root).as_posix()
        if not is_included(rel, include) or is_excluded(rel, effective_exclude):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]
        items.append({"path": rel, "content": text})
        if len(items) >= max_files:
            break
    return {"status": "ok", "items": items}
