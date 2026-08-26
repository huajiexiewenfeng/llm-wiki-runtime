from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from llm_wiki_runtime.principal import load_principal_manifest
from llm_wiki_runtime.principal_registry import (
    PrincipalRegistryError,
    build_principal_registry,
    load_principal_registry,
    normalize_registry,
    register_workload_principal,
    resolve_principal,
    write_principal_registry,
)


def write_skill_scp(tmp_path: Path) -> Path:
    path = tmp_path / "demo.scp.yml"
    path.write_text(
        """scp_version: v0.1
skill:
  id: demo-skill
  domain: demo
llm_wiki:
  profile: demo
  fallback_mode: markdown
trust:
  level: internal
  instruction_policy: trusted_content
query:
  primary_domain: demo
  supports: []
ingest:
  produces:
    - domain: demo
      record_type: demo_record
""",
        encoding="utf-8",
    )
    return path


def write_workload_manifest(tmp_path: Path, profile: str = "demo") -> Path:
    path = tmp_path / "demo.principal.yml"
    path.write_text(
        f"""principal_version: v0.1
principal:
  id: demo-harness
  kind: workload
  role: domain_harness
  domain: demo
llm_wiki:
  profile: {profile}
  fallback_mode: evidence_only
trust:
  level: sensitive_local
  instruction_policy: data_only
query:
  primary_domain: demo
  supports: []
ingest:
  produces:
    - domain: demo
      record_type: demo_revision
""",
        encoding="utf-8",
    )
    return path


def empty_registry() -> dict:
    return {"version": "v0.2", "principals": {}, "skills": {}, "domains": {}, "domain_policies": {}, "warnings": []}


def test_v01_registry_normalizes_to_principals_and_skill_projection(tmp_path):
    scp = write_skill_scp(tmp_path)
    old = {"version": "v0.1", "skills": {"demo-skill": {"domain": "demo", "scp_path": str(scp)}}}

    normalized = normalize_registry(old)

    assert normalized["version"] == "v0.2"
    assert normalized["principals"]["demo-skill"]["kind"] == "skill"
    assert normalized["skills"]["demo-skill"] == normalized["principals"]["demo-skill"]


def test_scan_scp_preserves_registered_workload(tmp_path):
    manifest = write_workload_manifest(tmp_path)
    registry = register_workload_principal(empty_registry(), load_principal_manifest(manifest))

    rebuilt = build_principal_registry([write_skill_scp(tmp_path)], registry, {}, {})

    assert set(rebuilt["principals"]) == {"demo-skill", "demo-harness"}


def test_scan_scp_defensively_preserves_legacy_origin_workload(tmp_path):
    registry = empty_registry()
    registry["principals"]["unexpected-workload"] = {
        "kind": "workload",
        "role": "domain_harness",
        "domain": "demo",
        "origin": "legacy_scp",
    }

    rebuilt = build_principal_registry([write_skill_scp(tmp_path)], registry, {}, {})

    assert "unexpected-workload" in rebuilt["principals"]
    assert "unexpected-workload" not in rebuilt["skills"]


def test_registering_identical_workload_is_idempotent(tmp_path):
    manifest = load_principal_manifest(write_workload_manifest(tmp_path))
    registry = register_workload_principal(empty_registry(), manifest)

    result = register_workload_principal(registry, manifest)

    assert result == registry
    assert result is not registry


def test_changed_workload_requires_explicit_refresh(tmp_path):
    first = load_principal_manifest(write_workload_manifest(tmp_path, profile="demo"))
    registry = register_workload_principal(empty_registry(), first)
    changed = load_principal_manifest(write_workload_manifest(tmp_path, profile="demo-v2"))

    with pytest.raises(PrincipalRegistryError) as exc:
        register_workload_principal(registry, changed)

    assert exc.value.code == "principal_contract_stale"
    refreshed = register_workload_principal(registry, changed, refresh=True)
    assert refreshed["principals"]["demo-harness"]["profile"] == "demo-v2"


def test_registration_rejects_kind_conflict(tmp_path):
    skill_registry = build_principal_registry([write_skill_scp(tmp_path)], empty_registry(), {}, {})
    workload = load_principal_manifest(write_workload_manifest(tmp_path))
    workload["principal"]["id"] = "demo-skill"

    with pytest.raises(PrincipalRegistryError) as exc:
        register_workload_principal(skill_registry, workload)

    assert exc.value.code == "principal_conflict"


def test_normalize_rejects_stale_skill_projection():
    registry = empty_registry()
    registry["principals"]["demo-skill"] = {"kind": "skill", "domain": "demo"}
    registry["skills"]["other-skill"] = {"kind": "skill", "domain": "other"}

    with pytest.raises(PrincipalRegistryError) as exc:
        normalize_registry(registry)

    assert exc.value.code == "principal_conflict"


def test_normalize_rejects_unsupported_persisted_principal_kind():
    registry = empty_registry()
    registry["principals"]["demo-agent"] = {"kind": "agent", "domain": "demo"}

    with pytest.raises(PrincipalRegistryError) as exc:
        normalize_registry(registry)

    assert exc.value.code == "principal_kind_unsupported"


def test_normalize_rejects_unsupported_persisted_workload_role():
    registry = empty_registry()
    registry["principals"]["demo-harness"] = {"kind": "workload", "role": "service", "domain": "demo"}

    with pytest.raises(PrincipalRegistryError) as exc:
        normalize_registry(registry)

    assert exc.value.code == "principal_role_unsupported"


def test_normalize_rejects_a_workload_role_on_persisted_skill():
    registry = empty_registry()
    skill = {"kind": "skill", "role": "domain_harness", "domain": "demo"}
    registry["principals"]["demo-skill"] = skill
    registry["skills"]["demo-skill"] = skill

    with pytest.raises(PrincipalRegistryError) as exc:
        normalize_registry(registry)

    assert exc.value.code == "principal_role_unsupported"


def test_scan_scp_rejects_same_id_as_registered_workload(tmp_path):
    workload = load_principal_manifest(write_workload_manifest(tmp_path))
    workload["principal"]["id"] = "demo-skill"
    registry = register_workload_principal(empty_registry(), workload)

    with pytest.raises(PrincipalRegistryError) as exc:
        build_principal_registry([write_skill_scp(tmp_path)], registry, {}, {})

    assert exc.value.code == "principal_conflict"


def test_load_registry_is_read_only_and_write_uses_v02_projection(tmp_path):
    registry = build_principal_registry([write_skill_scp(tmp_path)], empty_registry(), {}, {})
    target = tmp_path / "registry.json"
    write_principal_registry(registry, target)
    before = target.read_text(encoding="utf-8")

    loaded = load_principal_registry(target)

    assert loaded == registry
    assert target.read_text(encoding="utf-8") == before
    assert json.loads(before)["skills"] == json.loads(before)["principals"]


def test_resolve_principal_rejects_changed_contract(tmp_path):
    scp = write_skill_scp(tmp_path)
    registry = build_principal_registry([scp], empty_registry(), {}, {})
    scp.write_text(scp.read_text(encoding="utf-8").replace("profile: demo", "profile: changed"), encoding="utf-8")

    with pytest.raises(PrincipalRegistryError) as exc:
        resolve_principal(registry, "demo-skill")

    assert exc.value.code == "principal_contract_stale"


def test_registration_does_not_mutate_input_registry(tmp_path):
    registry = empty_registry()
    original = copy.deepcopy(registry)

    register_workload_principal(registry, load_principal_manifest(write_workload_manifest(tmp_path)))

    assert registry == original
