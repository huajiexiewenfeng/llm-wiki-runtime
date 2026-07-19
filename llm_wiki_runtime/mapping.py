from __future__ import annotations

from pathlib import Path

from .models import Profile
from .profile import parse_scalar
from .scp import load_scp


CONTRACT_KINDS = ("record_type", "artifact_type", "log_type")
REQUIRED_MAPPING_FIELDS = {
    "id",
    "version",
    "domain",
    "owner_skill_id",
    "source_types",
    "instruction_ref",
}


def load_ingest_mapping(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    mapping_values: dict[str, object] = {}
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
    if mapping_values["version"] != "v0.1":
        raise ValueError(f"unsupported mapping version: {mapping_values['version']}")
    for field in ("id", "domain", "owner_skill_id", "instruction_ref"):
        if not isinstance(mapping_values[field], str) or not mapping_values[field]:
            raise ValueError(f"mapping {field} must be a non-empty string")
    source_types = mapping_values["source_types"]
    if not isinstance(source_types, list) or not source_types:
        raise ValueError("mapping source_types must be a non-empty list")
    if not all(isinstance(item, str) and item for item in source_types):
        raise ValueError("mapping source_types entries must be non-empty strings")
    if not products:
        raise ValueError("mapping produces must not be empty")
    return {**mapping_values, "produces": products, "_path": str(path)}


def contracts_from_scp(doc: dict) -> set[tuple[str, str]]:
    contracts: set[tuple[str, str]] = set()
    for product in doc.get("ingest", {}).get("produces", []):
        kinds = [kind for kind in CONTRACT_KINDS if kind in product]
        if len(kinds) == 1:
            contracts.add((kinds[0], product[kinds[0]]))
    return contracts


def validate_ingest_mapping(mapping: dict, registry: dict, profile: Profile) -> dict:
    owner_skill_id = mapping["owner_skill_id"]
    owner_entry = registry.get("skills", {}).get(owner_skill_id)
    if owner_entry is None:
        raise ValueError(f"mapping owner is not registered: {owner_skill_id}")
    if mapping["domain"] != owner_entry.get("domain"):
        raise ValueError("mapping domain does not match owner domain")
    scp_path = owner_entry.get("scp_path")
    if not isinstance(scp_path, str) or not scp_path:
        raise ValueError(f"mapping owner has no SCP path: {owner_skill_id}")
    owner_scp = load_scp(Path(scp_path))
    if owner_scp.get("skill", {}).get("id") != owner_skill_id:
        raise ValueError("mapping owner id does not match owner SCP")
    owner_contracts = contracts_from_scp(owner_scp)

    for product in mapping["produces"]:
        kind = next(kind for kind in CONTRACT_KINDS if kind in product)
        value = product[kind]
        if (kind, value) not in owner_contracts:
            raise ValueError(f"owner SCP does not produce {kind}: {value}")
        if kind == "record_type" and value not in profile.write_rules:
            raise ValueError(f"profile does not declare record: {value}")
        if kind == "artifact_type" and value not in profile.artifact_types:
            raise ValueError(f"profile does not declare artifact: {value}")
        if kind == "log_type" and value not in profile.log_rules:
            raise ValueError(f"profile does not declare log: {value}")

    return {
        "status": "ok",
        "mapping_id": mapping["id"],
        "owner_skill_id": owner_skill_id,
        "produces": mapping["produces"],
    }
