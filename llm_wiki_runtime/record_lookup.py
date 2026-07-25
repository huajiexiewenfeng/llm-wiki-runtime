from __future__ import annotations

import math
import unicodedata
from pathlib import Path

from .frontmatter import FrontmatterScalar, FrontmatterValue, parse_frontmatter
from .io import sha256_file
from .policy import assert_read_allowed, load_domain_policies
from .profile import load_active_profile
from .read_paths import iter_readable_files


MAX_FRONTMATTER_BYTES = 64 * 1024
LookupScalar = str | int | float | bool


def _is_lookup_scalar(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str)


def _scalar_equal(stored: FrontmatterScalar, lookup: LookupScalar) -> bool:
    if isinstance(stored, str) and isinstance(lookup, str):
        return unicodedata.normalize("NFC", stored) == unicodedata.normalize("NFC", lookup)
    return type(stored) is type(lookup) and stored == lookup


def _field_matches(value: FrontmatterValue | None, lookup: LookupScalar) -> bool:
    if isinstance(value, list):
        return any(_scalar_equal(item, lookup) for item in value)
    return _scalar_equal(value, lookup)


def _read_frontmatter(path: Path) -> tuple[dict[str, FrontmatterValue] | None, str | None]:
    with path.open("rb") as handle:
        data = handle.read(MAX_FRONTMATTER_BYTES + 1)
    lines = data.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        return None, None

    end = len(lines[0])
    for line in lines[1:]:
        end += len(line)
        if end > MAX_FRONTMATTER_BYTES:
            return None, "frontmatter_too_large"
        if line.rstrip(b"\r\n") == b"---":
            try:
                text = data[:end].decode("utf-8")
                metadata, _ = parse_frontmatter(text)
            except (UnicodeDecodeError, ValueError):
                return None, "frontmatter_invalid"
            return metadata, None

    if len(data) > MAX_FRONTMATTER_BYTES:
        return None, "frontmatter_too_large"
    return None, "frontmatter_missing_closing_delimiter"


def _warning(code: str, relative_path: str) -> dict[str, str]:
    return {"code": code, "path": relative_path}


def find_records(
    scope_root: Path,
    record_type: str,
    lookup_value: LookupScalar,
    *,
    caller_domain: str | None = None,
    target_domain: str | None = None,
    domain_policies: dict | None = None,
    caller_groups: list[str] | None = None,
) -> dict:
    if not _is_lookup_scalar(lookup_value):
        raise ValueError("lookup value must be a non-null finite JSON scalar")

    profile = load_active_profile(scope_root)
    rule = profile.record_lookup.get(record_type)
    if rule is None:
        raise ValueError(f"record lookup is not declared: {record_type}")

    policies = load_domain_policies(domain_policies)
    allowed, reason = assert_read_allowed(
        caller_domain,
        target_domain,
        policies,
        caller_groups,
    )
    if not allowed:
        return {
            "status": "read_denied",
            "reason": reason,
            "record_type": record_type,
            "matches": [],
            "context_refs": [],
            "warnings": [],
            "truncated": False,
        }

    wiki_root = scope_root / ".llm-wiki"
    matches: list[dict] = []
    warnings: list[dict[str, str]] = []
    matched_count = 0

    for path in iter_readable_files(
        wiki_root,
        profile.context_pack.include,
        profile.context_pack.exclude,
    ):
        relative = path.relative_to(wiki_root).as_posix()
        metadata, warning_code = _read_frontmatter(path)
        if warning_code is not None:
            warnings.append(_warning(warning_code, relative))
            continue
        if metadata is None or metadata.get("record_type") != record_type:
            continue
        if not any(
            _field_matches(metadata.get(field), lookup_value)
            for field in rule.match_fields
        ):
            continue

        identity = metadata.get(rule.identity_field)
        display = metadata.get(rule.display_field)
        if not _is_lookup_scalar(identity) or not _is_lookup_scalar(display):
            warnings.append(_warning("record_identity_invalid", relative))
            continue

        matched_count += 1
        if len(matches) >= rule.max_results:
            continue
        fields = {
            field: metadata[field]
            for field in rule.return_fields
            if field in metadata
        }
        matches.append(
            {
                "path": relative,
                "checksum": "sha256:" + sha256_file(path),
                "identity": identity,
                "display": display,
                "fields": fields,
            }
        )

    status = (
        "not_found"
        if matched_count == 0
        else "found"
        if matched_count == 1
        else "multiple_matches"
    )
    return {
        "status": status,
        "record_type": record_type,
        "lookup_value": lookup_value,
        "matches": matches,
        "context_refs": [
            {"path": match["path"], "checksum": match["checksum"]}
            for match in matches
        ],
        "warnings": warnings,
        "truncated": matched_count > len(matches),
    }
