# Principal + Workload Runtime v0.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `llm-wiki-runtime` from a Skill-only integration model to a backward-compatible Principal runtime in which Skill and `workload/domain_harness` callers share one Registry, authorization model, and Principal-aware invocation boundary.

**Architecture:** Add a normalized Principal Contract and Registry v0.2 above the existing Profile, Policy, Mapping, and Runtime Core. Preserve SCP and legacy CLI behavior through compatibility adapters, while all new Workload callers use one `invoke` request envelope that authorizes the actual query or write before delegating to existing Core functions.

**Tech Stack:** Python 3.10+, standard library only, `argparse`, immutable JSON/YAML-like contracts, pytest 9.1.1, local filesystem Runtime Core.

## Global Constraints

- Target package/runtime version is exactly `0.3.0`.
- Do not add third-party runtime dependencies; `[project].dependencies` remains empty.
- Supported Principal kinds are exactly `skill` and `workload`; the only supported Workload role is `domain_harness`.
- `principal.yml` is a declaration, not a way to override Host/Domain Policy.
- `skill` and `workload` may coexist in the same Domain and Workspace.
- Registry `principals` is authoritative; `skills` is a deterministic read-only compatibility projection.
- Existing SCP v0.1, Registry v0.1 input, Mapping v0.1 `owner_skill_id`, and existing CLI commands remain compatible throughout `0.3.x`.
- New Workload integrations must use `llm-wiki invoke`; an Invocation failure must never fall back to a legacy write command.
- `mapping_id` and `--mapping-path` must appear together. Runtime must verify the declared logical Mapping ID against the loaded Mapping Contract and its digest; every write Invocation requires both.
- Runtime, Principal, Profile, Mapping, and Policy changes stale unexecuted Plans/Approvals; terminal complete Receipts remain historical and their records remain read-only queryable when checksums match.
- Runtime Core remains the only writer of `.llm-wiki`; do not duplicate its locks, atomic IO, Profile path rendering, record lookup, or context loading.
- Historical and external content remains `data_only`; Principal kind never raises content trust.
- Do not implement MCP, semantic/vector search, cloud identity, signatures, multi-user auth, additional Workload roles, or a new storage layer.
- Preserve the untracked user-owned file `docs/superpowers/specs/2026-07-30-llm-wiki-runtime-mcp-adapter-assessment.zh.md`; do not stage or commit it.

---

## File Structure

### New Runtime units

- `llm_wiki_runtime/contract_yaml.py` — parse the existing constrained SCP/Principal YAML shape without adding PyYAML.
- `llm_wiki_runtime/principal.py` — normalize and validate Skill/Workload Principal Contracts and compute canonical digests.
- `llm_wiki_runtime/principal_registry.py` — normalize v0.1 Registry input, build Registry v0.2, preserve the Skill projection, and register/refresh Workloads atomically.
- `llm_wiki_runtime/authorization.py` — calculate effective query/write capability and return stable denial codes.
- `llm_wiki_runtime/invocation.py` — validate one Principal-aware request, authorize it, delegate to existing Runtime Core, and attach observations.

### Modified Runtime units

- `llm_wiki_runtime/scp.py` — become the SCP compatibility adapter and emit/merge Principal Registry v0.2.
- `llm_wiki_runtime/mapping.py` — accept Mapping v0.1/v0.2 and resolve one Owner Principal.
- `llm_wiki_runtime/cli.py` — add `register-principal` and `invoke`; map stable statuses to exit codes.
- `llm_wiki_runtime/policy.py` — expose deterministic effective instruction/read policy observations without changing existing defaults.
- `llm_wiki_runtime/__init__.py` and `pyproject.toml` — bump to `0.3.0` only after the feature suite passes.
- `README.md`, `README.zh-CN.md`, `docs/guides/domain-skill-integration-quickstart.zh.md`, and `skills/llm-wiki-core/references/status-v0.1.md` — document Workload usage, compatibility, and statuses.

### New/modified tests

- Create `tests/test_principal_contract.py`.
- Create `tests/test_principal_registry.py`.
- Create `tests/test_principal_authorization.py`.
- Create `tests/test_principal_invocation.py`.
- Create `tests/test_principal_invocation_end_to_end.py`.
- Modify `tests/test_scp_registry.py`, `tests/test_mapping.py`, `tests/test_cli.py`, and `tests/test_skill_package.py`.

---

### Task 1: Principal Contract parser and canonical identity

**Files:**
- Create: `llm_wiki_runtime/contract_yaml.py`
- Create: `llm_wiki_runtime/principal.py`
- Create: `tests/test_principal_contract.py`
- Modify: `llm_wiki_runtime/scp.py`
- Test: `tests/test_scp_registry.py`

