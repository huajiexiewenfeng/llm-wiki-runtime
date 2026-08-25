import json
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
        ],
    )
    registry = tmp_path / "principals.json"
    registered = register_workload_principal(
        {"version": "v0.2", "principals": {}, "skills": {}, "domains": {}, "domain_policies": {}, "warnings": []},
        load_principal_manifest(manifest),
    )
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
            "  id: demo-ingest",
            "  version: v0.2",
            "  domain: demo",
            "  owner_principal_id: demo-harness",
            "  source_types: [demo_source]",
            "  instruction_ref: references/demo.md",
            "produces:",
            "  - record_type: demo_record",
        ],
    )
    return PrincipalScope(tmp_path, registry, profile, mapping)


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
        request(scope_root=str(principal_scope.root), mapping_id="demo-ingest"),
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


def test_load_invocation_rejects_large_file(tmp_path: Path):
    path = tmp_path / "request.json"
    path.write_text("x" * 11, encoding="utf-8")

    with pytest.raises(InvocationError) as exc:
        load_invocation(path, max_bytes=10)

    assert exc.value.code == "invalid_invocation"
