import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from llm_wiki_runtime.invocation import InvocationError, execute_invocation, load_invocation
from llm_wiki_runtime.principal import load_principal_manifest
from llm_wiki_runtime.principal_registry import register_workload_principal, write_principal_registry
from llm_wiki_runtime.runtime import init_profile


@dataclass(frozen=True)
class PrincipalScope:
    root: Path
    registry: Path
    profile: Path
    mapping: Path
    source: Path
    content: Path


def _write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def principal_scope(tmp_path: Path) -> PrincipalScope:
    manifest = _write(
        tmp_path / "demo.principal.yml",
        [
            "principal_version: v0.1",
            "principal:",
            "  id: demo-harness",
            "  kind: workload",
            "  role: domain_harness",
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
            "    - domain: demo",
            "      artifact_type: demo_artifact",
            "    - domain: demo",
            "      log_type: demo_event",
        ],
    )
    registry = tmp_path / "principals.json"
    registered = register_workload_principal(
        {"version": "v0.2", "principals": {}, "skills": {}, "domains": {}, "domain_policies": {}, "warnings": []},
        load_principal_manifest(manifest),
    )
    other_manifest = _write(
        tmp_path / "other.principal.yml",
        [
            "principal_version: v0.1",
            "principal:",
            "  id: other-harness",
            "  kind: workload",
            "  role: domain_harness",
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
            "    - domain: demo",
            "      artifact_type: demo_artifact",
            "    - domain: demo",
            "      log_type: demo_event",
        ],
    )
    registered = register_workload_principal(registered, load_principal_manifest(other_manifest))
    write_principal_registry(registered, registry)
    profile = _write(
        tmp_path / "profile.yml",
        [
            "profile:",
            "  id: demo",
            "  version: v0.1",
            "write_rules:",
            "  records:",
            "    demo_record:",
            "      path: domains/demo/{record_id}.md",
            "      mode: create_only",
            "read_rules:",
            "  context_pack:",
            "    include: [domains/demo/**]",
            "    exclude: [.meta/**]",
            "  record_lookup:",
            "    demo_record:",
            "      identity_field: record_id",
            "      display_field: display_name",
            "      match_fields: [record_id, display_name]",
            "      return_fields: [record_id, display_name]",
            "      max_results: 20",
            "artifacts:",
            "  types: [demo_artifact]",
            "logs:",
            "  types:",
            "    demo_event:",
            "      path: logs/demo-events.jsonl",
            "      mode: append_only",
        ],
    )
    init_profile(tmp_path, profile, "local", "demo-test")
    _write(
        tmp_path / ".llm-wiki" / "domains" / "demo" / "record-1.md",
        [
            "---",
            "record_type: demo_record",
            "record_id: record-1",
            'display_name: "Record 1"',
            "---",
            "Demo context.",
        ],
    )
    mapping = _write(
        tmp_path / "mapping.yml",
        [
            "mapping:",
            "  id: demo-mapping",
            "  version: v0.2",
            "  domain: demo",
            "  owner_principal_id: demo-harness",
            "  source_types: [approved_demo]",
            "  instruction_ref: references/demo.md",
            "produces:",
            "  - record_type: demo_record",
            "  - artifact_type: demo_artifact",
            "  - log_type: demo_event",
        ],
    )
    source = tmp_path / "source.json"
    source.write_text('{"demo": true}', encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text("Demo record.", encoding="utf-8")
    return PrincipalScope(tmp_path, registry, profile, mapping, source, content)


def request(**overrides) -> dict:
    value = {
        "protocol_version": "v0.1",
        "request_id": "req-demo",
        "principal_id": "demo-harness",
        "operation": "resolve",
        "scope_root": "C:/scope",
        "payload": {},
    }
    value.update(overrides)
    return value


def write_request(**overrides) -> dict:
    value = request(
        operation="write_record",
        mapping_id="demo-mapping",
        payload={
            "record_type": "demo_record",
            "variables": {"record_id": "record-1"},
            "refs": {},
            "content_file": "C:/content.md",
        },
    )
    value.update(overrides)
    return value


def test_find_records_invocation_returns_principal_observation(principal_scope: PrincipalScope):
    result = execute_invocation(
        request(
            operation="find_records",
            scope_root=str(principal_scope.root),
            payload={"record_type": "demo_record", "lookup_value": "record-1"},
        ),
        registry_path=principal_scope.registry,
    )

    assert result["status"] == "ok"
    assert result["principal"]["kind"] == "workload"
    assert result["authorization"]["decision"] == "allowed"
    assert result["result"]["status"] == "found"


def test_all_invocation_modes_observe_a_canonical_registry_digest(principal_scope: PrincipalScope):
    responses = [
        execute_invocation(
            request(scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
        ),
        execute_invocation(
            request(
                operation="find_records",
                scope_root=str(principal_scope.root),
                payload={"record_type": "demo_record", "lookup_value": "record-1"},
            ),
            registry_path=principal_scope.registry,
        ),
        execute_invocation(
            write_request(
                scope_root=str(principal_scope.root),
                payload={
                    "record_type": "demo_record",
                    "variables": {"record_id": "record-2"},
                    "refs": {},
                    "content_file": str(principal_scope.content),
                },
            ),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        ),
    ]

    for response in responses:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", response["authorization"]["registry_digest"])


def test_invocation_response_canonicalizes_a_legacy_raw_registry_digest(principal_scope: PrincipalScope, monkeypatch):
    import llm_wiki_runtime.invocation as runtime

    monkeypatch.setattr(runtime, "_registry_digest", lambda registry: "a" * 64)

    result = execute_invocation(
        request(scope_root=str(principal_scope.root)),
        registry_path=principal_scope.registry,
    )

    assert result["authorization"]["registry_digest"] == "sha256:" + "a" * 64


def test_invocation_authorization_observation_has_an_exact_contract_key_set(principal_scope: PrincipalScope):
    resolve = execute_invocation(
        request(scope_root=str(principal_scope.root), mapping_id="demo-mapping"),
        registry_path=principal_scope.registry,
        profile_path=principal_scope.profile,
        mapping_path=principal_scope.mapping,
    )
    read = execute_invocation(
        request(
            operation="find_records",
            scope_root=str(principal_scope.root),
            payload={"record_type": "demo_record", "lookup_value": "record-1"},
        ),
        registry_path=principal_scope.registry,
    )
    write = execute_invocation(
        write_request(
            scope_root=str(principal_scope.root),
            payload={
                "record_type": "demo_record",
                "variables": {"record_id": "record-3"},
                "refs": {},
                "content_file": str(principal_scope.content),
            },
        ),
        registry_path=principal_scope.registry,
        profile_path=principal_scope.profile,
        mapping_path=principal_scope.mapping,
    )
    required = {
        "operation",
        "domain",
        "decision",
        "registry_digest",
        "policy_digest",
        "profile_digest",
        "mapping_digest",
    }

    assert set(resolve["authorization"]) == required
    assert set(write["authorization"]) == required
    assert set(read["authorization"]) == required - {"mapping_digest"}
    for response in (resolve, read, write):
        assert response["principal"]["contract_digest"].startswith("sha256:")


def test_unknown_invocation_operation_is_rejected(principal_scope: PrincipalScope):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(operation="graph_export", scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
        )

    assert exc.value.code == "operation_not_allowed"


def test_load_context_invocation_uses_profile_limits(principal_scope: PrincipalScope):
    result = execute_invocation(
        request(
            operation="load_context",
            scope_root=str(principal_scope.root),
            payload={"max_files": 1, "max_chars_per_file": 4},
        ),
        registry_path=principal_scope.registry,
    )

    assert result["result"]["included_count"] == 1
    assert result["result"]["items"][0]["content"] == "---\n"


def test_invocation_rejects_missing_principal(principal_scope: PrincipalScope):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(principal_id="missing", scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
        )

    assert exc.value.code == "principal_not_found"


def test_invocation_rejects_stale_principal_contract(principal_scope: PrincipalScope):
    contract = principal_scope.root / "demo.principal.yml"
    contract.write_text(contract.read_text(encoding="utf-8").replace("profile: demo", "profile: changed"), encoding="utf-8")

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(scope_root=str(principal_scope.root)), registry_path=principal_scope.registry
        )

    assert exc.value.code == "principal_contract_stale"


def test_invocation_reports_missing_active_profile_as_invalid_request(principal_scope: PrincipalScope):
    (principal_scope.root / ".llm-wiki" / ".meta" / "profile.yml").unlink()

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(scope_root=str(principal_scope.root)), registry_path=principal_scope.registry
        )

    assert exc.value.code == "invalid_invocation"


