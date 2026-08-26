from __future__ import annotations

import copy
import json
from pathlib import Path

from .io import atomic_write_json
from .policy import assert_read_allowed, load_domain_policies
from .principal import (
    principal_contract_digest,
    principal_from_scp,
    load_principal_manifest,
    validate_principal_contract,
)
from .scp import load_scp, produced_types


REGISTRY_VERSION = "v0.2"


class PrincipalRegistryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _empty_registry() -> dict:
    return {
        "version": REGISTRY_VERSION,
        "principals": {},
        "skills": {},
        "domains": {},
        "domain_policies": {},
        "warnings": [],
    }


def _contract_from_scp_unchecked(scp: dict) -> dict:
    return {
        "principal_version": "v0.1",
        "principal": {
            "id": scp["skill"]["id"],
            "kind": "skill",
            "domain": scp["skill"]["domain"],
        },
        "llm_wiki": dict(scp.get("llm_wiki", {})),
        "trust": dict(scp.get("trust", {})),
        "query": dict(scp.get("query", {"supports": []})),
        "ingest": dict(scp.get("ingest", {"produces": []})),
        "_path": scp.get("_path"),
    }


def _entry_from_contract(contract: dict, supports: list[str] | None = None, support_filters: dict | None = None) -> dict:
    principal = contract["principal"]
    kind = principal["kind"]
    entry = {
        "kind": kind,
        "role": principal.get("role"),
        "domain": principal["domain"],
        "profile": contract.get("llm_wiki", {}).get("profile"),
        "contract_path": contract["_path"],
        "contract_digest": principal_contract_digest(contract),
        "origin": "legacy_scp" if kind == "skill" else "principal_manifest",
        "fallback_mode": contract.get("llm_wiki", {}).get("fallback_mode", "markdown"),
        "trust_level": contract.get("trust", {}).get("level"),
        "instruction_policy": contract.get("trust", {}).get("instruction_policy"),
        "produces": contract.get("ingest", {}).get("produces", []),
        "supports": list(supports or []),
        "support_filters": dict(support_filters or {}),
    }
    if kind == "skill":
        entry["scp_path"] = contract["_path"]
    return entry


def _project_skills(principals: dict) -> dict:
    return {principal_id: entry for principal_id, entry in principals.items() if entry.get("kind") == "skill"}


def _validate_persisted_principal(principal_id: str, entry: object) -> None:
    if not isinstance(entry, dict):
        raise PrincipalRegistryError("principal_kind_unsupported", f"principal entry must be a mapping: {principal_id}")
    kind = entry.get("kind")
    if kind not in {"skill", "workload"}:
        raise PrincipalRegistryError("principal_kind_unsupported", f"unsupported principal kind: {kind!r}")
    role = entry.get("role")
    if kind == "skill" and role is not None:
        raise PrincipalRegistryError("principal_role_unsupported", f"skill principal cannot carry a role: {principal_id}")
    if kind == "workload" and role != "domain_harness":
        raise PrincipalRegistryError("principal_role_unsupported", f"unsupported workload role: {role!r}")


def _copy_common_fields(source: dict, target: dict) -> None:
    for key in ("domains", "domain_policies", "warnings"):
        if key in source:
            target[key] = copy.deepcopy(source[key])


def _legacy_skill_entry(principal_id: str, entry: dict) -> dict:
    path_text = entry.get("contract_path", entry.get("scp_path"))
    if path_text:
        scp = load_scp(Path(path_text))
        try:
            contract = principal_from_scp(scp)
        except ValueError:
            contract = _contract_from_scp_unchecked(scp)
        return _entry_from_contract(contract, entry.get("supports", []), entry.get("support_filters", {}))
    return {
        "kind": "skill",
        "role": None,
        "domain": entry.get("domain"),
        "profile": entry.get("profile"),
        "contract_path": None,
        "contract_digest": None,
        "origin": "legacy_scp",
        "fallback_mode": entry.get("fallback_mode", "markdown"),
        "trust_level": entry.get("trust_level"),
        "instruction_policy": entry.get("instruction_policy"),
        "produces": entry.get("produces", []),
        "supports": entry.get("supports", []),
        "support_filters": entry.get("support_filters", {}),
        "scp_path": None,
    }


