# Skill + Harness Runtime Integration Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-executable Runtime 0.3 integration guide and a self-contained AI Research Observatory Skill+Harness reference example without making `examples/**` a runtime dependency.

**Architecture:** The authoritative guide first audits a target project and selects one of three Principal topologies. A vendored Observatory example supplies immutable contract snapshots plus editable Invocation templates; a manifest pins their upstream commit and byte digests. Runtime tests validate the bundle in isolation and execute its core coexistence and authorization scenario only in temporary Workspaces.

**Tech Stack:** Markdown, YAML, JSON, Python 3.10+, pytest 9.1.1, `llm-wiki-runtime 0.3.0`.

## Global Constraints

- Runtime version remains exactly `0.3.0`; no new application dependency.
- Skill Principal ID is `ai-research-observatory`; Harness Principal ID is `ai-research-observatory-harness`.
- Both Principals use Domain and Profile `ai-research-observatory`.
- Mapping `ai-research-observatory-memory` is v0.2 and owned only by `ai-research-observatory-harness`.
- New Harness knowledge operations use `llm-wiki invoke`; no failed Invocation falls back to a legacy operation command.
- Examples are reference snapshots and templates, never runtime package data or a Runtime lookup source.
- Tests use pytest temporary directories and never access a user's real Wiki.
- Preserve `docs/superpowers/specs/2026-07-30-llm-wiki-runtime-mcp-adapter-assessment.zh.md` unchanged.
- Do not add MCP, vector search, Catalog/Shard, multi-user authorization, new Principal kinds, Scheduler behavior, or a new storage core.

---

## File Structure

### New files

- `docs/superpowers/specs/2026-08-28-skill-harness-runtime-integration-guide-design.zh.md` — approved design authority.
- `docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md` — LLM-executable evaluation and implementation manual.
- `examples/ai-research-observatory/README.zh-CN.md` — example usage, substitutions, commands, and provenance.
- `examples/ai-research-observatory/snapshot-manifest.json` — upstream commit and contract SHA-256 pins.
- `examples/ai-research-observatory/contracts/*.yml` — exact Observatory contract snapshots.
- `examples/ai-research-observatory/requests/harness/*.json` — Workload Invocation templates.
- `examples/ai-research-observatory/requests/skill/*.json` — peer Skill query and denied-write templates.
- `examples/ai-research-observatory/expected-outcomes.md` — stable expected statuses and invariants.
- `tests/test_observatory_reference_example.py` — bundle, contract, template, and temporary-Workspace acceptance.

### Modified files

- `README.md` — English guide/example entry points and topology summary.
- `README.zh-CN.md` — Chinese guide/example entry points and topology summary.
- `docs/guides/domain-skill-integration-quickstart.zh.md` — scope as Skill-only quickstart and route Harness projects to the new guide.
- `docs/guides/hr-llm-wiki-integration.zh.md` — compatibility banner.
- `docs/guides/hr-skill-llm-wiki-runtime-implementation.zh.md` — compatibility banner.
- `docs/methodology/professional-skill-dual-loop-engineering.zh.md` — decision-canvas link to the three-mode guide.

---

### Task 1: Pin the approved design and Observatory contract snapshots

**Files:**
- Create: `docs/superpowers/specs/2026-08-28-skill-harness-runtime-integration-guide-design.zh.md`
- Create: `examples/ai-research-observatory/contracts/principal.yml`
- Create: `examples/ai-research-observatory/contracts/scp.yml`
- Create: `examples/ai-research-observatory/contracts/llm-wiki-profile.yml`
- Create: `examples/ai-research-observatory/contracts/ingest-mapping.yml`
- Create: `examples/ai-research-observatory/snapshot-manifest.json`
- Create: `tests/test_observatory_reference_example.py`

**Interfaces:**
- Consumes: Observatory commit `b9c9bc6a04f5a9efeea7d7b8840bec370f61d69c` contract bytes.
- Produces: `EXAMPLE_ROOT`, four stable contract files, and a manifest that later request and E2E tests consume.

- [ ] **Step 1: Write failing snapshot and contract tests**

Create `tests/test_observatory_reference_example.py` with imports and these tests:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from llm_wiki_runtime.mapping import load_ingest_mapping
from llm_wiki_runtime.principal import load_principal_manifest
from llm_wiki_runtime.profile import load_profile
from llm_wiki_runtime.scp import load_scp


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "ai-research-observatory"
CONTRACTS = EXAMPLE_ROOT / "contracts"