**Interfaces:**
- Produces: `load_contract_document(path: Path, identity_section: str) -> dict`
- Produces: `load_principal_manifest(path: Path) -> dict`
- Produces: `principal_from_scp(scp: dict) -> dict`
- Produces: `principal_contract_digest(contract: dict) -> str`
- Consumes: existing `profile.parse_scalar()` and `paths.validate_slug()`.

- [ ] **Step 1: Write failing Principal Contract tests**

Create tests that cover a valid Workload, an unsupported role, unsafe IDs, cross-Domain produces, forbidden extra identity fields, and deterministic digest:

```python
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


def test_load_workload_principal_contract(tmp_path: Path):
    path = tmp_path / "principal.yml"
    path.write_text(WORKLOAD, encoding="utf-8")
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
    first.write_text(WORKLOAD, encoding="utf-8")
    second.write_text(WORKLOAD, encoding="utf-8")
    assert principal_contract_digest(load_principal_manifest(first)) == principal_contract_digest(
        load_principal_manifest(second)
    )


def test_rejects_unsupported_workload_role(tmp_path: Path):
    path = tmp_path / "principal.yml"
    path.write_text(WORKLOAD.replace("domain_harness", "service"), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported workload role"):
        load_principal_manifest(path)


def test_scp_normalizes_to_skill_principal(tmp_path: Path):
    path = tmp_path / "scp.yml"
    path.write_text(
        WORKLOAD.replace("principal_version: v0.1", "scp_version: v0.1")
        .replace("principal:", "skill:")
        .replace("  kind: workload\n", "")
        .replace("  role: domain_harness\n", ""),
        encoding="utf-8",
    )
    principal = principal_from_scp(load_scp(path))
    assert principal["principal"]["kind"] == "skill"
    assert principal["principal"]["id"] == "ai-research-observatory-harness"
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_principal_contract.py tests/test_scp_registry.py -q
```

Expected: collection fails because `llm_wiki_runtime.principal` and `load_contract_document` do not exist.

- [ ] **Step 3: Extract the constrained YAML parser**

Move the line-oriented section/list parsing currently embedded in `load_scp()` into `load_contract_document(path, identity_section)`. Reject an identity section other than `skill` or `principal`; parse top-level scalars, the selected identity mapping, `llm_wiki`, `trust`, `query.supports`, and `ingest.produces` with the existing `parse_scalar()` behavior; and attach `_path` only as Runtime metadata. Canonical digest calculation must remove `_path`.

Change `load_scp()` to:

```python
def load_scp(path: Path) -> dict:
    return load_contract_document(path, "skill")
```

The extracted parser must reproduce every current `test_scp_registry.py` result before Principal validation is added.

- [ ] **Step 4: Implement Principal validation and digest**

Use these constants and public functions:

```python
PRINCIPAL_VERSION = "v0.1"
SUPPORTED_KINDS = frozenset({"skill", "workload"})
SUPPORTED_WORKLOAD_ROLES = frozenset({"domain_harness"})
CONTRACT_KINDS = ("record_type", "artifact_type", "log_type")


def principal_contract_digest(contract: dict) -> str:
    body = {key: value for key, value in contract.items() if key != "_path"}
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def load_principal_manifest(path: Path) -> dict:
    contract = load_contract_document(path, "principal")
    validate_principal_contract(contract, expected_kind="workload")
    return contract


def principal_from_scp(scp: dict) -> dict:
    contract = {
        "principal_version": "v0.1",
        "principal": {
            "id": scp["skill"]["id"],
            "kind": "skill",
            "domain": scp["skill"]["domain"],
        },
        "llm_wiki": dict(scp.get("llm_wiki", {})),
        "trust": dict(scp.get("trust", {})),
        "query": dict(scp.get("query", {"supports": []})),
        "ingest": dict(scp.get("ingest", {"produces": []})),
        "_path": scp.get("_path"),
    }
    validate_principal_contract(contract, expected_kind="skill")
    return contract
```