def normalize_registry(registry: dict) -> dict:
    if not isinstance(registry, dict):
        raise PrincipalRegistryError("principal_conflict", "principal registry must be a mapping")

    version = registry.get("version", "v0.1")
    if version == "v0.1":
        normalized = _empty_registry()
        _copy_common_fields(registry, normalized)
        for principal_id, entry in registry.get("skills", {}).items():
            normalized["principals"][principal_id] = _legacy_skill_entry(principal_id, entry)
        normalized["skills"] = _project_skills(normalized["principals"])
        return normalized
    if version != REGISTRY_VERSION:
        raise PrincipalRegistryError("principal_conflict", f"unsupported principal registry version: {version!r}")

    normalized = _empty_registry()
    _copy_common_fields(registry, normalized)
    principals = registry.get("principals", {})
    if not isinstance(principals, dict):
        raise PrincipalRegistryError("principal_conflict", "registry principals must be a mapping")
    for principal_id, entry in principals.items():
        _validate_persisted_principal(principal_id, entry)
    normalized["principals"] = copy.deepcopy(principals)
    projection = _project_skills(normalized["principals"])
    if "skills" in registry and registry["skills"] != projection:
        raise PrincipalRegistryError("principal_conflict", "registry skills do not match the principal projection")
    normalized["skills"] = projection
    return normalized


def load_principal_registry(path: Path) -> dict:
    return normalize_registry(json.loads(path.read_text(encoding="utf-8")))


def _support_projection(
    doc: dict,
    by_domain: dict[str, list[dict]],
    policies: dict,
    caller_groups: dict,
    warnings: list[dict],
) -> tuple[list[str], dict]:
    skill_id = doc["skill"]["id"]
    domain = doc["skill"]["domain"]
    supports: list[str] = []
    support_filters: dict = {}
    for support in doc.get("query", {}).get("supports", []):
        target = support.get("domain")
        allowed, reason = assert_read_allowed(domain, target, policies, caller_groups.get(skill_id, []))
        if not allowed:
            warnings.append({"skill_id": skill_id, "domain": domain, "support_domain": target, "reason": reason})
            continue
        target_types = {item for target_doc in by_domain.get(target, []) for item in produced_types(target_doc)}
        requested = set(support.get("record_types", []))
        if by_domain.get(target) and not requested.issubset(target_types):
            warnings.append(
                {
                    "skill_id": skill_id,
                    "domain": domain,
                    "support_domain": target,
                    "reason": "support_record_type_not_produced",
                }
            )
            continue
        supports.append(target)
        support_filters[target] = {"record_types": support.get("record_types", [])}
    return supports, support_filters