@pytest.mark.parametrize(
    ("mapping_path", "mapping_id"),
    [("present", None), (None, "demo-ingest")],
)
def test_mapping_path_and_id_must_appear_together(
    principal_scope: PrincipalScope, mapping_path: str | None, mapping_id: str | None
):
    invocation = request(scope_root=str(principal_scope.root))
    if mapping_id:
        invocation["mapping_id"] = mapping_id

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            invocation,
            registry_path=principal_scope.registry,
            mapping_path=principal_scope.mapping if mapping_path else None,
        )

    assert exc.value.code == "invalid_invocation"


def test_resolve_validates_profile_mapping_and_returns_contract_digests(principal_scope: PrincipalScope):
    result = execute_invocation(
        request(scope_root=str(principal_scope.root), mapping_id="demo-mapping"),
        registry_path=principal_scope.registry,
        profile_path=principal_scope.profile,
        mapping_path=principal_scope.mapping,
    )

    assert result["authorization"]["profile_digest"].startswith("sha256:")
    assert result["authorization"]["mapping_digest"].startswith("sha256:")


def test_resolve_rejects_mismatched_mapping_id(principal_scope: PrincipalScope):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(scope_root=str(principal_scope.root), mapping_id="other"),
            registry_path=principal_scope.registry,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "invalid_invocation"


