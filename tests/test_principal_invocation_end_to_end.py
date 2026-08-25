from __future__ import annotations

import pytest

import llm_wiki_runtime.invocation as runtime
from llm_wiki_runtime.invocation import InvocationError, execute_invocation
from test_principal_invocation import PrincipalScope, principal_scope, write_request


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
    logged = invoke(
        principal_scope,
        "append_log",
        {"log_type": "demo_event", "record": {"event_id": "demo:record-2"}},
    )

    assert copied["result"]["status"] == "ok"
    assert len(written["result"]["checksum"]) == 64
    assert logged["result"]["status"] == "ok"
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
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(principal_id="other-harness", scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "mapping_owner_mismatch"


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