Validation must require exact identity keys, safe IDs, `query.primary_domain == principal.domain`, and every produced item’s `domain == principal.domain`. It must reject any product without exactly one contract kind.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_principal_contract.py tests/test_scp_registry.py -q
```

Expected: all tests pass; existing SCP parsing behavior is unchanged.

- [ ] **Step 6: Commit Task 1**

```powershell
git add llm_wiki_runtime/contract_yaml.py llm_wiki_runtime/principal.py llm_wiki_runtime/scp.py tests/test_principal_contract.py tests/test_scp_registry.py
git commit -m "feat: add principal contract model"
```

---

### Task 2: Unified Principal Registry v0.2 and Workload registration

**Files:**
- Create: `llm_wiki_runtime/principal_registry.py`
- Create: `tests/test_principal_registry.py`
- Modify: `llm_wiki_runtime/scp.py`
- Modify: `tests/test_scp_registry.py`

**Interfaces:**
- Consumes: Task 1 Principal Contract functions.
- Produces: `normalize_registry(registry: dict) -> dict`
- Produces: `load_principal_registry(path: Path) -> dict`
- Produces: `build_principal_registry(scp_paths, existing_registry, domain_policies, caller_groups) -> dict`
- Produces: `register_workload_principal(registry, manifest, refresh=False) -> dict`
- Produces: `write_principal_registry(registry, path) -> Path`
- Produces: `resolve_principal(registry, principal_id) -> dict` with stale Contract verification.

- [ ] **Step 1: Write failing Registry tests**

Cover v0.1 normalization, Skill projection, Workload preservation during SCP rescan, idempotent registration, explicit refresh, kind conflict, and read-only load:

```python
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


def test_changed_workload_requires_explicit_refresh(tmp_path):
    first = load_principal_manifest(write_workload_manifest(tmp_path, profile="demo"))
    registry = register_workload_principal(empty_registry(), first)
    changed = load_principal_manifest(write_workload_manifest(tmp_path, profile="demo-v2"))
    with pytest.raises(PrincipalRegistryError) as exc:
        register_workload_principal(registry, changed)
    assert exc.value.code == "principal_contract_stale"
    refreshed = register_workload_principal(registry, changed, refresh=True)
    assert refreshed["principals"]["demo-harness"]["profile"] == "demo-v2"
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_principal_registry.py tests/test_scp_registry.py -q
```

Expected: import/attribute failures for the new Registry interfaces.

- [ ] **Step 3: Implement the canonical Registry entry and projection**

Each canonical entry must contain:

```python
{
    "kind": contract["principal"]["kind"],
    "role": contract["principal"].get("role"),
    "domain": contract["principal"]["domain"],
    "profile": contract["llm_wiki"].get("profile"),
    "contract_path": contract["_path"],
    "contract_digest": principal_contract_digest(contract),
    "origin": "legacy_scp" if kind == "skill" else "principal_manifest",
    "fallback_mode": contract["llm_wiki"].get("fallback_mode", "markdown"),
    "trust_level": contract["trust"].get("level"),
    "instruction_policy": contract["trust"].get("instruction_policy"),
    "produces": contract["ingest"].get("produces", []),
    "supports": accepted_support_domains,
    "support_filters": accepted_support_filters,
}
```

Build `skills` only through:

```python
registry["skills"] = {
    principal_id: entry
    for principal_id, entry in registry["principals"].items()
    if entry["kind"] == "skill"
}
```

Never mutate `skills` independently. Validate an input Registry containing both keys by recomputing the projection and returning `principal_conflict` on mismatch.

- [ ] **Step 4: Make SCP build/write functions use Registry v0.2**

Retain the public `build_registry()` and `write_registry()` names as compatibility aliases:

```python
def build_registry(scp_paths, domain_policies=None, caller_groups=None, existing_registry=None):
    return build_principal_registry(
        scp_paths,
        existing_registry=existing_registry,
        domain_policies=domain_policies,
        caller_groups=caller_groups,
    )


def write_registry(registry: dict, path: Path | None = None) -> Path:
    return write_principal_registry(normalize_registry(registry), path or skill_registry_path())
```

Do not rename or delete `skill_registry_path()` in `0.3.0`; it remains a compatibility storage locator even though the stored schema is Principal Registry v0.2.

- [ ] **Step 5: Add atomic Workload registration semantics**

`register_workload_principal()` must copy the input Registry, enforce `kind=workload/role=domain_harness`, and only replace a changed Workload when `refresh=True`. It must reject replacement of an SCP-origin Skill. `write_principal_registry()` must use `atomic_write_json()`.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_principal_registry.py tests/test_scp_registry.py -q
```

Expected: all pass, including the old `registry["skills"]` assertions.

- [ ] **Step 7: Commit Task 2**

```powershell
git add llm_wiki_runtime/principal_registry.py llm_wiki_runtime/scp.py tests/test_principal_registry.py tests/test_scp_registry.py
git commit -m "feat: add unified principal registry"
```

---

### Task 3: Mapping v0.2 and single Owner Principal

**Files:**
- Modify: `llm_wiki_runtime/mapping.py`
- Modify: `tests/test_mapping.py`

