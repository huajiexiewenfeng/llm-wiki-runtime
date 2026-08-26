from __future__ import annotations

import os
import sys
from pathlib import Path

from .contract_yaml import load_contract_document


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
    return load_contract_document(path, "skill")


def produced_types(doc: dict | None) -> list[str]:
    if not doc:
        return []
    result: list[str] = []
    for item in doc.get("ingest", {}).get("produces", []):
        for key in ("record_type", "artifact_type", "log_type"):
            if key in item:
                result.append(item[key])
    return result


def build_registry(
    scp_paths: list[Path],
    domain_policies: dict | None = None,
    caller_groups: dict | None = None,
    existing_registry: dict | None = None,
) -> dict:
    from .principal_registry import build_principal_registry

    return build_principal_registry(
        scp_paths,
        existing_registry=existing_registry,
        domain_policies=domain_policies,
        caller_groups=caller_groups,
    )


def write_registry(registry: dict, path: Path | None = None) -> Path:
    from .principal_registry import normalize_registry, write_principal_registry

    return write_principal_registry(normalize_registry(registry), path or skill_registry_path())
