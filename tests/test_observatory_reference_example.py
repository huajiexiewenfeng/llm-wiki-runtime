from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from llm_wiki_runtime.invocation import InvocationError, execute_invocation
from llm_wiki_runtime.mapping import load_ingest_mapping
from llm_wiki_runtime.principal import load_principal_manifest
from llm_wiki_runtime.principal_registry import (
    build_principal_registry,
    load_principal_registry,
    register_workload_principal,
    write_principal_registry,
)
from llm_wiki_runtime.profile import load_profile
from llm_wiki_runtime.runtime import init_profile
from llm_wiki_runtime.scp import load_scp


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "ai-research-observatory"
CONTRACTS = EXAMPLE_ROOT / "contracts"


def test_observatory_snapshot_manifest_matches_contract_bytes():
    manifest = json.loads(
        (EXAMPLE_ROOT / "snapshot-manifest.json").read_text(encoding="utf-8")
    )
    assert (
        manifest["source"]["repository"]
        == "https://github.com/huajiexiewenfeng/ai-research-observatory"
    )
    assert (
        manifest["source"]["commit"]
        == "b9c9bc6a04f5a9efeea7d7b8840bec370f61d69c"
    )
    assert set(manifest["contracts"]) == {
        "principal.yml",
        "scp.yml",
        "llm-wiki-profile.yml",
        "ingest-mapping.yml",
    }
    for name, metadata in manifest["contracts"].items():
        content = (CONTRACTS / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == metadata["sha256"]
        assert metadata["source_path"].startswith(
            "src/ai_observatory/memory/assets/"
        )


def test_observatory_contracts_model_independent_same_domain_principals():
    principal = load_principal_manifest(CONTRACTS / "principal.yml")
    scp = load_scp(CONTRACTS / "scp.yml")
    profile = load_profile(CONTRACTS / "llm-wiki-profile.yml")
    mapping = load_ingest_mapping(CONTRACTS / "ingest-mapping.yml")

    assert principal["principal"] == {
        "id": "ai-research-observatory-harness",
        "kind": "workload",
        "role": "domain_harness",
        "domain": "ai-research-observatory",
    }
    assert scp["skill"] == {
        "id": "ai-research-observatory",
        "domain": "ai-research-observatory",
    }
    assert principal["llm_wiki"]["profile"] == profile.id
    assert scp["llm_wiki"]["profile"] == profile.id
    assert mapping["version"] == "v0.2"
    assert mapping["owner_principal_id"] == "ai-research-observatory-harness"
    assert "_legacy_owner_skill_id" not in mapping


def _requests() -> dict[str, dict]:
    return {
        path.relative_to(EXAMPLE_ROOT / "requests").as_posix(): json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in sorted((EXAMPLE_ROOT / "requests").rglob("*.json"))
    }


def test_observatory_requests_cover_real_harness_flow_and_skill_boundary():
    requests = _requests()
    assert list(requests) == [
        "harness/00-resolve.request.json",
        "harness/10-copy-source.request.json",
        "harness/20-write-record.request.json",
        "harness/30-append-log.request.json",
        "harness/40-find-records.request.json",
        "harness/50-load-context.request.json",
        "skill/10-find-records.request.json",
        "skill/20-write-record-denied.request.json",
    ]
    for request in requests.values():
        assert set(request) <= {
            "protocol_version",
            "request_id",
            "principal_id",
            "operation",
            "scope_root",
            "mapping_id",
            "payload",
        }
        assert request["protocol_version"] == "v0.1"
        assert request["scope_root"] == "__ABSOLUTE_DOMAIN_WORKSPACE__"

    harness = [
        value for name, value in requests.items() if name.startswith("harness/")
    ]
    assert [value["operation"] for value in harness] == [
        "resolve",
        "copy_source",
        "write_record",
        "append_log",
        "find_records",
        "load_context",
    ]
    assert all(
        value["principal_id"] == "ai-research-observatory-harness"
        for value in harness
    )
    assert requests["harness/10-copy-source.request.json"]["payload"]["metadata"] == {}
    assert (
        requests["skill/10-find-records.request.json"]["principal_id"]
        == "ai-research-observatory"
    )
    denied = requests["skill/20-write-record-denied.request.json"]
    assert denied["mapping_id"] == "ai-research-observatory-memory"
    assert denied["operation"] == "write_record"


def test_authoritative_guide_routes_all_three_modes_without_blurring_legacy_harness_rules():
    guide = (
        ROOT
        / "docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md"
    ).read_text(encoding="utf-8")
    for fragment in (
        "Skill-only",
        "Harness-only",
        "Skill+Harness",
        "detected_mode",
        "owner_principal_id",
        "llm-wiki invoke",
        "mapping_owner_mismatch",
        "不得回退",
        "HR",
        "Runtime 0.1",
        "Runtime 0.3",
    ):
        assert fragment in guide
    assert "examples/ai-research-observatory" in guide


def test_example_readme_marks_snapshots_as_reference_only():
    text = (EXAMPLE_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    assert "不是运行时依赖" in text
    assert "逐字节快照" in text
    assert "__ABSOLUTE_DOMAIN_WORKSPACE__" in text
    assert "ai-research-observatory-harness" in text
    assert "ai-research-observatory" in text


def test_existing_skill_guides_declare_their_compatibility_boundary():
    quickstart = (
        ROOT / "docs/guides/domain-skill-integration-quickstart.zh.md"
    ).read_text(encoding="utf-8")
    hr = (ROOT / "docs/guides/hr-llm-wiki-integration.zh.md").read_text(
        encoding="utf-8"
    )
    implementation = (
        ROOT / "docs/guides/hr-skill-llm-wiki-runtime-implementation.zh.md"
    ).read_text(encoding="utf-8")
    assert "Skill-only 快速入口" in quickstart
    assert "skill-harness-llm-wiki-runtime-integration.zh.md" in quickstart
    assert "上面的 Workload" not in quickstart
    assert "上一节的 v0.2 Mapping" not in quickstart
    for text in (hr, implementation):
        assert "Runtime 0.1" in text
        assert "Runtime 0.3" in text
        assert "Skill-only" in text
        assert "新 Harness" in text
        assert "llm-wiki invoke" in text


def test_repository_entry_points_link_the_authoritative_guide_and_example():
    for name in ("README.md", "README.zh-CN.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert (
            "docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md"
            in text
        )
        assert "examples/ai-research-observatory/README.zh-CN.md" in text
    methodology = (
        ROOT / "docs/methodology/professional-skill-dual-loop-engineering.zh.md"
    ).read_text(encoding="utf-8")
    assert "Skill-only" in methodology
    assert "Harness-only" in methodology
    assert "Skill+Harness" in methodology
    assert (
        "../guides/skill-harness-llm-wiki-runtime-integration.zh.md"
        in methodology
    )


def _request(
    workspace: Path,
    principal_id: str,
    operation: str,
    payload: dict,
    *,
    mapping: bool = False,
) -> dict:
    request = {
        "protocol_version": "v0.1",
        "request_id": f"example-{principal_id}-{operation}",
        "principal_id": principal_id,
        "operation": operation,
        "scope_root": str(workspace),
        "payload": payload,
    }
    if mapping:
        request["mapping_id"] = "ai-research-observatory-memory"
    return request


def test_observatory_reference_completes_workload_flow_then_enforces_skill_boundary(
    tmp_path: Path,
):
    workspace = tmp_path / "observatory-workspace"
    workspace.mkdir()
    profile_path = CONTRACTS / "llm-wiki-profile.yml"
    principal_path = CONTRACTS / "principal.yml"
    mapping_path = CONTRACTS / "ingest-mapping.yml"
    scp_path = CONTRACTS / "scp.yml"
    registry_path = workspace / "memory/runtime/principal-registry.json"

    init_profile(workspace, profile_path, "local", "observatory-reference")
    registry = register_workload_principal(
        {}, load_principal_manifest(principal_path)
    )
    write_principal_registry(registry, registry_path)
    assert set(load_principal_registry(registry_path)["principals"]) == {
        "ai-research-observatory-harness"
    }

    invocation_args = {
        "registry_path": registry_path,
        "profile_path": profile_path,
        "mapping_path": mapping_path,
    }
    resolved = execute_invocation(
        _request(
            workspace,
            "ai-research-observatory-harness",
            "resolve",
            {},
            mapping=True,
        ),
        **invocation_args,
    )
    assert resolved["status"] == "ok"
    assert set(resolved["authorization"]) >= {
        "registry_digest",
        "policy_digest",
        "profile_digest",
        "mapping_digest",
    }

    evidence = workspace / "approved-evidence.md"
    evidence.write_text("# Approved Evidence\n\nA bounded source snapshot.\n", encoding="utf-8")
    copied = execute_invocation(
        _request(
            workspace,
            "ai-research-observatory-harness",
            "copy_source",
            {
                "source": str(evidence),
                "logical_path": "sources/originals/ai-research-observatory/example-source-001.md",
                "source_type": "approved_direction_revision",
                "metadata": {},
            },
            mapping=True,
        ),
        **invocation_args,
    )
    assert copied["result"]["status"] == "ok"

    content = workspace / "approved-record.md"
    content.write_text(
        "---\n"
        "record_type: research_direction_revision\n"
        "record_id: example-record-001\n"
        "title: Example Direction\n"
        "direction_id: example-direction\n"
        "revision: r1\n"
        "promotion_id: example-promotion-001\n"
        "---\n\n"
        "This accepted revision remains data-only context.\n",
        encoding="utf-8",
    )
    written = execute_invocation(
        _request(
            workspace,
            "ai-research-observatory-harness",
            "write_record",
            {
                "record_type": "research_direction_revision",
                "variables": {"direction_id": "example-direction", "revision": "r1"},
                "refs": {"source_id": copied["result"]["source_id"]},
                "content_file": str(content),
            },
            mapping=True,
        ),
        **invocation_args,
    )
    assert written["result"]["status"] == "ok"

    logged = execute_invocation(
        _request(
            workspace,
            "ai-research-observatory-harness",
            "append_log",
            {
                "log_type": "observatory_memory_event",
                "record": {
                    "event_id": "example-observatory-memory-event-001",
                    "record_id": "example-record-001",
                },
            },
            mapping=True,
        ),
        **invocation_args,
    )
    assert logged["result"]["status"] == "ok"

    found = execute_invocation(
        _request(
            workspace,
            "ai-research-observatory-harness",
            "find_records",
            {
                "record_type": "research_direction_revision",
                "lookup_value": "example-record-001",
                "target_domain": "ai-research-observatory",
            },
            mapping=True,
        ),
        **invocation_args,
    )
    assert found["result"]["status"] == "found"
    logical_path = found["result"]["matches"][0]["path"]

    loaded = execute_invocation(
        _request(
            workspace,
            "ai-research-observatory-harness",
            "load_context",
            {
                "path_filters": [logical_path],
                "glob_filters": [],
                "policy": "data_only",
                "target_domain": "ai-research-observatory",
            },
            mapping=True,
        ),
        **invocation_args,
    )
    assert loaded["result"]["items"][0]["instruction_policy"] == "data_only"

    registry = build_principal_registry(
        [scp_path], load_principal_registry(registry_path), {}, {}
    )
    write_principal_registry(registry, registry_path)
    assert set(registry["principals"]) == {
        "ai-research-observatory-harness",
        "ai-research-observatory",
    }
    assert set(registry["skills"]) == {"ai-research-observatory"}

    skill_found = execute_invocation(
        _request(
            workspace,
            "ai-research-observatory",
            "find_records",
            {
                "record_type": "research_direction_revision",
                "lookup_value": "example-record-001",
                "target_domain": "ai-research-observatory",
            },
        ),
        registry_path=registry_path,
    )
    assert skill_found["result"]["status"] == "found"
    target = workspace / ".llm-wiki" / logical_path
    checksum_before = hashlib.sha256(target.read_bytes()).hexdigest()

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            _request(
                workspace,
                "ai-research-observatory",
                "write_record",
                {
                    "record_type": "research_direction_revision",
                    "variables": {
                        "direction_id": "example-direction",
                        "revision": "r1",
                    },
                    "refs": {"source_id": copied["result"]["source_id"]},
                    "content_file": str(content),
                },
                mapping=True,
            ),
            **invocation_args,
        )
    assert exc.value.code == "mapping_owner_mismatch"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == checksum_before