**Interfaces:**
- Consumes: `normalize_registry()` and `resolve_principal()` from Task 2.
- Produces: normalized Mapping key `owner_principal_id`.
- Produces: `validate_ingest_mapping()` result with `owner_principal_id`, `principal_kind`, `mapping_digest`, and typed `produces`.

- [ ] **Step 1: Add failing Mapping compatibility tests**

```python
def test_mapping_v02_uses_workload_owner(tmp_path):
    mapping = load_ingest_mapping(write_v02_mapping(tmp_path))
    registry, profile = workload_registry_and_profile(tmp_path)
    result = validate_ingest_mapping(mapping, registry, profile)
    assert result["owner_principal_id"] == "demo-harness"
    assert result["principal_kind"] == "workload"
    assert result["mapping_digest"].startswith("sha256:")


def test_v01_owner_skill_id_is_normalized(tmp_path):
    mapping, registry, profile = load_contract(tmp_path)
    result = validate_ingest_mapping(mapping, registry, profile)
    assert result["owner_principal_id"] == "hr-resume-screening-copilot"
    assert result["owner_skill_id"] == "hr-resume-screening-copilot"


def test_mapping_rejects_two_owner_fields(tmp_path):
    path = write_v02_mapping(tmp_path, include_legacy_owner=True)
    with pytest.raises(ValueError, match="exactly one owner"):
        load_ingest_mapping(path)
```

- [ ] **Step 2: Run Mapping tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_mapping.py -q
```

Expected: v0.2 is rejected and `owner_principal_id` is absent.

- [ ] **Step 3: Implement versioned owner parsing**

Define `SUPPORTED_MAPPING_VERSIONS = frozenset({"v0.1", "v0.2"})` and `OWNER_FIELDS = frozenset({"owner_skill_id", "owner_principal_id"})`. Require `owner_skill_id` for v0.1, require `owner_principal_id` for v0.2, and require exactly one owner field in every document. Normalize both versions to `owner_principal_id`; retain `_legacy_owner_skill_id` only in memory for the v0.1 compatibility response.

Compute `mapping_digest` from the normalized mapping without `_path` or compatibility-only output fields.

- [ ] **Step 4: Validate the Owner Principal Contract**

Replace SCP-specific loading with `resolve_principal()`. Verify each Mapping product exists in the canonical Principal entry’s typed `produces`, then verify it exists in the Profile. Return `owner_skill_id` only for a v0.1 Mapping compatibility response.

- [ ] **Step 5: Run Mapping and CLI Mapping tests**

Run:

```powershell
python -m pytest tests/test_mapping.py tests/test_cli.py -k "mapping" -q
```

Expected: v0.1 tests remain green and v0.2 Workload tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add llm_wiki_runtime/mapping.py tests/test_mapping.py
git commit -m "feat: authorize mappings by principal"
```

---

### Task 4: Effective Principal authorization

**Files:**
- Create: `llm_wiki_runtime/authorization.py`
- Create: `tests/test_principal_authorization.py`
- Modify: `llm_wiki_runtime/policy.py`

**Interfaces:**
- Consumes: canonical Principal entry, Mapping, Profile, existing Domain Policy functions.
- Produces: `AuthorizationError(code, message)`.
- Produces: `authorize_query(*, principal, operation, target_domain, domain_policies, caller_groups) -> dict`.
- Produces: `authorize_write(*, principal_id, principal, operation, product, mapping, profile) -> dict`.

- [ ] **Step 1: Write failing authorization tests**

Cover same-Domain query, undeclared supporting Domain, Host Policy denial, Mapping owner mismatch, undeclared product, and Profile mismatch:

```python
def test_same_domain_query_is_allowed():
    result = authorize_query(
        principal=principal(domain="demo"),
        operation="find_records",
        target_domain="demo",
        domain_policies={},
        caller_groups=[],
    )
    assert result["decision"] == "allowed"


def test_mapping_owner_mismatch_is_stable_error():
    with pytest.raises(AuthorizationError) as exc:
        authorize_write(
            principal_id="other-harness",
            principal=principal(domain="demo"),
            operation="write_record",
            product={"record_type": "demo_record"},
            mapping=mapping(owner="demo-harness"),
            profile=profile_with_demo_record(),
        )
    assert exc.value.code == "mapping_owner_mismatch"


def test_manifest_cannot_produce_type_absent_from_profile():
    with pytest.raises(AuthorizationError) as exc:
        authorize_write(
            principal_id="demo-harness",
            principal=principal(
                domain="demo",
                produced_records=["demo_record"],
            ),
            operation="write_record",
            product={"record_type": "demo_record"},
            mapping=mapping(
                owner="demo-harness",
                record_types=["demo_record"],
            ),
            profile=profile_with_record_types([]),
        )
    assert exc.value.code == "profile_mismatch"
```