def test_mapping_preflight_rejects_a_different_registered_owner(principal_scope: PrincipalScope):
    principal_scope.mapping.write_text(
        principal_scope.mapping.read_text(encoding="utf-8").replace("demo-harness", "other-harness"),
        encoding="utf-8",
    )

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(scope_root=str(principal_scope.root), mapping_id="demo-mapping"),
            registry_path=principal_scope.registry,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "mapping_owner_mismatch"


def test_resolve_rejects_payload_before_authorization(principal_scope: PrincipalScope):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(scope_root=str(principal_scope.root), payload={"target_domain": "secret"}),
            registry_path=principal_scope.registry,
            domain_policies={"secret": {"readable_by": []}},
        )

    assert exc.value.code == "invalid_invocation"


def test_resolve_rejects_explicit_profile_not_declared_by_principal(principal_scope: PrincipalScope):
    other_profile = _write(
        principal_scope.root / "other-profile.yml",
        [
            "profile:",
            "  id: other",
            "  version: v0.1",
        ],
    )

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
            profile_path=other_profile,
        )

    assert exc.value.code == "invalid_invocation"


def test_find_records_observes_the_active_profile_digest(principal_scope: PrincipalScope):
    alternate_profile = _write(
        principal_scope.root / "alternate-profile.yml",
        [
            "profile:",
            "  id: demo",
            "  version: v0.1",
            "read_rules:",
            "  context_pack:",
            "    include: [other/**]",
        ],
    )
    invocation = request(
        operation="find_records",
        scope_root=str(principal_scope.root),
        payload={"record_type": "demo_record", "lookup_value": "record-1"},
    )

    observed = execute_invocation(
        invocation,
        registry_path=principal_scope.registry,
        profile_path=alternate_profile,
    )
    active = execute_invocation(invocation, registry_path=principal_scope.registry)

    assert observed["authorization"]["profile_digest"] == active["authorization"]["profile_digest"]


def test_load_invocation_uses_a_bounded_binary_read(tmp_path: Path):
    path = tmp_path / "request.json"
    expected = {"request_id": "req-demo"}
    path.write_text(json.dumps(expected), encoding="utf-8")

    class BinaryOnlyPath:
        def open(self, *args, **kwargs):
            return path.open(*args, **kwargs)

        def stat(self):
            raise AssertionError("unbounded path helper used")

        def read_text(self, *args, **kwargs):
            raise AssertionError("unbounded path helper used")

    assert load_invocation(BinaryOnlyPath(), max_bytes=100) == expected


def test_invocation_rejects_non_object_domain_policies(principal_scope: PrincipalScope):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            request(scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
            domain_policies=[],
        )

    assert exc.value.code == "invalid_invocation"


