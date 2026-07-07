from __future__ import annotations

from pathlib import Path

from .models import ContextPackRule, Profile, WriteRule


def parse_scalar(value: str):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        body = value[1:-1].strip()
        if not body:
            return []
        return [item.strip().strip('"').strip("'") for item in body.split(",")]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value.strip('"').strip("'")


def load_profile(path: Path) -> Profile:
    lines = path.read_text(encoding="utf-8").splitlines()
    profile_values: dict[str, object] = {}
    directories: list[str] = []
    write_rules: dict[str, WriteRule] = {}
    context_values: dict[str, object] = {}
    artifact_types: list[str] = []

    section: str | None = None
    current_record: str | None = None
    current_rule: dict[str, object] = {}
    in_directories = False
    in_context_pack = False

    def flush_record() -> None:
        nonlocal current_record, current_rule
        if current_record:
            write_rules[current_record] = WriteRule(
                record_type=current_record,
                path=str(current_rule.get("path", "")),
                mode=str(current_rule.get("mode", "create_only")),
                required_vars=list(current_rule.get("required_vars", [])),
                required_refs=list(current_rule.get("required_refs", [])),
                register_artifact=bool(current_rule.get("register_artifact", False)),
                artifact_type=current_rule.get("artifact_type") if current_rule.get("artifact_type") else None,
            )
        current_record = None
        current_rule = {}

    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            flush_record()
            section = stripped[:-1]
            in_directories = False
            in_context_pack = False
            continue
        if section == "profile" and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            profile_values[key] = parse_scalar(value)
        elif section == "layout":
            if indent == 2 and stripped == "directories:":
                in_directories = True
            elif in_directories and stripped.startswith("- "):
                directories.append(stripped[2:].strip())
        elif section == "write_rules":
            if indent == 4 and stripped.endswith(":") and stripped != "records:":
                flush_record()
                current_record = stripped[:-1]
            elif current_record and indent >= 6 and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_rule[key] = parse_scalar(value)
        elif section == "read_rules":
            if indent == 2 and stripped == "context_pack:":
                in_context_pack = True
            elif in_context_pack and indent >= 4 and ":" in stripped:
                key, value = stripped.split(":", 1)
                context_values[key] = parse_scalar(value)
        elif section == "artifacts" and indent == 2 and stripped.startswith("types:"):
            _, value = stripped.split(":", 1)
            artifact_types = list(parse_scalar(value))
    flush_record()

    context_pack = ContextPackRule(
        include=list(context_values.get("include", [])),
        exclude=list(context_values.get("exclude", [".meta/**"])),
        max_files=int(context_values.get("max_files", 30)),
        max_chars_per_file=int(context_values.get("max_chars_per_file", 4000)),
    )
    return Profile(
        id=str(profile_values.get("id", "")),
        version=str(profile_values.get("version", "")),
        display_name=profile_values.get("display_name") if profile_values.get("display_name") else None,
        scope_type=profile_values.get("scope_type") if profile_values.get("scope_type") else None,
        privacy_default=profile_values.get("privacy_default") if profile_values.get("privacy_default") else None,
        directories=directories,
        write_rules=write_rules,
        context_pack=context_pack,
        artifact_types=artifact_types,
    )