- [ ] **Step 2: Run tests and confirm RED**

```powershell
python -m pytest tests/test_principal_authorization.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement stable authorization errors and observations**

```python
class AuthorizationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


QUERY_OPERATIONS = frozenset({"resolve", "find_records", "load_context"})
WRITE_OPERATION_KIND = {
    "write_record": "record_type",
    "register_artifact": "artifact_type",
    "append_log": "log_type",
}
```

`authorize_query()` must require the target to be the primary Domain or an accepted support and then call `assert_read_allowed()`. `authorize_write()` must require Mapping ownership, same Mapping/Principal Domain, a typed product in both Principal and Mapping, and a matching Profile rule. `copy_source` is authorized by `mapping.source_types` rather than a produced contract kind.

Return only deterministic metadata:

```python
{
    "operation": operation,
    "domain": target_domain,
    "decision": "allowed",
    "policy_digest": domain_policy_digest(domain_policies),
}
```

- [ ] **Step 4: Preserve existing Policy behavior**

Do not change same-Domain or cross-Domain defaults in `assert_read_allowed()`. Add only a deterministic `domain_policy_digest()` helper used by observations.

- [ ] **Step 5: Run focused authorization and policy tests**

```powershell
python -m pytest tests/test_principal_authorization.py tests/test_policy.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add llm_wiki_runtime/authorization.py llm_wiki_runtime/policy.py tests/test_principal_authorization.py tests/test_policy.py
git commit -m "feat: enforce principal capabilities"
```

---

### Task 5: Principal-aware read Invocation

**Files:**
- Create: `llm_wiki_runtime/invocation.py`
- Create: `tests/test_principal_invocation.py`
- Modify: `llm_wiki_runtime/cli.py`

**Interfaces:**
- Consumes: Tasks 2–4 Registry, Mapping, and authorization functions.
- Produces: `load_invocation(path: Path, max_bytes=1_000_000) -> dict`.
- Produces: `execute_invocation(request, registry_path, profile_path=None, mapping_path=None, domain_policies=None) -> dict`.
- Produces: CLI `invoke --request --registry-path [--profile-path] [--mapping-path] [--domain-policies-json]`.

- [ ] **Step 1: Write failing read Invocation tests**

Create fixtures containing a v0.2 Registry and active Profile, then test `resolve`, exact `find_records`, bounded `load_context`, unknown operation, missing Principal, and contract drift:

```python
def test_find_records_invocation_returns_principal_observation(principal_scope):
    result = execute_invocation(
        {
            "protocol_version": "v0.1",
            "request_id": "req-find-demo",
            "principal_id": "demo-harness",
            "operation": "find_records",
            "scope_root": str(principal_scope.root),
            "payload": {"record_type": "demo_record", "lookup_value": "record-1"},
        },
        registry_path=principal_scope.registry,
    )
    assert result["status"] == "ok"
    assert result["principal"]["kind"] == "workload"
    assert result["authorization"]["decision"] == "allowed"
    assert result["result"]["status"] == "found"


def test_unknown_invocation_operation_is_rejected(principal_scope):
    with pytest.raises(InvocationError) as exc:
        execute_invocation(request(operation="graph_export"), registry_path=principal_scope.registry)
    assert exc.value.code == "operation_not_allowed"
```

- [ ] **Step 2: Run tests and confirm RED**

```powershell
python -m pytest tests/test_principal_invocation.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement strict Envelope validation**

Require exactly these top-level keys for read operations:

```python
REQUIRED_INVOCATION_FIELDS = {
    "protocol_version",
    "request_id",
    "principal_id",
    "operation",
    "scope_root",
    "payload",
}
OPTIONAL_INVOCATION_FIELDS = {"mapping_id"}
INVOCATION_VERSION = "v0.1"
ALLOWED_OPERATIONS = frozenset(
    {"resolve", "find_records", "load_context", "copy_source", "write_record", "register_artifact", "append_log"}
)
```

Reject unknown fields, unsafe IDs, non-object payloads, files larger than the byte cap, non-absolute/nonexistent scope roots, unsupported kinds/roles, and a Registry Contract digest that no longer matches its Contract file. Require `mapping_id` exactly when `--mapping-path` is present; load that Contract and reject `invalid_invocation` when its `mapping.id` differs from the declared logical ID.

- [ ] **Step 4: Dispatch read operations to existing Core**

Map payload fields exactly:

```text
find_records:
  record_type, lookup_value, target_domain?

load_context:
  include, exclude, max_files, max_chars_per_file,
  path_filters, glob_filters, order, policy, target_domain?

resolve:
  no operation-specific payload; return Principal/Profile readiness
```

