from __future__ import annotations

import re

import pytest

import llm_wiki_runtime.invocation as runtime
from llm_wiki_runtime.invocation import InvocationError, execute_invocation
from llm_wiki_runtime.mapping import load_ingest_mapping, mapping_digest
from llm_wiki_runtime.policy import domain_policy_digest
from llm_wiki_runtime.principal_registry import (
    build_principal_registry,
    load_principal_registry,
    write_principal_registry,
)
from llm_wiki_runtime.profile import load_active_profile
from test_principal_invocation import PrincipalScope, principal_scope as base_principal_scope, write_request


@pytest.fixture
def principal_scope(base_principal_scope: PrincipalScope) -> PrincipalScope:
    scp = base_principal_scope.root / "demo-skill.scp.yml"
    scp.write_text(
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: demo-skill",
                "  domain: demo",
                "llm_wiki:",
                "  profile: demo",
                "query:",
                "  primary_domain: demo",
                "  supports: []",
                "ingest:",
                "  produces:",
                "    - domain: demo",
                "      record_type: demo_record",
            ]
        ),
        encoding="utf-8",
    )
    registered = build_principal_registry(
        [scp], load_principal_registry(base_principal_scope.registry), {}, {}
    )
    write_principal_registry(registered, base_principal_scope.registry)
    return base_principal_scope


def invoke(principal_scope: PrincipalScope, operation: str, payload: dict) -> dict:
    return execute_invocation(
        write_request(
            scope_root=str(principal_scope.root),
            operation=operation,
            payload=payload,
        ),
        registry_path=principal_scope.registry,
        profile_path=principal_scope.profile,
        mapping_path=principal_scope.mapping,
    )


def test_workload_can_copy_write_log_and_read_back(principal_scope: PrincipalScope):
    principal_scope.content.write_text(
        "---\nrecord_type: demo_record\nrecord_id: record-2\ndisplay_name: Record 2\n---\n\nDemo record.",
        encoding="utf-8",
    )
    copied = invoke(
        principal_scope,
        "copy_source",
        {
            "source": str(principal_scope.source),
            "logical_path": "sources/originals/demo/source.json",
            "source_type": "approved_demo",
            "metadata": {},
        },
    )
    written = invoke(
        principal_scope,
        "write_record",
        {
            "record_type": "demo_record",
            "variables": {"record_id": "record-2"},
            "refs": {"source_id": copied["result"]["source_id"]},
            "content_file": str(principal_scope.content),
        },
    )
    artifact = invoke(
        principal_scope,
        "register_artifact",
        {
            "artifact_type": "demo_artifact",
            "record": {
                "artifact_id": "demo-artifact-record-2",
                "artifact_type": "demo_artifact",
                "path": written["result"]["path"],
                "checksum": written["result"]["checksum"],
            },
        },
    )
    logged = invoke(
        principal_scope,
        "append_log",
        {"log_type": "demo_event", "record": {"event_id": "demo:record-2"}},
    )

    assert copied["result"]["status"] == "ok"
    assert len(written["result"]["checksum"]) == 64
    assert artifact["result"] == {"status": "ok", "artifact_id": "demo-artifact-record-2"}
    assert logged["result"]["status"] == "ok"
    copied_again = invoke(
        principal_scope,
        "copy_source",
        {
            "source": str(principal_scope.source),
            "logical_path": "sources/originals/demo/source.json",
            "source_type": "approved_demo",
            "metadata": {},
        },
    )
    written_again = invoke(
        principal_scope,
        "write_record",
        {
            "record_type": "demo_record",
            "variables": {"record_id": "record-2"},
            "refs": {"source_id": copied["result"]["source_id"]},
            "content_file": str(principal_scope.content),
        },
    )
    logged_again = invoke(
        principal_scope,
        "append_log",
        {"log_type": "demo_event", "record": {"event_id": "demo:record-2"}},
    )
    assert copied_again["result"]["status"] == "already_exists"
    assert written_again["result"]["status"] == "already_exists"
    assert written_again["result"]["checksum"] == written["result"]["checksum"]
    assert logged_again["result"]["status"] == "already_exists"
    digest_pattern = r"sha256:[0-9a-f]{64}"
    for digest in (
        copied["authorization"]["registry_digest"],
        copied["authorization"]["policy_digest"],
        copied["authorization"]["profile_digest"],
        copied["authorization"]["mapping_digest"],
        copied["principal"]["contract_digest"],
    ):
        assert re.fullmatch(digest_pattern, digest)
    assert copied["authorization"]["registry_digest"] == runtime._registry_digest(
        load_principal_registry(principal_scope.registry)
    )
    assert copied["authorization"]["policy_digest"] == domain_policy_digest({})
    assert copied["authorization"]["profile_digest"] == runtime._profile_digest(
        load_active_profile(principal_scope.root)
    )
    assert copied["authorization"]["mapping_digest"] == mapping_digest(
        load_ingest_mapping(principal_scope.mapping)
    )
    assert execute_invocation(
        {
            "protocol_version": "v0.1",
            "request_id": "read-back",
            "principal_id": "demo-harness",
            "operation": "find_records",
            "scope_root": str(principal_scope.root),
            "payload": {"record_type": "demo_record", "lookup_value": "record-2"},
        },
        registry_path=principal_scope.registry,
    )["result"]["status"] == "found"


def test_non_owner_skill_cannot_use_workload_mapping(principal_scope: PrincipalScope):
    registry = load_principal_registry(principal_scope.registry)
    assert {"demo-harness", "demo-skill"}.issubset(registry["principals"])

    target = principal_scope.root / ".llm-wiki" / "domains" / "demo" / "skill-denied.md"
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(
                principal_id="demo-skill",
                scope_root=str(principal_scope.root),
                payload={
                    "record_type": "demo_record",
                    "variables": {"record_id": "skill-denied"},
                    "refs": {},
                    "content_file": str(principal_scope.content),
                },
            ),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "mapping_owner_mismatch"
    assert not target.exists()


def test_failed_principal_write_does_not_fall_back(principal_scope: PrincipalScope, monkeypatch):
    calls = []

    def unexpected_write(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Runtime Core must not be called after authorization denial")

    monkeypatch.setattr(runtime, "write_record", unexpected_write, raising=False)
    with pytest.raises(InvocationError):
        execute_invocation(
            write_request(principal_id="other-harness", scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert calls == []


def test_write_rejects_a_profile_digest_mismatch_before_core(principal_scope: PrincipalScope, monkeypatch):
    principal_scope.profile.write_text(
        principal_scope.profile.read_text(encoding="utf-8").replace("max_results: 20", "max_results: 19"),
        encoding="utf-8",
    )
    calls = []

    def unexpected_write(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Runtime Core must not be called after profile binding denial")

    monkeypatch.setattr(runtime, "write_record", unexpected_write, raising=False)
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "profile_mismatch"
    assert calls == []
