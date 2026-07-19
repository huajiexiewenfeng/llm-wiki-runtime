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
from .policy import assert_read_allowed, effective_instruction_policy, load_domain_policies
from .profile import load_active_profile, load_profile


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


SOURCE_METADATA_KEYS = {
    "excerpted",
    "thread_id",
    "selections",
    "confirmed_at",
}
SOURCE_SELECTION_KEYS = {
    "turn_id",
    "item_id",
    "start",
    "end",
    "original_message_checksum",
}


def validate_source_metadata(metadata: dict | None) -> dict:
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("source metadata must be an object")
    result = dict(metadata or {})
    unexpected = sorted(set(result) - SOURCE_METADATA_KEYS)
    if unexpected:
        raise ValueError(f"unsupported source metadata fields: {unexpected}")

    excerpted = result.get("excerpted")
    if excerpted is not None and not isinstance(excerpted, bool):
        raise ValueError("source metadata excerpted must be boolean")
    thread_id = result.get("thread_id")
    if thread_id is not None and (not isinstance(thread_id, str) or not thread_id):
        raise ValueError("source metadata thread_id must be a non-empty string")
    selections = result.get("selections", [])
    if not isinstance(selections, list):
        raise ValueError("source metadata selections must be a list")
    if excerpted and (not thread_id or not selections):
        raise ValueError("excerpt metadata requires thread_id and selections")
    confirmed_at = result.get("confirmed_at")
    if confirmed_at is not None and (not isinstance(confirmed_at, str) or not confirmed_at):
        raise ValueError("source metadata confirmed_at must be a non-empty string")

    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError("source metadata selection must be an object")
        unexpected_selection = sorted(set(selection) - SOURCE_SELECTION_KEYS)
        if unexpected_selection:
            raise ValueError(f"unsupported source selection fields: {unexpected_selection}")
        missing = sorted(SOURCE_SELECTION_KEYS - set(selection))
        if missing:
            raise ValueError(f"missing source selection fields: {missing}")
        if type(selection["start"]) is not int or type(selection["end"]) is not int:
            raise ValueError("source selection start/end must be integers")
        if selection["start"] < 0 or selection["end"] <= selection["start"]:
            raise ValueError("source selection range is invalid")
        for key in ("turn_id", "item_id", "original_message_checksum"):
            if not isinstance(selection[key], str) or not selection[key]:
                raise ValueError(f"source selection {key} must be a non-empty string")
    return result


def copy_source(
    wiki_root: Path,
    source: Path,
    logical_path: str,
    source_type: str,
    metadata: dict | None = None,
) -> dict:
    controlled_metadata = validate_source_metadata(metadata)
    checksum = sha256_file(source)
    source_id = "src-" + checksum[:12]
    with ScopeLock(wiki_root, command="copy-source"):
        target = ensure_under_root(wiki_root, Path(logical_path))
        target_exists = target.exists()
        if target_exists and sha256_file(target) != checksum:
            raise FileExistsError(f"source target already exists with different content: {logical_path}")

        registry_path = wiki_root / "sources" / "registry.json"
        registry = load_json(registry_path, {"sources": []})
        existing = next(
            (
                item
                for item in registry["sources"]
                if item.get("checksum") == checksum and item.get("path") == logical_path
            ),
            None,
        )
        if existing is not None:
            if not target_exists:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                status = "ok"
            else:
                status = "already_exists"
            return {
                "status": status,
                "source_id": existing["source_id"],
                "path": existing["path"],
                "checksum": existing["checksum"],
            }

        if not target_exists:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        record = {
            "source_id": source_id,
            "source_type": source_type,
            "path": logical_path,
            "checksum": checksum,
            "registered_at": now_iso(),
        }
        if controlled_metadata:
            record["metadata"] = controlled_metadata
        registry["sources"].append(record)
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


def append_log_unlocked(wiki_root: Path, logical_log_path: str, record: dict) -> dict:
    target = ensure_under_root(wiki_root, Path(logical_log_path))
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"logged_at": now_iso(), **record}, ensure_ascii=False, sort_keys=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    atomic_write_text(target, existing + line + "\n")
    return {"status": "ok", "path": logical_log_path}


def append_log(wiki_root: Path, logical_log_path: str, record: dict) -> dict:
    with ScopeLock(wiki_root, command="append-log"):
        return append_log_unlocked(wiki_root, logical_log_path, record)


