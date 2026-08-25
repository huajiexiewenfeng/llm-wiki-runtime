from pathlib import Path

import pytest

from llm_wiki_runtime.principal import (
    load_principal_manifest,
    principal_contract_digest,
    principal_from_scp,
)
from llm_wiki_runtime.scp import load_scp


WORKLOAD = """principal_version: v0.1
principal:
  id: ai-research-observatory-harness
  kind: workload
  role: domain_harness
  domain: ai-research-observatory
llm_wiki:
  profile: ai-research-observatory
  required: false
  fallback_mode: evidence_only
trust:
  level: sensitive_local
  source_type: harness_generated
  instruction_policy: data_only
query:
  primary_domain: ai-research-observatory
  supports: []
ingest:
  produces:
    - domain: ai-research-observatory
      record_type: research_direction_revision
"""


def write_manifest(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_workload_principal_contract(tmp_path: Path):
    path = tmp_path / "principal.yml"
    write_manifest(path, WORKLOAD)

    contract = load_principal_manifest(path)

    assert contract["principal"] == {
        "id": "ai-research-observatory-harness",
        "kind": "workload",
        "role": "domain_harness",
        "domain": "ai-research-observatory",
    }
    assert principal_contract_digest(contract).startswith("sha256:")


def test_workload_contract_digest_ignores_source_path(tmp_path: Path):
    first = tmp_path / "a.yml"
    second = tmp_path / "nested" / "b.yml"
    second.parent.mkdir()
    write_manifest(first, WORKLOAD)
    write_manifest(second, WORKLOAD)

    assert principal_contract_digest(load_principal_manifest(first)) == principal_contract_digest(
        load_principal_manifest(second)
    )


def test_rejects_unsupported_workload_role(tmp_path: Path):
    path = tmp_path / "principal.yml"
    write_manifest(path, WORKLOAD.replace("domain_harness", "service"))

    with pytest.raises(ValueError, match="unsupported workload role"):
        load_principal_manifest(path)


def test_rejects_unsafe_principal_id(tmp_path: Path):
    path = tmp_path / "principal.yml"
    write_manifest(path, WORKLOAD.replace("ai-research-observatory-harness", "../unsafe"))

    with pytest.raises(ValueError, match="unsafe path variable"):
        load_principal_manifest(path)


def test_rejects_cross_domain_produced_contract(tmp_path: Path):
    path = tmp_path / "principal.yml"
    write_manifest(path, WORKLOAD.replace("record_type: research_direction_revision", "domain: other\n      record_type: research_direction_revision"))

    with pytest.raises(ValueError, match="produce domain mismatch"):
        load_principal_manifest(path)


def test_rejects_extra_principal_identity_field(tmp_path: Path):
    path = tmp_path / "principal.yml"
    write_manifest(path, WORKLOAD.replace("  domain: ai-research-observatory", "  domain: ai-research-observatory\n  executable: runtime.exe", 1))

    with pytest.raises(ValueError, match="principal identity fields"):
        load_principal_manifest(path)


def test_rejects_produced_item_with_multiple_contract_kinds(tmp_path: Path):
    path = tmp_path / "principal.yml"
    write_manifest(path, WORKLOAD.replace("record_type: research_direction_revision", "record_type: research_direction_revision\n      log_type: audit_log"))

    with pytest.raises(ValueError, match="exactly one contract kind"):
        load_principal_manifest(path)


def test_scp_normalizes_to_skill_principal(tmp_path: Path):
    path = tmp_path / "scp.yml"
    write_manifest(
        path,
        WORKLOAD.replace("principal_version: v0.1", "scp_version: v0.1")
        .replace("principal:", "skill:")
        .replace("  kind: workload\n", "")
        .replace("  role: domain_harness\n", ""),
    )

    principal = principal_from_scp(load_scp(path))

    assert principal["principal"]["kind"] == "skill"
    assert principal["principal"]["id"] == "ai-research-observatory-harness"
