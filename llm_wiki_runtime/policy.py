from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def domain_policy_path() -> Path:
    override = os.environ.get("LLM_WIKI_DOMAIN_POLICIES")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "llm-wiki-runtime" / "domain-policies.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "llm-wiki-runtime" / "domain-policies.json"
    return Path.home() / ".config" / "llm-wiki-runtime" / "domain-policies.json"


def load_domain_policies(override: dict | None = None) -> dict:
    if override is not None:
        return override
    path = domain_policy_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def assert_read_allowed(
    caller_domain: str | None,
    target_domain: str | None,
    domain_policies: dict,
    caller_groups: list[str] | None = None,
) -> tuple[bool, str]:
    if not target_domain:
        return True, "ok"
    if caller_domain == target_domain:
        return True, "ok"
    if not caller_domain:
        return False, "no_caller_domain_default_deny"
    if not domain_policies:
        return False, "no_policy_default_deny"
    policy = domain_policies.get(target_domain, {})
    readable_by = policy.get("readable_by", [])
    if "*" in readable_by:
        return True, "ok"
    if caller_domain in readable_by:
        return True, "ok"
    for group in caller_groups or []:
        if group in readable_by:
            return True, "ok"
    return False, "domain_not_readable_by_caller"


def effective_instruction_policy(target_domain: str | None, domain_policies: dict, default: str = "trusted_content") -> str:
    if not target_domain:
        return default
    policy = domain_policies.get(target_domain, {})
    return policy.get("instruction_policy_override", default)