def test_observatory_snapshot_manifest_matches_contract_bytes():
    manifest = json.loads((EXAMPLE_ROOT / "snapshot-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["repository"] == "https://github.com/huajiexiewenfeng/ai-research-observatory"
    assert manifest["source"]["commit"] == "b9c9bc6a04f5a9efeea7d7b8840bec370f61d69c"
    assert set(manifest["contracts"]) == {
        "principal.yml", "scp.yml", "llm-wiki-profile.yml", "ingest-mapping.yml"
    }
    for name, metadata in manifest["contracts"].items():
        content = (CONTRACTS / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == metadata["sha256"]
        assert metadata["source_path"].startswith("src/ai_observatory/memory/assets/")


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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/test_observatory_reference_example.py -q
```

Expected: FAIL because `examples/ai-research-observatory` does not exist.

- [ ] **Step 3: Copy the four source assets byte-for-byte**

Copy exactly from the pinned Observatory checkout:

```text
src/ai_observatory/memory/assets/principal.yml
src/ai_observatory/memory/assets/scp.yml
src/ai_observatory/memory/assets/llm-wiki-profile.yml
src/ai_observatory/memory/assets/ingest-mapping.yml
```

Preserve UTF-8, LF line endings, field order, and final newline. Do not add comments or replace Observatory identifiers.

- [ ] **Step 4: Add the exact snapshot manifest**

Create `snapshot-manifest.json`:

```json
{
  "schema_version": 1,
  "source": {
    "repository": "https://github.com/huajiexiewenfeng/ai-research-observatory",
    "commit": "b9c9bc6a04f5a9efeea7d7b8840bec370f61d69c"
  },
  "contracts": {
    "principal.yml": {
      "source_path": "src/ai_observatory/memory/assets/principal.yml",
      "sha256": "27642e7b95f5ab8c5f3644e35c7ae54b76912a717698c5d49daf16ef21147665"
    },
    "scp.yml": {
      "source_path": "src/ai_observatory/memory/assets/scp.yml",
      "sha256": "e0c66252fc9c97ebfae626e67a27ef56158696930abc955d83ddb0c31de1bc0a"
    },
    "llm-wiki-profile.yml": {
      "source_path": "src/ai_observatory/memory/assets/llm-wiki-profile.yml",
      "sha256": "22410bb7a678cc5ebb984ef778e8c611094d6194e74831ac33fc0789dcc2da8d"
    },
    "ingest-mapping.yml": {
      "source_path": "src/ai_observatory/memory/assets/ingest-mapping.yml",
      "sha256": "8b7e45c421fd20e796a0b84265a5d27863c5e78e0d79eccac013c8d603ac936f"
    }
  }
}
```

- [ ] **Step 5: Run snapshot tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_observatory_reference_example.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Commit the approved design and snapshot bundle**

```powershell
git add docs/superpowers/specs/2026-08-28-skill-harness-runtime-integration-guide-design.zh.md examples/ai-research-observatory/contracts examples/ai-research-observatory/snapshot-manifest.json tests/test_observatory_reference_example.py
git commit -m "docs: pin observatory runtime integration example"
```

---

### Task 2: Add complete Principal Invocation templates and stable outcomes

**Files:**
- Create: `examples/ai-research-observatory/requests/harness/*.request.json`
- Create: `examples/ai-research-observatory/requests/skill/*.request.json`
- Create: `examples/ai-research-observatory/expected-outcomes.md`
- Modify: `tests/test_observatory_reference_example.py`

**Interfaces:**
- Consumes: Runtime Invocation protocol v0.1 and the four Task 1 contracts.
- Produces: valid JSON request templates using exact operation payload keys and a stable expected-status matrix.

- [ ] **Step 1: Add failing request-template tests**

Append:

```python
def _requests() -> dict[str, dict]:
    return {
        path.relative_to(EXAMPLE_ROOT / "requests").as_posix(): json.loads(path.read_text(encoding="utf-8"))
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
            "protocol_version", "request_id", "principal_id", "operation",
            "scope_root", "mapping_id", "payload"
        }
        assert request["protocol_version"] == "v0.1"
        assert request["scope_root"] == "__ABSOLUTE_DOMAIN_WORKSPACE__"
    harness = [value for name, value in requests.items() if name.startswith("harness/")]
    assert [value["operation"] for value in harness] == [
        "resolve", "copy_source", "write_record", "append_log", "find_records", "load_context"
    ]
    assert all(value["principal_id"] == "ai-research-observatory-harness" for value in harness)
    assert requests["skill/10-find-records.request.json"]["principal_id"] == "ai-research-observatory"
    denied = requests["skill/20-write-record-denied.request.json"]
    assert denied["mapping_id"] == "ai-research-observatory-memory"
    assert denied["operation"] == "write_record"
```

- [ ] **Step 2: Run and verify RED**

Run `python -m pytest tests/test_observatory_reference_example.py -q`.

Expected: FAIL because the request directory is absent.

- [ ] **Step 3: Add the eight exact JSON templates**

Every template must use:

```json
{
  "protocol_version": "v0.1",
  "request_id": "example-unique-request-id",
  "principal_id": "ai-research-observatory-harness",
  "operation": "resolve",
  "scope_root": "__ABSOLUTE_DOMAIN_WORKSPACE__",
  "mapping_id": "ai-research-observatory-memory",
  "payload": {}
}
```

Use the Runtime's exact payload fields:

```text
copy_source: source, logical_path, source_type, metadata
write_record: record_type, variables, refs, content_file
append_log: log_type, record
find_records: record_type, lookup_value, target_domain
load_context: include, exclude, max_files, max_chars_per_file, path_filters, glob_filters, order, policy, target_domain
```

The Skill query omits `mapping_id`; the denied Skill write includes `mapping_id: ai-research-observatory-memory` to demonstrate ownership rejection.

- [ ] **Step 4: Add stable expected outcomes**

Document this matrix in `expected-outcomes.md`:

```markdown
| Request | Expected outer status | Required invariant |
| --- | --- | --- |
| Harness resolve | `ok` | Workload Principal and four authorization digests |
| Harness copy/write/log | `ok` | Mapping owner is the Harness; no legacy fallback |
| Harness find/load | `ok` | Returned content remains `data_only` |
| Skill find | `ok` | Skill can find the same accepted record using its own identity |
| Skill write with Harness Mapping | `mapping_owner_mismatch` | Target checksum remains unchanged |
```

- [ ] **Step 5: Run and verify GREEN**

Run `python -m pytest tests/test_observatory_reference_example.py -q`.

Expected: `3 passed`.

- [ ] **Step 6: Commit request templates**

```powershell
git add examples/ai-research-observatory/requests examples/ai-research-observatory/expected-outcomes.md tests/test_observatory_reference_example.py
git commit -m "docs: add principal invocation reference flow"
```

---

### Task 3: Write the authoritative LLM-executable integration manual

**Files:**
- Create: `docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md`
- Create: `examples/ai-research-observatory/README.zh-CN.md`
- Modify: `tests/test_observatory_reference_example.py`

**Interfaces:**
- Consumes: decision topology and example bundle from Tasks 1-2.
- Produces: one authoritative evaluation-to-acceptance workflow and one example-specific execution guide.

- [ ] **Step 1: Add failing documentation-contract tests**

Append:

```python
def test_authoritative_guide_routes_all_three_modes_without_blurring_legacy_harness_rules():
    guide = (ROOT / "docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md").read_text(encoding="utf-8")
    for fragment in (
        "Skill-only", "Harness-only", "Skill+Harness", "detected_mode",
        "owner_principal_id", "llm-wiki invoke", "mapping_owner_mismatch",
        "不得回退", "HR", "Runtime 0.1", "Runtime 0.3"
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
```

- [ ] **Step 2: Run and verify RED**

Run `python -m pytest tests/test_observatory_reference_example.py -q`.

Expected: FAIL because both Markdown files are absent.

- [ ] **Step 3: Write the guide with the approved twelve chapters**

Use these exact top-level headings:

```markdown
# Skill + Harness 接入 llm-wiki-runtime 0.3：LLM 评估与实施手册
## 0. LLM 执行协议
## 1. 接入前项目盘点
## 2. Skill-only、Harness-only、Skill+Harness 决策树
## 3. Domain、Principal、Interface 与 Mapping Owner
## 4. 三种模式的最小接入资产
## 5. 从领域需求推导四类契约
## 6. Runtime 0.3 Registry 与 Principal Invocation
## 7. 分模式实施顺序
## 8. 失败、恢复与升级
## 9. Observatory Skill+Harness 完整参考
## 10. HR Skill-only 兼容对照
## 11. 测试与最终验收
## 12. 非目标
```

Include the approved assessment record fields, the decision tree, distinct Principal table, effective-capability intersection, exact Workload registration and `invoke` command forms, v0.2 Mapping rule, no-fallback rule, stale Plan versus terminal Receipt distinction, and temporary-Workspace acceptance sequence.

- [ ] **Step 4: Write the example README**

The README must state:

```text
1. contracts are byte snapshots from the pinned Observatory commit;
2. examples are not package data or runtime lookup inputs;
3. replace every double-underscore placeholder before invocation;
4. register Harness independently, initialize the Profile, run Harness flow, then optionally scan SCP;
5. Harness queries may carry the Mapping to bind its digest; Skill query must use the Skill identity;
6. denied Skill write is an acceptance test and must not be retried through legacy commands;
7. generated Registry, Plan, Receipt, and Workspace outputs are intentionally absent.
```

- [ ] **Step 5: Run and verify GREEN**

Run `python -m pytest tests/test_observatory_reference_example.py -q`.

Expected: `5 passed`.

- [ ] **Step 6: Commit the guide**

```powershell
git add docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md examples/ai-research-observatory/README.zh-CN.md tests/test_observatory_reference_example.py
git commit -m "docs: add skill harness integration manual"
```

---

### Task 4: Separate the existing Skill-only quickstart from Workload guidance

**Files:**
- Modify: `docs/guides/domain-skill-integration-quickstart.zh.md`
- Modify: `docs/guides/hr-llm-wiki-integration.zh.md`
- Modify: `docs/guides/hr-skill-llm-wiki-runtime-implementation.zh.md`
- Modify: `tests/test_observatory_reference_example.py`

**Interfaces:**
- Consumes: authoritative guide path from Task 3.
- Produces: unambiguous compatibility routing for existing Skill-only readers.

- [ ] **Step 1: Add failing legacy-boundary documentation tests**

Append:

```python
def test_existing_skill_guides_declare_their_compatibility_boundary():
    quickstart = (ROOT / "docs/guides/domain-skill-integration-quickstart.zh.md").read_text(encoding="utf-8")
    hr = (ROOT / "docs/guides/hr-llm-wiki-integration.zh.md").read_text(encoding="utf-8")
    implementation = (ROOT / "docs/guides/hr-skill-llm-wiki-runtime-implementation.zh.md").read_text(encoding="utf-8")
    assert "Skill-only 快速入口" in quickstart
    assert "skill-harness-llm-wiki-runtime-integration.zh.md" in quickstart
    for text in (hr, implementation):
        assert "Runtime 0.1" in text
        assert "Runtime 0.3" in text
        assert "Skill-only" in text
        assert "新 Harness" in text
        assert "llm-wiki invoke" in text
```

- [ ] **Step 2: Run and verify RED**

Run the focused test file; expect failure on the missing boundary banners.

- [ ] **Step 3: Add the quickstart route banner and remove the embedded Workload tutorial**

Immediately after the title add:

```markdown
> 本文是既有 Domain Skill 的 **Skill-only 快速入口**。如果项目包含独立 CLI、Scheduler、Service 或受治理 Harness，先阅读[Skill + Harness Runtime 0.3 评估与实施手册](skill-harness-llm-wiki-runtime-integration.zh.md)，完成模式判定后再实施。
```

Replace the current `### 0.3：选择 Skill/SCP 兼容入口或 Workload 入口` body with a concise route note. Keep the detailed Skill/SCP/Profile/legacy workflow unchanged. Do not leave a second Workload `principal.yml` or `invoke` tutorial in this file.

- [ ] **Step 4: Add the HR compatibility banner to both HR guides**

After each title add:

```markdown
> 版本边界：本文记录的是源自 Runtime 0.1、由 Runtime 0.3 compatibility adapter 继续支持的 **Skill-only** 接入。它不包含 Workload Principal，也不是新 Harness 的实现模板。新 Harness 必须使用 `principal.yml`、v0.2 Mapping 和 `llm-wiki invoke`，Invocation 失败不得回退到本文中的 legacy 写命令。
```

- [ ] **Step 5: Run and verify GREEN**

Run `python -m pytest tests/test_observatory_reference_example.py -q`.

Expected: all tests pass.

- [ ] **Step 6: Commit compatibility routing**

```powershell
git add docs/guides/domain-skill-integration-quickstart.zh.md docs/guides/hr-llm-wiki-integration.zh.md docs/guides/hr-skill-llm-wiki-runtime-implementation.zh.md tests/test_observatory_reference_example.py
git commit -m "docs: separate skill compatibility from workload guidance"
```

---

### Task 5: Publish documentation entry points

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/methodology/professional-skill-dual-loop-engineering.zh.md`
- Modify: `tests/test_observatory_reference_example.py`

**Interfaces:**
- Consumes: final guide and example paths.
- Produces: discoverable English/Chinese repository entry points without duplicating the full guide.

- [ ] **Step 1: Add failing entry-point tests**

Append:

```python
def test_repository_entry_points_link_the_authoritative_guide_and_example():
    for name in ("README.md", "README.zh-CN.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md" in text
        assert "examples/ai-research-observatory/README.zh-CN.md" in text
    methodology = (ROOT / "docs/methodology/professional-skill-dual-loop-engineering.zh.md").read_text(encoding="utf-8")
    assert "Skill-only" in methodology
    assert "Harness-only" in methodology
    assert "Skill+Harness" in methodology
    assert "../guides/skill-harness-llm-wiki-runtime-integration.zh.md" in methodology
```

- [ ] **Step 2: Run and verify RED**

Run the focused test file; expect missing-link assertions.

- [ ] **Step 3: Add concise README entries**

In both README guide lists add links to the authoritative guide and Observatory example. Near the existing 0.3 entry-mode section add a three-row table for Skill-only, Harness-only, and Skill+Harness, with HR and Observatory as the respective references.

- [ ] **Step 4: Update the methodology decision canvas**

Add a route paragraph that says the canvas determines not only whether to adopt Runtime but also which of the three Principal topologies applies, then link to the new guide. Do not copy the full decision tree into the methodology document.

- [ ] **Step 5: Run and verify GREEN**

Run `python -m pytest tests/test_observatory_reference_example.py -q`.

Expected: all tests pass.

- [ ] **Step 6: Commit entry points**

```powershell
git add README.md README.zh-CN.md docs/methodology/professional-skill-dual-loop-engineering.zh.md tests/test_observatory_reference_example.py
git commit -m "docs: publish runtime integration entry points"
```

---

### Task 6: Prove the reference bundle against Runtime 0.3 and run regressions

**Files:**
- Modify: `tests/test_observatory_reference_example.py`
- Test: `tests/test_principal_contract.py`
- Test: `tests/test_principal_registry.py`
- Test: `tests/test_mapping.py`
- Test: `tests/test_principal_authorization.py`
- Test: `tests/test_principal_invocation.py`
- Test: `tests/test_principal_invocation_end_to_end.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_skill_package.py`

**Interfaces:**
- Consumes: the final example bundle and Runtime public CLI/application boundary.
- Produces: fresh evidence that the example remains executable and does not weaken existing compatibility.

- [ ] **Step 1: Add a temporary-Workspace example E2E**

Use the existing `register_principal`, `scan_scp_paths`, `init_profile`, and `execute_invocation` public Python functions in a pytest `tmp_path`. The scenario must:

```text
register only ai-research-observatory-harness
initialize the example Profile
invoke resolve
copy a prepared Evidence file
write one research_direction_revision
append one observatory_memory_event
find and load that record as the Harness
scan the example SCP into the same Registry
find the same record as ai-research-observatory
attempt Skill write with ai-research-observatory-memory
assert mapping_owner_mismatch and unchanged checksum
```

Use fixed safe IDs `example-direction`, `r1`, `example-record-001`, and `example-source-001`. All files must live below `tmp_path`.

- [ ] **Step 2: Run the focused E2E and verify GREEN**

Run:

```powershell
python -m pytest tests/test_observatory_reference_example.py -q
```

Expected: all reference-example tests pass without skips.

- [ ] **Step 3: Run Principal and compatibility regressions**

Run:

```powershell
python -m pytest tests/test_principal_contract.py tests/test_principal_registry.py tests/test_mapping.py tests/test_principal_authorization.py tests/test_principal_invocation.py tests/test_principal_invocation_end_to_end.py tests/test_cli.py tests/test_skill_package.py -q
```

Expected: zero failures and zero errors.

- [ ] **Step 4: Run the full Runtime suite**

Run:

```powershell
python -m pytest -q
```

Expected: zero failures and zero errors.

- [ ] **Step 5: Run repository hygiene checks**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; status lists only the planned guide/example/test changes plus the pre-existing untracked `docs/superpowers/specs/2026-07-30-llm-wiki-runtime-mcp-adapter-assessment.zh.md`.

- [ ] **Step 6: Commit final acceptance coverage**

```powershell
git add tests/test_observatory_reference_example.py
git commit -m "test: verify observatory reference integration"
```

---

## Final Self-Review

- [ ] Confirm the plan and produced documentation contain no unfinished markers or deferred requirements.
- [ ] Confirm every Workload write example uses `invoke`, v0.2 Mapping, and the Harness Principal.
- [ ] Confirm no text tells Skill and Harness to share a Principal ID or Mapping ownership.
- [ ] Confirm HR is labeled compatibility reference rather than Runtime 0.3 Harness guidance.
- [ ] Confirm examples are absent from `tool.setuptools.package-data` and application imports.
- [ ] Confirm the pre-existing MCP assessment file is byte-for-byte untouched.