def append_profile_log(
    scope_root: Path,
    profile_path: Path | None,
    log_type: str,
    record: dict,
) -> dict:
    profile = load_active_profile(scope_root, profile_path)
    rule = profile.log_rules.get(log_type)
    if rule is None:
        raise ValueError(f"undeclared log type: {log_type}")
    if rule.mode != "append_only":
        raise ValueError(f"log type is not append_only: {log_type}")
    event_id = record.get("event_id")
    if event_id is not None and (not isinstance(event_id, str) or not event_id):
        raise ValueError("event_id must be a non-empty string")

    wiki_root = scope_root / ".llm-wiki"
    target = ensure_under_root(wiki_root, Path(rule.path))
    with ScopeLock(wiki_root, command="append-log"):
        if event_id and target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                if line and json.loads(line).get("event_id") == event_id:
                    return {
                        "status": "already_exists",
                        "path": rule.path,
                        "log_type": log_type,
                        "event_id": event_id,
                    }
        payload = append_log_unlocked(wiki_root, rule.path, record)
        return {**payload, "log_type": log_type}


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
        snapshot_path = wiki_root / ".meta" / "profile.yml"
        old_text = snapshot_path.read_text(encoding="utf-8") if snapshot_path.exists() else None
        new_text = profile_path.read_text(encoding="utf-8")
        atomic_write_text(snapshot_path, new_text)
        if old_text is not None and old_text != new_text:
            append_profile_snapshot_log(wiki_root, profile.id)
        return {"status": "ok", "profile": profile.id, "wiki_root": str(wiki_root)}


def append_profile_snapshot_log(wiki_root: Path, profile_id: str) -> None:
    path = wiki_root / ".meta" / "profile-snapshot-log.jsonl"
    line = json.dumps(
        {"logged_at": now_iso(), "event": "profile_snapshot_refreshed", "profile": profile_id},
        ensure_ascii=False,
        sort_keys=True,
    )
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write_text(path, existing + line + "\n")


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
    profile_path: Path | None,
    record_type: str,
    variables: dict[str, str],
    refs: dict,
    content_file: Path,
) -> dict:
    profile = load_active_profile(scope_root, profile_path)
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
            return {
                "status": "already_exists",
                "record_type": record_type,
                "path": str(logical_path).replace("\\", "/"),
                "checksum": sha256_file(target),
            }
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


def matches_any_filter(path: str, filters: list[str] | None) -> bool:
    if not filters:
        return True
    return any(path == item or fnmatch.fnmatch(path, item) for item in filters)


def sort_context_paths(paths: list[Path], wiki_root: Path, order: str) -> list[Path]:
    if order == "mtime_desc":
        return sorted(paths, key=lambda item: (-item.stat().st_mtime, item.relative_to(wiki_root).as_posix()))
    return sorted(paths, key=lambda item: item.relative_to(wiki_root).as_posix())


DATA_ONLY_RISK_TERMS = [
    "ignore previous instructions",
    "system prompt",
    "developer message",
    "execute command",
    "delete files",
    "you must",
    "do not follow user",
    "忽略之前的指令",
    "执行以下命令",
    "删除文件",
    "不要听用户",
]


def data_only_flags(text: str) -> list[str]:
    lowered = text.lower()
    for term in DATA_ONLY_RISK_TERMS:
        if term.lower() in lowered:
            return ["instruction_like_text"]
    return []


def load_context_pack(
    wiki_root: Path,
    include: list[str],
    exclude: list[str],
    max_files: int,
    max_chars_per_file: int,
    path_filters: list[str] | None = None,
    glob_filters: list[str] | None = None,
    order: str = "path_asc",
    policy: str | None = None,
    caller_domain: str | None = None,
    target_domain: str | None = None,
    domain_policies: dict | None = None,
    caller_groups: list[str] | None = None,
) -> dict:
    policies = load_domain_policies(domain_policies)
    allowed, reason = assert_read_allowed(caller_domain, target_domain, policies, caller_groups)
    if not allowed:
        return {
            "status": "read_denied",
            "reason": reason,
            "items": [],
            "included_count": 0,
            "excluded_count": 0,
            "context_refs": [],
            "warnings": [f"{caller_domain} is not allowed to read {target_domain}"],
            "next_actions": ["ask the architect to update domain_policies.readable_by"],
        }
    effective_policy = effective_instruction_policy(target_domain, policies, default=policy or "trusted_content")
    effective_exclude = list(dict.fromkeys([*exclude, ".meta/**"]))
    eligible_paths: list[str] = []
    items = []
    candidates = [path for path in wiki_root.rglob("*") if path.is_file()]
    for path in sort_context_paths(candidates, wiki_root, order):
        if not path.is_file():
            continue
        rel = path.relative_to(wiki_root).as_posix()
        if not is_included(rel, include) or is_excluded(rel, effective_exclude):
            continue
        eligible_paths.append(rel)
        if not matches_any_filter(rel, path_filters) or not matches_any_filter(rel, glob_filters):
            continue
        if len(items) >= max_files:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]
        checksum = "sha256:" + sha256_file(path)
        item = {"path": rel, "content": text, "checksum": checksum}
        if effective_policy == "data_only":
            risk_flags = data_only_flags(text)
            item.update(
                {
                    "instruction_policy": "data_only",
                    "sanitized": bool(risk_flags),
                    "risk_flags": risk_flags,
                }
            )
        else:
            item.update(
                {
                    "instruction_policy": "trusted_content",
                    "sanitized": False,
                    "risk_flags": [],
                }
            )
        items.append(item)
    context_refs = [{"path": item["path"], "checksum": item["checksum"]} for item in items]
    return {
        "status": "ok",
        "items": items,
        "included_count": len(items),
        "excluded_count": max(0, len(eligible_paths) - len(items)),
        "context_refs": context_refs,
    }
