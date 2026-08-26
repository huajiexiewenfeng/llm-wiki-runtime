from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import Profile
from .principal_registry import resolve_principal
from .profile import parse_scalar


CONTRACT_KINDS = ("record_type", "artifact_type", "log_type")
SUPPORTED_MAPPING_VERSIONS = frozenset({"v0.1", "v0.2"})
OWNER_FIELDS = frozenset({"owner_skill_id", "owner_principal_id"})
REQUIRED_MAPPING_FIELDS = {
    "id",
    "version",
    "domain",
    "source_types",
    "instruction_ref",
}


def load_ingest_mapping(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    mapping_values: dict[str, object] = {}
    seen_owner_fields: set[str] = set()
    products: list[dict] = []
    section: str | None = None
    current_product: dict | None = None

    def flush_product() -> None:
        nonlocal current_product
        if current_product is None:
            return
        unsupported = sorted(set(current_product) - set(CONTRACT_KINDS))
        if unsupported:
            raise ValueError(f"unsupported mapping product fields: {unsupported}")
        kinds = [kind for kind in CONTRACT_KINDS if kind in current_product]
        if len(kinds) != 1:
            raise ValueError("mapping product must declare exactly one contract kind")
        value = current_product[kinds[0]]
        if not isinstance(value, str) or not value:
            raise ValueError(f"mapping product {kinds[0]} must be a non-empty string")
        products.append({kinds[0]: value})
        current_product = None

    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            flush_product()
            section = stripped[:-1]
            continue
        if section == "mapping" and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key in OWNER_FIELDS:
                if key in seen_owner_fields:
                    raise ValueError(f"duplicate owner field: {key}")
                seen_owner_fields.add(key)
            mapping_values[key] = parse_scalar(value)
            continue
        if section == "produces" and stripped.startswith("- "):
            flush_product()
            current_product = {}
            key, value = stripped[2:].split(":", 1)
            current_product[key] = parse_scalar(value)
            continue
        if section == "produces" and current_product is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_product[key] = parse_scalar(value)
    flush_product()

    missing = sorted(REQUIRED_MAPPING_FIELDS - set(mapping_values))
    if missing:
        raise ValueError(f"missing mapping fields: {missing}")
    version = mapping_values["version"]
    if not isinstance(version, str) or not version:
        raise ValueError("mapping version must be a non-empty string")
    if version not in SUPPORTED_MAPPING_VERSIONS:
        raise ValueError(f"unsupported mapping version: {mapping_values['version']}")
    owner_fields = OWNER_FIELDS & set(mapping_values)
    if len(owner_fields) != 1:
        raise ValueError("mapping must declare exactly one owner field")
    expected_owner_field = "owner_skill_id" if version == "v0.1" else "owner_principal_id"
    if owner_fields != {expected_owner_field}:
        raise ValueError(f"mapping {version} requires {expected_owner_field}")
    owner_field = next(iter(owner_fields))
    for field in ("id", "domain", owner_field, "instruction_ref"):
        if not isinstance(mapping_values[field], str) or not mapping_values[field]:
            raise ValueError(f"mapping {field} must be a non-empty string")
    source_types = mapping_values["source_types"]
    if not isinstance(source_types, list) or not source_types:
        raise ValueError("mapping source_types must be a non-empty list")
    if not all(isinstance(item, str) and item for item in source_types):
        raise ValueError("mapping source_types entries must be non-empty strings")
    if not products:
        raise ValueError("mapping produces must not be empty")
    normalized = {
        **{key: value for key, value in mapping_values.items() if key not in OWNER_FIELDS},
        "owner_principal_id": mapping_values[owner_field],
        "produces": products,
        "_path": str(path),
    }
    if version == "v0.1":
        normalized["_legacy_owner_skill_id"] = mapping_values[owner_field]
    return normalized


def contracts_from_principal(entry: dict) -> set[tuple[str, str]]:
    contracts: set[tuple[str, str]] = set()
    for product in entry.get("produces", []):
        kinds = [kind for kind in CONTRACT_KINDS if kind in product]
        if len(kinds) == 1:
            contracts.add((kinds[0], product[kinds[0]]))
    return contracts


def mapping_digest(mapping: dict) -> str:
    body = {
        key: value
        for key, value in mapping.items()
        if key not in {"_path", "_legacy_owner_skill_id"}
    }
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def validate_ingest_mapping(mapping: dict, registry: dict, profile: Profile) -> dict:
    owner_principal_id = mapping["owner_principal_id"]
    owner_entry = resolve_principal(registry, owner_principal_id)
    if mapping["domain"] != owner_entry.get("domain"):
        raise ValueError("mapping domain does not match owner domain")
    owner_contracts = contracts_from_principal(owner_entry)

    for product in mapping["produces"]:
        kind = next(kind for kind in CONTRACT_KINDS if kind in product)
        value = product[kind]
        if (kind, value) not in owner_contracts:
            raise ValueError(f"owner principal does not produce {kind}: {value}")
        if kind == "record_type" and value not in profile.write_rules:
            raise ValueError(f"profile does not declare record: {value}")
        if kind == "artifact_type" and value not in profile.artifact_types:
            raise ValueError(f"profile does not declare artifact: {value}")
        if kind == "log_type" and value not in profile.log_rules:
            raise ValueError(f"profile does not declare log: {value}")

    result = {
        "status": "ok",
        "mapping_id": mapping["id"],
        "owner_principal_id": owner_principal_id,
        "principal_kind": owner_entry["kind"],
        "mapping_digest": mapping_digest(mapping),
        "produces": mapping["produces"],
    }
    if "_legacy_owner_skill_id" in mapping:
        result["owner_skill_id"] = mapping["_legacy_owner_skill_id"]
    return result