Call `find_records()` and `load_context_pack()` directly. Reuse Active Profile read rules and preserve existing result status/cardinality. Wrap the unchanged Core result under `result` and add Principal/Authorization observations.

When `resolve` receives explicit Profile and Mapping paths, require the request's matching `mapping_id`, validate both Contracts without writing, and include their canonical digests in the Authorization observation. This is the Harness preflight used to bind a pending Plan; omitting the Mapping path and ID omits only the inapplicable Mapping digest.

- [ ] **Step 5: Add CLI parsing and stable error emission**

Add:

```python
invoke_parser = sub.add_parser("invoke")
invoke_parser.add_argument("--request", required=True)
invoke_parser.add_argument("--registry-path", required=True)
invoke_parser.add_argument("--profile-path")
invoke_parser.add_argument("--mapping-path")
invoke_parser.add_argument("--domain-policies-json")
```

Map `principal_not_found`, `principal_contract_stale`, `principal_domain_mismatch`, `capability_denied`, `operation_not_allowed`, and `invalid_invocation` to exit code 2. Preserve `read_denied` as exit code 1 inside a successful authorized Core read only when the Core returns it.

- [ ] **Step 6: Run focused tests**

```powershell
python -m pytest tests/test_principal_invocation.py tests/test_cli.py -k "invoke or find_records or context" -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 5**

```powershell
git add llm_wiki_runtime/invocation.py llm_wiki_runtime/cli.py tests/test_principal_invocation.py tests/test_cli.py
git commit -m "feat: add principal-aware read invocation"
```

---

### Task 6: Principal-aware write Invocation

**Files:**
- Modify: `llm_wiki_runtime/invocation.py`
- Modify: `tests/test_principal_invocation.py`
- Create: `tests/test_principal_invocation_end_to_end.py`
- Test: existing `tests/test_write_record.py`, `tests/test_context_pack.py`, and `tests/test_record_lookup_end_to_end.py`.

**Interfaces:**
- Extends: Task 5 `execute_invocation()`.
- Delegates: existing `copy_source()`, `write_record()`, `register_artifact()`, and `append_profile_log()`.

- [ ] **Step 1: Write failing write Invocation tests**

Test one approved write sequence and each denial boundary:

The `write_request()` fixture must set `mapping_id: demo-mapping` by default so every write request is valid before the specific authorization condition under test is evaluated.

```python
def test_workload_can_copy_write_log_and_read_back(principal_scope):
    copied = invoke(principal_scope, "copy_source", {"source": str(principal_scope.source), "logical_path": "sources/originals/demo/source.json", "source_type": "approved_demo", "metadata": {}})
    written = invoke(principal_scope, "write_record", {"record_type": "demo_record", "variables": {"record_id": "record-1"}, "refs": {"source_id": copied["result"]["source_id"]}, "content_file": str(principal_scope.content)})
    logged = invoke(principal_scope, "append_log", {"log_type": "demo_event", "record": {"event_id": "demo:record-1"}})
    assert copied["result"]["status"] == "ok"
    assert written["result"]["checksum"]
    assert logged["result"]["status"] == "ok"


def test_non_owner_skill_cannot_use_workload_mapping(principal_scope):
    request = write_request(principal_id="demo-skill", operation="write_record")
    with pytest.raises(InvocationError) as exc:
        execute_invocation(request, registry_path=principal_scope.registry, profile_path=principal_scope.profile, mapping_path=principal_scope.mapping)
    assert exc.value.code == "mapping_owner_mismatch"


