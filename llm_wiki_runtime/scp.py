from __future__ import annotations

import os
import sys
from pathlib import Path

from .io import atomic_write_json
from .policy import assert_read_allowed, load_domain_policies
from .profile import parse_scalar


def skill_registry_path() -> Path:
    override = os.environ.get("LLM_WIKI_SKILL_REGISTRY")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "llm-wiki-runtime" / "skill-registry.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "llm-wiki-runtime" / "skill-registry.json"
    return Path.home() / ".config" / "llm-wiki-runtime" / "skill-registry.json"


def load_scp(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    doc: dict = {
        "skill": {},
        "llm_wiki": {},
        "trust": {},
        "query": {"supports": []},
        "ingest": {"produces": []},
        "_path": str(path),
    }
    section: str | None = None
    in_supports = False
    in_produces = False
    current_item: dict | None = None

    def flush_item() -> None:
        nonlocal current_item
        if current_item is None:
            return
        if in_supports:
            doc["query"]["supports"].append(current_item)
        elif in_produces:
            doc["ingest"]["produces"].append(current_item)
        current_item = None

    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            flush_item()
            section = stripped[:-1]
            in_supports = False
            in_produces = False
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            doc[key] = parse_scalar(value)
            continue
        if section in {"skill", "llm_wiki", "trust"} and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            doc[section][key] = parse_scalar(value)
            continue
        if section == "query":
            if indent == 2 and stripped == "supports:":
                in_supports = True
                continue
            if indent == 2 and ":" in stripped:
                key, value = stripped.split(":", 1)
                doc["query"][key] = parse_scalar(value)
                continue
            if in_supports and stripped.startswith("- "):
                flush_item()
                current_item = {}
                key, value = stripped[2:].split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
            if in_supports and current_item is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
        if section == "ingest":
            if indent == 2 and stripped == "produces:":
                in_produces = True
                continue
            if in_produces and stripped.startswith("- "):
                flush_item()
                current_item = {}
                key, value = stripped[2:].split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
            if in_produces and current_item is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_item[key] = parse_scalar(value)
                continue
    flush_item()
    return doc


def produced_types(doc: dict | None) -> list[str]:
    if not doc:
        return []
    result: list[str] = []
    for item in doc.get("ingest", {}).get("produces", []):
        for key in ("record_type", "artifact_type", "log_type"):
            if key in item:
                result.append(item[key])
    return result


def build_registry(scp_paths: list[Path], domain_policies: dict | None = None, caller_groups: dict | None = None) -> dict:
    policies = load_domain_policies(domain_policies)
    groups_by_skill = caller_groups or {}
    docs = [load_scp(path) for path in scp_paths]
    registry = {"version": "v0.1", "skills": {}, "domains": {}, "domain_policies": policies, "warnings": []}
    by_domain: dict[str, list[dict]] = {}
    seen_skill_ids: set[str] = set()

    for doc in docs:
        skill_id = doc["skill"].get("id")
        domain = doc["skill"].get("domain")
        if skill_id in seen_skill_ids:
            registry["warnings"].append({"skill_id": skill_id, "domain": domain, "reason": "duplicate_skill_id"})
        seen_skill_ids.add(skill_id)
        by_domain.setdefault(domain, []).append(doc)

    for doc in docs:
        skill_id = doc["skill"]["id"]
        domain = doc["skill"]["domain"]
        if doc.get("query", {}).get("primary_domain") not in {None, domain}:
            registry["warnings"].append({"skill_id": skill_id, "domain": domain, "reason": "primary_domain_mismatch"})
        for produced in doc.get("ingest", {}).get("produces", []):
            if produced.get("domain") != domain:
                registry["warnings"].append({"skill_id": skill_id, "domain": domain, "reason": "produce_domain_mismatch"})

        supports: list[str] = []
        support_filters: dict = {}
        for support in doc.get("query", {}).get("supports", []):
            target = support.get("domain")
            allowed, reason = assert_read_allowed(domain, target, policies, groups_by_skill.get(skill_id, []))
            if not allowed:
                registry["warnings"].append(
                    {"skill_id": skill_id, "domain": domain, "support_domain": target, "reason": reason}
                )
                continue
            target_docs = by_domain.get(target, [])
            target_types: set[str] = set()
            for target_doc in target_docs:
                target_types.update(produced_types(target_doc))
            requested = set(support.get("record_types", []))
            if target_docs and not requested.issubset(target_types):
                registry["warnings"].append(
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

        registry["skills"][skill_id] = {
            "domain": domain,
            "profile": doc.get("llm_wiki", {}).get("profile"),
            "scp_path": doc["_path"],
            "fallback_mode": doc.get("llm_wiki", {}).get("fallback_mode", "markdown"),
            "trust_level": doc.get("trust", {}).get("level"),
            "instruction_policy": doc.get("trust", {}).get("instruction_policy"),
            "produces": produced_types(doc),
            "supports": supports,
            "support_filters": support_filters,
        }
        registry["domains"].setdefault(domain, {"skills": [], "profiles": [], "produces": [], "supports": []})
        registry["domains"][domain]["skills"].append(skill_id)
        registry["domains"][domain]["profiles"].append(doc.get("llm_wiki", {}).get("profile"))
        registry["domains"][domain]["produces"].extend(produced_types(doc))
        registry["domains"][domain]["supports"].extend(supports)
    return registry


def write_registry(registry: dict, path: Path | None = None) -> Path:
    target = path or skill_registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, registry)
    return target