def test_load_invocation_rejects_large_file(tmp_path: Path):
    path = tmp_path / "request.json"
    path.write_text("x" * 11, encoding="utf-8")

    with pytest.raises(InvocationError) as exc:
        load_invocation(path, max_bytes=10)

    assert exc.value.code == "invalid_invocation"


@pytest.mark.parametrize(
    ("mapping_path", "profile_path"),
    [(None, "present"), ("present", None)],
)
def test_write_invocation_requires_mapping_and_profile_paths(
    principal_scope: PrincipalScope, mapping_path: str | None, profile_path: str | None
):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
            mapping_path=principal_scope.mapping if mapping_path else None,
            profile_path=principal_scope.profile if profile_path else None,
        )

    assert exc.value.code == "invalid_invocation"


def test_write_invocation_rejects_unknown_payload_key_before_core(principal_scope: PrincipalScope, monkeypatch):
    import llm_wiki_runtime.invocation as runtime

    calls = []

    def unexpected_write(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Runtime Core must not be called after payload validation denial")

    monkeypatch.setattr(runtime, "write_record", unexpected_write, raising=False)
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(
                scope_root=str(principal_scope.root),
                payload={
                    "record_type": "demo_record",
                    "variables": {"record_id": "record-1"},
                    "refs": {},
                    "content_file": str(principal_scope.content),
                    "extra": True,
                },
            ),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "invalid_invocation"
    assert calls == []


def test_write_invocation_does_not_accept_a_legacy_mapping(principal_scope: PrincipalScope):
    principal_scope.mapping.write_text(
        principal_scope.mapping.read_text(encoding="utf-8")
        .replace("version: v0.2", "version: v0.1")
        .replace("owner_principal_id", "owner_skill_id"),
        encoding="utf-8",
    )

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(scope_root=str(principal_scope.root)),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "invalid_invocation"


@pytest.mark.parametrize(
    ("operation", "payload", "target"),
    [
        (
            "copy_source",
            {
                "source": "C:/source.json",
                "logical_path": "sources/originals/demo/extra.json",
                "source_type": "approved_demo",
                "metadata": {},
                "extra": True,
            },
            "sources/originals/demo/extra.json",
        ),
        (
            "write_record",
            {
                "record_type": "demo_record",
                "variables": {"record_id": "extra"},
                "refs": {},
                "content_file": "C:/content.md",
                "extra": True,
            },
            "domains/demo/extra.md",
        ),
        (
            "register_artifact",
            {
                "artifact_type": "demo_artifact",
                "record": {"artifact_id": "demo-artifact-extra", "artifact_type": "demo_artifact"},
                "extra": True,
            },
            "artifacts/index.json",
        ),
        (
            "append_log",
            {
                "log_type": "demo_event",
                "record": {"event_id": "demo:extra"},
                "extra": True,
            },
            "logs/demo-events.jsonl",
        ),
    ],
)
def test_write_invocation_rejects_extra_payload_keys_without_writing(
    principal_scope: PrincipalScope, operation: str, payload: dict, target: str
):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(scope_root=str(principal_scope.root), operation=operation, payload=payload),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "invalid_invocation"
    assert not (principal_scope.root / ".llm-wiki" / target).exists()


@pytest.mark.parametrize(
    "record",
    [
        [],
        {},
        {"artifact_id": "demo-artifact-invalid"},
        {"artifact_type": "demo_artifact"},
        {"artifact_id": "not a safe id", "artifact_type": "demo_artifact"},
        {"artifact_id": "demo-artifact-invalid", "artifact_type": "other_artifact"},
    ],
)
def test_register_artifact_requires_a_bound_safe_record_before_writing(
    principal_scope: PrincipalScope, record: object
):
    index = principal_scope.root / ".llm-wiki" / "artifacts" / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    original = '{"artifacts":[{"artifact_id":"existing"}]}'
    index.write_text(original, encoding="utf-8")

    with pytest.raises(InvocationError) as exc:
        execute_invocation(
            write_request(
                scope_root=str(principal_scope.root),
                operation="register_artifact",
                payload={"artifact_type": "demo_artifact", "record": record},
            ),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )

    assert exc.value.code == "invalid_invocation"
    assert index.read_text(encoding="utf-8") == original