def test_failed_principal_write_does_not_fall_back(principal_scope, monkeypatch):
    calls = []

    def unexpected_write(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Runtime Core must not be called after authorization denial")

    monkeypatch.setattr(runtime, "write_record", unexpected_write)
    with pytest.raises(InvocationError):
        execute_invocation(
            write_request(principal_id="demo-skill", operation="write_record"),
            registry_path=principal_scope.registry,
            profile_path=principal_scope.profile,
            mapping_path=principal_scope.mapping,
        )
    assert calls == []
```

- [ ] **Step 2: Run tests and confirm RED**

```powershell
python -m pytest tests/test_principal_invocation.py tests/test_principal_invocation_end_to_end.py -q
```

Expected: write operations return `operation_not_allowed` or lack dispatch.

- [ ] **Step 3: Implement typed write authorization and Core delegation**

Require request `mapping_id`, CLI `--mapping-path`, and CLI `--profile-path` for every write Invocation. Load and validate the Mapping before any Core call, require its logical ID to equal the request value, and bind its canonical digest. Compare the packaged Profile digest with `scope_root / ".llm-wiki" / ".meta" / "profile.yml"`; return `profile_mismatch` before writing when they differ.

Use exact payload schemas:

```text
copy_source:
  source, logical_path, source_type, metadata

write_record:
  record_type, variables, refs, content_file

register_artifact:
  artifact_type, record

append_log:
  log_type, record
```

For every operation, reject extra payload keys and call `authorize_write()` before resolving a target or calling Runtime Core. Preserve Core `ok`/`already_exists` statuses and checksums under `result`.

- [ ] **Step 4: Add observations required by Harness Plans/Receipts**

Success output must contain:

```python
{
    "status": "ok",
    "principal": {
        "id": principal.principal_id,
        "kind": principal.kind,
        "role": principal.role,
        "contract_digest": principal.contract_digest,
    },
    "authorization": {
        "operation": request.operation,
        "domain": principal.domain,
        "decision": "allowed",
        "registry_digest": registry.digest,
        "policy_digest": domain_policy_digest(domain_policies),
        "profile_digest": profile.digest,
        "mapping_digest": mapping.digest,
    },
    "result": core_result,
}
```

All digests use the literal prefix `sha256:` followed by 64 lowercase hexadecimal characters.

- [ ] **Step 5: Verify denial is pre-write and idempotency is unchanged**

Run:

```powershell
python -m pytest tests/test_principal_invocation.py tests/test_principal_invocation_end_to_end.py tests/test_write_record.py tests/test_context_pack.py tests/test_record_lookup_end_to_end.py -q
```

Expected: all pass; denied tests assert the target does not exist or retains its original checksum.

- [ ] **Step 6: Commit Task 6**

```powershell
git add llm_wiki_runtime/invocation.py tests/test_principal_invocation.py tests/test_principal_invocation_end_to_end.py
git commit -m "feat: add principal-aware write invocation"
```

---

### Task 7: Registration CLI, status vocabulary, version, and compatibility docs

**Files:**
- Modify: `llm_wiki_runtime/cli.py`
- Modify: `llm_wiki_runtime/__init__.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mapping.py`
- Modify: `tests/test_skill_package.py`
- Modify: `skills/llm-wiki-core/references/status-v0.1.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/guides/domain-skill-integration-quickstart.zh.md`

**Interfaces:**
- Produces: CLI `register-principal --manifest --registry-path [--refresh]`.
- Preserves: `scan-scp` old arguments and top-level `skills` output.
- Publishes: package version `0.3.0`.

- [ ] **Step 1: Write failing CLI registration and compatibility tests**

```python
def test_cli_register_principal_is_idempotent(tmp_path):
    manifest = write_workload_manifest(tmp_path)
    registry = tmp_path / "registry.json"
    command = [sys.executable, "-m", "llm_wiki_runtime.cli", "register-principal", "--manifest", str(manifest), "--registry-path", str(registry)]
    first = subprocess.run(command, text=True, capture_output=True, check=False)
    second = subprocess.run(command, text=True, capture_output=True, check=False)
    assert first.returncode == second.returncode == 0
    assert json.loads(second.stdout)["status"] == "already_exists"


def test_cli_scan_scp_preserves_workload_entry(tmp_path):
    manifest = write_workload_manifest(tmp_path)
    scp = write_skill_scp(tmp_path)
    registry = tmp_path / "registry.json"
    register = [
        sys.executable,
        "-m",
        "llm_wiki_runtime.cli",
        "register-principal",
        "--manifest",
        str(manifest),
        "--registry-path",
        str(registry),
    ]
    scan = [
        sys.executable,
        "-m",
        "llm_wiki_runtime.cli",
        "scan-scp",
        "--scp-path-json",
        json.dumps([str(scp)]),
        "--write",
        "--output",
        str(registry),
    ]
    assert subprocess.run(register, text=True, capture_output=True, check=False).returncode == 0
    completed = subprocess.run(scan, text=True, capture_output=True, check=False)
    payload = json.loads(completed.stdout)
    stored = json.loads(registry.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "ok"
    assert set(stored["principals"]) == {"demo-harness", "demo-skill"}
    assert set(stored["skills"]) == {"demo-skill"}
```

- [ ] **Step 2: Run tests and confirm RED**

```powershell
python -m pytest tests/test_cli.py -k "principal or scan_scp" -q
```

Expected: `register-principal` is not recognized.

- [ ] **Step 3: Implement registration CLI and preserve scan behavior**

Add:

```python
register = sub.add_parser("register-principal")
register.add_argument("--manifest", required=True)
register.add_argument("--registry-path", required=True)
register.add_argument("--refresh", action="store_true")
```

When `scan-scp --write --output PATH` targets an existing Registry, load/normalize it first and replace only SCP-origin Skill entries. Registration returns `ok`, `already_exists`, `principal_contract_stale`, or `principal_conflict` with standard response fields.

- [ ] **Step 4: Extend the stable status reference**

Append the exact new statuses without renaming existing ones:

```text
principal_not_found
principal_conflict
principal_contract_stale
principal_kind_unsupported
principal_role_unsupported
principal_domain_mismatch
capability_denied
mapping_owner_mismatch
operation_not_allowed
invalid_invocation
```

Update the exact vocabulary assertion in `tests/test_mapping.py` accordingly.

- [ ] **Step 5: Update package version and product description**

Set both version locations to `0.3.0`. Change the package description to mention Skills and governed Workloads without implying cryptographic identity:

```toml
version = "0.3.0"
description = "Deterministic local memory and knowledge runtime for AI skills and governed workloads."
```

- [ ] **Step 6: Document the two entry modes**

Update English/Chinese READMEs and the integration quickstart with:

- Skill/SCP compatibility flow;
- Workload `principal.yml` and `register-principal` flow;
- a complete `invoke` Query example;
- a complete `invoke` write example;
- the rule that `skills` is a derived Registry projection;
- no silent fallback from Workload Invocation to legacy writes;
- protocol identity versus cryptographic identity;
- Runtime 0.2 complete records remain readable, while pending old approvals stale.

- [ ] **Step 7: Run CLI, package, and Skill documentation tests**

```powershell
python -m pytest tests/test_cli.py tests/test_mapping.py tests/test_skill_package.py tests/test_packaging.py -q
```

Expected: all pass and CLI version returns `0.3.0`.

- [ ] **Step 8: Commit Task 7**

```powershell
git add llm_wiki_runtime/cli.py llm_wiki_runtime/__init__.py pyproject.toml tests/test_cli.py tests/test_mapping.py tests/test_skill_package.py skills/llm-wiki-core/references/status-v0.1.md README.md README.zh-CN.md docs/guides/domain-skill-integration-quickstart.zh.md
git commit -m "docs: publish principal runtime v0.3 contract"
```

---

### Task 8: Full Runtime verification and Observatory handoff gate

**Files:**
- Modify only files required to fix failures caused by Tasks 1–7.
- Verify: `docs/superpowers/specs/2026-08-25-principal-workload-runtime-v0-3-design.zh.md`.
- Produce no release tag or push in this task unless the user separately authorizes it.

**Interfaces:**
- Consumes: every Task 1–7 deliverable.
- Produces: a verified Runtime `0.3.0` commit suitable for the separate Observatory adoption plan.

- [ ] **Step 1: Run the complete test suite**

```powershell
python -m pytest -q
```

Expected: exit code 0, zero failed/error tests, and all Principal, legacy SCP, graph, record, context, mapping, path, and packaging tests included in collection.

- [ ] **Step 2: Run focused compatibility evidence**

```powershell
python -m pytest tests/test_scp_registry.py tests/test_mapping.py tests/test_skill_package.py tests/test_cli.py -q
```

Expected: exit code 0 and old SCP/Mapping/CLI behavior proven by unchanged compatibility tests.

- [ ] **Step 3: Run the Principal Workload end-to-end test separately**

```powershell
python -m pytest tests/test_principal_invocation_end_to_end.py -vv
```

Expected: a Workload registers, copies Evidence, writes a record, appends a log, reads it back, coexists with a Skill Principal, and rejects the Skill’s attempt to use the Workload-owned Mapping.

- [ ] **Step 4: Check repository and package integrity**

```powershell
git diff --check
python -m build
python -m pip check
git status --short
```

Expected: diff check clean; wheel/sdist build successfully; dependency check succeeds; status contains only intended implementation changes plus the pre-existing untracked MCP assessment document.

- [ ] **Step 5: Audit every design acceptance criterion**

Read Section 18 of the design and record the proving test/command for each item. Do not mark Runtime complete if any criterion relies only on intent or on the later Observatory plan. Runtime Core may be handed off when its own requirements are green; product-level `0.3.0` completion still waits for Observatory acceptance.

- [ ] **Step 6: Commit any verification-only corrections**

If verification exposes a defect, return to the task that owns the affected file, add a failing regression test, make it pass, and use that task's explicit `git add` file list. Then commit with `git commit -m "fix: close principal runtime verification gaps"`. Skip this step when verification required no corrections.

---

## Execution Boundary

After Task 8 passes, do not declare the full `0.3.0` objective complete. Execute the separate AI Research Observatory Workload adoption plan, which proves the required cross-repository acceptance without an installed Skill and verifies preservation of existing terminal complete Receipts.