def build_principal_registry(
    scp_paths: list[Path],
    existing_registry: dict | None,
    domain_policies: dict | None,
    caller_groups: dict | None,
) -> dict:
    previous = normalize_registry(existing_registry or _empty_registry())
    policies = load_domain_policies(
        domain_policies if domain_policies is not None else previous["domain_policies"]
    )
    groups_by_skill = caller_groups or {}
    docs = [load_scp(path) for path in scp_paths]
    registry = _empty_registry()
    registry["domain_policies"] = copy.deepcopy(policies)
    registry["warnings"] = copy.deepcopy(previous["warnings"])
    registry["domains"] = copy.deepcopy(previous["domains"])
    registry["principals"] = {
        principal_id: copy.deepcopy(entry)
        for principal_id, entry in previous["principals"].items()
        if not (entry.get("origin") == "legacy_scp" and entry.get("kind") == "skill")
    }
    preserved_principal_ids = set(registry["principals"])
    by_domain: dict[str, list[dict]] = {}
    seen_skill_ids: set[str] = set()
    for doc in docs:
        skill_id = doc["skill"].get("id")
        domain = doc["skill"].get("domain")
        if skill_id in seen_skill_ids:
            registry["warnings"].append({"skill_id": skill_id, "domain": domain, "reason": "duplicate_skill_id"})
        seen_skill_ids.add(skill_id)
        by_domain.setdefault(domain, []).append(doc)

    for domain in by_domain:
        domain_entry = copy.deepcopy(registry["domains"].get(domain, {}))
        domain_entry.update({"skills": [], "profiles": [], "produces": [], "supports": []})
        registry["domains"][domain] = domain_entry

    for doc in docs:
        skill_id = doc["skill"]["id"]
        domain = doc["skill"]["domain"]
        if skill_id in preserved_principal_ids:
            raise PrincipalRegistryError(
                "principal_conflict",
                f"scanned skill conflicts with registered principal: {skill_id}",
            )
        if doc.get("query", {}).get("primary_domain") not in {None, domain}:
            registry["warnings"].append({"skill_id": skill_id, "domain": domain, "reason": "primary_domain_mismatch"})
        for produced in doc.get("ingest", {}).get("produces", []):
            if produced.get("domain") != domain:
                registry["warnings"].append({"skill_id": skill_id, "domain": domain, "reason": "produce_domain_mismatch"})
        supports, support_filters = _support_projection(doc, by_domain, policies, groups_by_skill, registry["warnings"])
        try:
            contract = principal_from_scp(doc)
        except ValueError:
            contract = _contract_from_scp_unchecked(doc)
        registry["principals"][skill_id] = _entry_from_contract(contract, supports, support_filters)
        registry["domains"][domain]["skills"].append(skill_id)
        registry["domains"][domain]["profiles"].append(doc.get("llm_wiki", {}).get("profile"))
        registry["domains"][domain]["produces"].extend(produced_types(doc))
        registry["domains"][domain]["supports"].extend(supports)
    registry["skills"] = _project_skills(registry["principals"])
    return registry


def register_workload_principal(registry: dict, manifest: dict, refresh: bool = False) -> dict:
    try:
        validate_principal_contract(manifest, expected_kind="workload")
    except (KeyError, ValueError) as exc:
        raise PrincipalRegistryError("principal_conflict", str(exc)) from exc
    result = normalize_registry(registry)
    principal_id = manifest["principal"]["id"]
    existing = result["principals"].get(principal_id)
    entry = _entry_from_contract(manifest)
    if existing is not None:
        if existing.get("kind") != "workload":
            raise PrincipalRegistryError("principal_conflict", f"principal id already belongs to a {existing.get('kind')} principal")
        if existing.get("contract_digest") != entry["contract_digest"] and not refresh:
            raise PrincipalRegistryError("principal_contract_stale", "workload principal contract changed; refresh is required")
    result["principals"][principal_id] = entry
    result["skills"] = _project_skills(result["principals"])
    return result


def write_principal_registry(registry: dict, path: Path) -> Path:
    normalized = normalize_registry(registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, normalized)
    return path


def resolve_principal(registry: dict, principal_id: str) -> dict:
    entry = normalize_registry(registry)["principals"].get(principal_id)
    if entry is None:
        raise PrincipalRegistryError("principal_not_found", f"principal not found: {principal_id}")
    path = entry.get("contract_path")
    if not path:
        raise PrincipalRegistryError("principal_contract_stale", f"principal has no contract path: {principal_id}")
    try:
        contract = principal_from_scp(load_scp(Path(path))) if entry.get("kind") == "skill" else load_principal_manifest(Path(path))
    except (OSError, ValueError, KeyError) as exc:
        raise PrincipalRegistryError("principal_contract_stale", f"unable to verify principal contract: {principal_id}") from exc
    if principal_contract_digest(contract) != entry.get("contract_digest"):
        raise PrincipalRegistryError("principal_contract_stale", f"principal contract is stale: {principal_id}")
    return copy.deepcopy(entry)
