# LLM Wiki 通用 Skills 与 HR 历史 JD 入库 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 发布并安装 `llm-wiki-core` 的 init/ingest/query/maintain 四个通用子 Skill，并通过一个旧 Codex 招聘任务完成 HR Wiki 初始化、JD-only 历史导入和查询闭环。

**Architecture:** `llm-wiki-runtime` 提供确定性 source、record、log、mapping 校验和 CLI；`llm-wiki-core` 负责宿主编排；`role-copilot-skills/hr-agent-copilot` 提供 HR profile、JD ingest mapping 和 owner SCP。Phase 1 只处理 JD，不实现人物索引、person resolution 或 context views。

**Tech Stack:** Python 3.10+、标准库、pytest、YAML 子集解析器、Markdown Skills、PowerShell 5.1、Codex `list_threads`/`read_thread` 宿主工具。

## Global Constraints

- Runtime 仓库：`D:\tmp\github\llm-wiki-runtime`。
- HR 开发 worktree：`C:\tmp\role-copilot-skills-llm-wiki-scp`。
- 当前 Codex Skill root：`C:\Users\admin\.codex-clean-20260710\skills`。
- 不创建 commit、不 push；每个任务完成后只执行精确的 `git add`。
- 不清理或回退两个仓库中已有的 staged/unstaged 修改。
- 手工编辑使用 `apply_patch`；文本使用 UTF-8 无 BOM。
- 不增加第三方 Python 依赖，保持 `dependencies = []`。
- Skills 不得绕过 runtime CLI 直接写 `.llm-wiki`。
- JD 写入前必须经过用户预览确认；混合候选人信息的消息默认不写。
- `jd_version_id` 只基于确认后的原文：Unicode NFC、LF 换行、全文首尾 trim，其余字符不变。
- Phase 1 不增加 person-query/context-view SCP 字段，不修改人物数据。

---

### Task 1: Profile 日志合同与受控 append-log

**Files:**
- Modify: `llm_wiki_runtime/models.py`
- Modify: `llm_wiki_runtime/profile.py`
- Modify: `llm_wiki_runtime/runtime.py`
- Modify: `llm_wiki_runtime/cli.py`
- Modify: `tests/test_profile.py`
- Modify: `tests/test_registries.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `LogRule(log_type: str, path: str, mode: str)`。
- Produces: `Profile.log_rules: dict[str, LogRule]`。
- Produces: `append_profile_log(scope_root, profile_path, log_type, record) -> dict`。
- CLI: `append-log --scope-root $SCOPE_ROOT --log-type $LOG_TYPE --record-json $RECORD_JSON [--profile-path $PROFILE_PATH]`。
- Preserves: existing low-level `append_log(wiki_root, logical_log_path, record)` for compatibility only.
- Returns: `status=already_exists` without a second line when a profile-aware record repeats a non-empty `event_id`.

- [ ] **Step 1: Write failing profile and runtime tests**

Add to `tests/test_profile.py`:

```python
def test_load_profile_parses_append_only_log_contract(tmp_path):
    profile_path = tmp_path / "llm-wiki-profile.yml"
    profile_path.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "logs:",
                "  types:",
                "    hr_jd_import:",
                "      path: logs/hr-jd-import.jsonl",
                "      mode: append_only",
            ]
        ),
        encoding="utf-8",
    )

    profile = load_profile(profile_path)

    assert profile.log_rules["hr_jd_import"].path == "logs/hr-jd-import.jsonl"
    assert profile.log_rules["hr_jd_import"].mode == "append_only"
```

Add to `tests/test_registries.py`:

```python
import pytest

from llm_wiki_runtime.runtime import append_profile_log, init_profile


def test_append_profile_log_uses_active_profile_contract(tmp_path):
    profile = tmp_path / "hr-profile.yml"
    profile.write_text(
        "\n".join(
            [
                "profile:",
                "  id: hr",
                "  version: v0.1",
                "layout:",
                "  directories:",
                "    - logs",
                "logs:",
                "  types:",
                "    hr_jd_import:",
                "      path: logs/hr-jd-import.jsonl",
                "      mode: append_only",
            ]
        ),
        encoding="utf-8",
    )
    init_profile(tmp_path, profile, "local", "hr-test")

    record = {
        "event": "jd_imported",
        "event_id": "hr-jd-import:src-1:job-1:jd-1",
    }
    payload = append_profile_log(tmp_path, None, "hr_jd_import", record)
    duplicate = append_profile_log(tmp_path, None, "hr_jd_import", record)

    assert payload["status"] == "ok"
    assert payload["log_type"] == "hr_jd_import"
    assert duplicate["status"] == "already_exists"
    lines = (tmp_path / ".llm-wiki/logs/hr-jd-import.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "jd_imported" in lines[0]


def test_append_profile_log_rejects_undeclared_type(tmp_path):
    profile = tmp_path / "hr-profile.yml"
    profile.write_text("profile:\n  id: hr\n  version: v0.1\n", encoding="utf-8")
    init_profile(tmp_path, profile, "local", "hr-test")

    with pytest.raises(ValueError, match="undeclared log type"):
        append_profile_log(tmp_path, None, "hr_jd_import", {"event": "jd_imported"})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
$PY = 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $PY -m pytest tests/test_profile.py tests/test_registries.py -q
```

Expected: FAIL because `Profile.log_rules`, `LogRule`, and `append_profile_log` do not exist.

- [ ] **Step 3: Implement log contract parsing**

Add to `llm_wiki_runtime/models.py`:

```python
@dataclass(frozen=True)
class LogRule:
    log_type: str
    path: str
    mode: str = "append_only"
```

Add this field after `artifact_types` in the existing `Profile` dataclass:

```python
    log_rules: dict[str, LogRule] = field(default_factory=dict)
```

Extend `load_profile()` so the YAML subset accepts:

```yaml
logs:
  types:
    hr_jd_import:
      path: logs/hr-jd-import.jsonl
      mode: append_only
```

Construct `LogRule` objects and pass `log_rules=log_rules` as a keyword to the existing `Profile` constructor. Reject an empty path and any mode other than `append_only` with `ValueError`.

- [ ] **Step 4: Implement the profile-aware append function and CLI**

Add to `llm_wiki_runtime/runtime.py`:

```python
def append_profile_log(
    scope_root: Path,
    profile_path: Path | None,
    log_type: str,
    record: dict,
) -> dict:
    profile = load_active_profile(scope_root, profile_path)
    rule = profile.log_rules.get(log_type)
    if rule is None:
        raise ValueError(f"undeclared log type: {log_type}")
    if rule.mode != "append_only":
        raise ValueError(f"log type is not append_only: {log_type}")
    event_id = record.get("event_id")
    if event_id is not None and (not isinstance(event_id, str) or not event_id):
        raise ValueError("event_id must be a non-empty string")
    wiki_root = scope_root / ".llm-wiki"
    target = ensure_under_root(wiki_root, Path(rule.path))
    with ScopeLock(wiki_root, command="append-log"):
        if event_id and target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                if json.loads(line).get("event_id") == event_id:
                    return {
                        "status": "already_exists",
                        "path": rule.path,
                        "log_type": log_type,
                        "event_id": event_id,
                    }
        payload = append_log_unlocked(wiki_root, rule.path, record)
        return {**payload, "log_type": log_type}
```

Refactor the existing append body into `append_log_unlocked`; keep `append_log` as the compatibility wrapper that acquires `ScopeLock` and calls it. In `llm_wiki_runtime/cli.py`, make the existing `--wiki-root` and `--log` arguments optional, then add `--scope-root`, `--profile-path`, and `--log-type`. Dispatch rules are exact: profile mode requires both `--scope-root` and `--log-type` and calls `append_profile_log`; compatibility mode requires both `--wiki-root` and `--log` and calls `append_log`; mixed or incomplete modes return `validation_error` with exit code 2.

- [ ] **Step 5: Add and run CLI coverage**

Add a subprocess test to `tests/test_cli.py` that initializes a temporary HR profile, invokes `append-log --scope-root $SCOPE_ROOT --log-type hr_jd_import --record-json $RECORD_JSON`, and asserts JSON `status=ok` plus `log_type=hr_jd_import`. Invoke it a second time with the same `event_id` and assert `status=already_exists` with exit code 0.

Run:

```powershell
& $PY -m pytest tests/test_profile.py tests/test_registries.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Stage Task 1 only**

```powershell
git add llm_wiki_runtime/models.py llm_wiki_runtime/profile.py llm_wiki_runtime/runtime.py llm_wiki_runtime/cli.py tests/test_profile.py tests/test_registries.py tests/test_cli.py
git diff --cached --check
```

Expected: no whitespace errors; do not commit.

---

### Task 2: Source provenance metadata and idempotent copy-source

**Files:**
- Modify: `llm_wiki_runtime/runtime.py`
- Modify: `llm_wiki_runtime/cli.py`
- Modify: `tests/test_registries.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_write_record.py`

**Interfaces:**
- Changes: `copy_source(wiki_root: Path, source: Path, logical_path: str, source_type: str, metadata: dict | None = None) -> dict`。
- CLI: `copy-source --metadata-json $METADATA_JSON`。
- Returns: `status=already_exists` when the checksum and logical path are already registered; registry remains unchanged.
- Changes: an existing `create_only` record returns `already_exists` with its current checksum and is never overwritten.

- [ ] **Step 1: Write failing source-registry tests**

Add to `tests/test_registries.py`:

```python
def test_copy_source_registers_controlled_provenance_metadata(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")
    metadata = {
        "excerpted": True,
        "thread_id": "thread-1",
        "selections": [
            {
                "turn_id": "turn-1",
                "item_id": "item-1",
                "start": 0,
                "end": 21,
                "original_message_checksum": "abc123",
            }
        ],
        "confirmed_at": "2026-07-18T10:00:00+08:00",
    }

    payload = copy_source(
        wiki_root,
        source,
        "sources/originals/hr/jobs/job-1/jd-1.md",
        "codex_thread_jd_excerpt",
        metadata,
    )

    registry = json.loads((wiki_root / "sources/registry.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert registry["sources"][0]["metadata"] == metadata


def test_copy_source_is_idempotent_by_checksum(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")

    first = copy_source(wiki_root, source, "sources/originals/hr/jobs/jd.md", "jd")
    second = copy_source(wiki_root, source, "sources/originals/hr/jobs/jd.md", "jd")

    registry = json.loads((wiki_root / "sources/registry.json").read_text(encoding="utf-8"))
    assert first["source_id"] == second["source_id"]
    assert second["status"] == "already_exists"
    assert len(registry["sources"]) == 1


def test_copy_source_refuses_different_content_at_existing_logical_path(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("JD version one", encoding="utf-8")
    logical_path = "sources/originals/hr/jobs/jd.md"
    copy_source(wiki_root, source, logical_path, "jd")

    source.write_text("JD version two", encoding="utf-8")
    with pytest.raises(FileExistsError, match="source target already exists"):
        copy_source(wiki_root, source, logical_path, "jd")

    target = wiki_root / logical_path
    assert target.read_text(encoding="utf-8") == "JD version one"


def test_copy_source_rejects_incomplete_excerpt_metadata(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    source = tmp_path / "jd.md"
    source.write_text("Senior Java Developer", encoding="utf-8")

    with pytest.raises(ValueError, match="excerpt metadata requires thread_id and selections"):
        copy_source(
            wiki_root,
            source,
            "sources/originals/hr/jobs/jd.md",
            "codex_thread_jd_excerpt",
            {"excerpted": True},
        )
```

Replace `test_write_record_create_only_refuses_overwrite` in `tests/test_write_record.py` with:

```python
def test_write_record_create_only_refuses_overwrite_and_returns_existing(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "llm-wiki-profile.yml"
    write_profile(profile)
    content = tmp_path / "content.md"
    content.write_text("first", encoding="utf-8")
    first = write_record(tmp_path, profile, "screening_report", {"run_id": "run-001"}, {}, content)

    content.write_text("second", encoding="utf-8")
    duplicate = write_record(tmp_path, profile, "screening_report", {"run_id": "run-001"}, {}, content)

    assert first["status"] == "ok"
    assert duplicate["status"] == "already_exists"
    assert duplicate["checksum"] == first["checksum"]
    target = wiki_root / "domains/hr/screenings/run-001/report.md"
    assert target.read_text(encoding="utf-8") == "first"
```

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
& $PY -m pytest tests/test_registries.py tests/test_write_record.py -q
```

Expected: FAIL because `copy_source` does not accept metadata, duplicate registry entries are appended, and `create_only` still raises `FileExistsError` on an idempotent retry.

- [ ] **Step 3: Implement controlled metadata and idempotency**

In `llm_wiki_runtime/runtime.py`, define:

```python
SOURCE_METADATA_KEYS = {
    "excerpted",
    "thread_id",
    "selections",
    "confirmed_at",
}
SOURCE_SELECTION_KEYS = {
    "turn_id",
    "item_id",
    "start",
    "end",
    "original_message_checksum",
}


def validate_source_metadata(metadata: dict | None) -> dict:
    result = dict(metadata or {})
    unexpected = sorted(set(result) - SOURCE_METADATA_KEYS)
    if unexpected:
        raise ValueError(f"unsupported source metadata fields: {unexpected}")
    selections = result.get("selections", [])
    if not isinstance(selections, list):
        raise ValueError("source metadata selections must be a list")
    if result.get("excerpted") is not None and not isinstance(result["excerpted"], bool):
        raise ValueError("source metadata excerpted must be boolean")
    if result.get("excerpted") and (
        not isinstance(result.get("thread_id"), str)
        or not result["thread_id"]
        or not selections
    ):
        raise ValueError("excerpt metadata requires thread_id and selections")
    confirmed_at = result.get("confirmed_at")
    if confirmed_at is not None and (not isinstance(confirmed_at, str) or not confirmed_at):
        raise ValueError("source metadata confirmed_at must be a non-empty string")
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError("source metadata selection must be an object")
        unexpected_selection = sorted(set(selection) - SOURCE_SELECTION_KEYS)
        if unexpected_selection:
            raise ValueError(f"unsupported source selection fields: {unexpected_selection}")
        missing = sorted(SOURCE_SELECTION_KEYS - set(selection))
        if missing:
            raise ValueError(f"missing source selection fields: {missing}")
        if not isinstance(selection["start"], int) or not isinstance(selection["end"], int):
            raise ValueError("source selection start/end must be integers")
        if selection["start"] < 0 or selection["end"] <= selection["start"]:
            raise ValueError("source selection range is invalid")
        for key in ("turn_id", "item_id", "original_message_checksum"):
            if not isinstance(selection[key], str) or not selection[key]:
                raise ValueError(f"source selection {key} must be a non-empty string")
    return result
```

Update `copy_source` to validate metadata and calculate the input file checksum before copying. Under `ScopeLock`, return the existing record when both checksum and logical path match. If the target logical path exists with a different checksum, raise `FileExistsError(f"source target already exists with different content: {logical_path}")` before copying. If the target has the same checksum but its registry entry is missing, register it once as crash recovery. Store controlled metadata only after validation and never duplicate a source registry entry for the idempotency key.

In `write_record`, keep required-ref validation inside the lock and return the existing immutable record before any write:

```python
if rule.mode == "create_only" and target.exists():
    return {
        "status": "already_exists",
        "record_type": record_type,
        "path": str(logical_path).replace("\\", "/"),
        "checksum": sha256_file(target),
    }
```

- [ ] **Step 4: Wire `--metadata-json` and verify CLI behavior**

Add `copy.add_argument("--metadata-json", default="{}")` and pass `json.loads(args.metadata_json)` to `copy_source`.

Add a subprocess test asserting the metadata appears in `sources/registry.json` and a second invocation returns `already_exists` with exit code 0.

Run:

```powershell
& $PY -m pytest tests/test_registries.py tests/test_write_record.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Stage Task 2 only**

```powershell
git add llm_wiki_runtime/runtime.py llm_wiki_runtime/cli.py tests/test_registries.py tests/test_write_record.py tests/test_cli.py
git diff --cached --check
```

Expected: no whitespace errors; do not commit.

---

### Task 3: Deterministic Codex-thread JD excerpt preparation

**Files:**
- Create: `llm_wiki_runtime/ingest.py`
- Create: `tests/test_ingest.py`
- Modify: `llm_wiki_runtime/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `normalize_evidence_text(text: str) -> str`。
- Produces: `prepare_excerpt(items: list[dict], selections: list[dict], id_prefix: str, confirmed_at: str) -> dict`。
- CLI: `prepare-excerpt --items-file $ITEMS_JSON --selections-file $SELECTIONS_JSON --output $SNAPSHOT_MD --id-prefix jd --confirmed-at $CONFIRMED_AT`。
- Result includes: `version_id`, `body_checksum`, `metadata`, `risk_flags`, and `snapshot_path`.

- [ ] **Step 1: Write failing normalization, range, and risk tests**

Create `tests/test_ingest.py`:

```python
import unicodedata

import pytest

from llm_wiki_runtime.ingest import normalize_evidence_text, prepare_excerpt


CONFIRMED_AT = "2026-07-18T10:00:00+08:00"


def test_normalize_evidence_text_is_deterministic():
    decomposed = "  Cafe\u0301\r\nSenior Java\r  "
    assert normalize_evidence_text(decomposed) == unicodedata.normalize("NFC", "Café\nSenior Java")


def test_prepare_excerpt_hashes_confirmed_verbatim_ranges_only():
    items = [
        {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "turn_order": 1,
            "item_order": 1,
            "text": "Candidate discussion. JD: Senior Java Developer",
        }
    ]
    text = items[0]["text"]
    selections = [
        {
            "turn_id": "turn-1",
            "item_id": "item-1",
            "start": text.index("JD:"),
            "end": len(text),
        }
    ]

    first = prepare_excerpt(items, selections, "jd", CONFIRMED_AT)
    second = prepare_excerpt(items, selections, "jd", CONFIRMED_AT)

    assert first["body"] == "JD: Senior Java Developer"
    assert first["version_id"] == second["version_id"]
    assert first["metadata"]["excerpted"] is True
    assert first["metadata"]["confirmed_at"] == CONFIRMED_AT
    assert first["metadata"]["selections"][0]["item_id"] == "item-1"


def test_prepare_excerpt_rejects_invalid_character_range():
    items = [{"thread_id": "t", "turn_id": "r", "item_id": "i", "turn_order": 1, "item_order": 1, "text": "JD"}]
    with pytest.raises(ValueError, match="invalid excerpt range"):
        prepare_excerpt(
            items,
            [{"turn_id": "r", "item_id": "i", "start": 0, "end": 99}],
            "jd",
            CONFIRMED_AT,
        )


def test_prepare_excerpt_flags_obvious_contact_data_without_claiming_full_privacy():
    items = [{"thread_id": "t", "turn_id": "r", "item_id": "i", "turn_order": 1, "item_order": 1, "text": "JD owner test@example.com"}]
    payload = prepare_excerpt(
        items,
        [{"turn_id": "r", "item_id": "i", "start": 0, "end": len(items[0]["text"])}],
        "jd",
        CONFIRMED_AT,
    )
    assert "email" in payload["risk_flags"]
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
& $PY -m pytest tests/test_ingest.py -q
```

Expected: ERROR because `llm_wiki_runtime.ingest` does not exist.

- [ ] **Step 3: Implement deterministic preparation**

Create `llm_wiki_runtime/ingest.py` with:

```python
from __future__ import annotations

import hashlib
import re
import unicodedata


EXCERPT_SEPARATOR = "\n\n---\n\n"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CN_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def normalize_evidence_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalized).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scan_sensitive_patterns(text: str) -> list[str]:
    flags = []
    if EMAIL_RE.search(text):
        flags.append("email")
    if CN_MOBILE_RE.search(text):
        flags.append("phone")
    return flags
```

Implement `prepare_excerpt` by indexing items on `(turn_id, item_id)`, validating a non-empty ISO-8601 `confirmed_at`, thread consistency, and ranges, sorting by `(turn_order, item_order, start)`, slicing exact source text, normalizing each slice, joining with `EXCERPT_SEPARATOR`, and returning `version_id=f"{id_prefix}-{sha256_text(body)[:12]}"`. Metadata must contain `thread_id`, the supplied `confirmed_at`, and a `selections` list whose entries contain `turn_id`, `item_id`, `start`, `end`, and `original_message_checksum`; it must not include LLM structured fields.

- [ ] **Step 4: Add snapshot output and CLI**

Add `write_excerpt_snapshot(payload: dict, output: Path) -> Path` that writes deterministic UTF-8 Markdown frontmatter followed by the confirmed body. The `version_id` hash must be calculated before frontmatter is added.

Add CLI arguments:

```text
prepare-excerpt
  --items-file $ITEMS_JSON
  --selections-file $SELECTIONS_JSON
  --output $SNAPSHOT_MD
  --id-prefix jd
  --confirmed-at $CONFIRMED_AT
```

Return JSON with `status=ok`, `version_id`, `body_checksum`, `metadata`, `risk_flags`, and `snapshot_path`.

- [ ] **Step 5: Run unit and CLI tests**

```powershell
& $PY -m pytest tests/test_ingest.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Stage Task 3 only**

```powershell
git add llm_wiki_runtime/ingest.py llm_wiki_runtime/cli.py tests/test_ingest.py tests/test_cli.py
git diff --cached --check
```

Expected: no whitespace errors; do not commit.

---

### Task 4: Ingest mapping contract and SCP/profile validation

**Files:**
- Create: `llm_wiki_runtime/mapping.py`
- Create: `tests/test_mapping.py`
- Modify: `llm_wiki_runtime/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `skills/llm-wiki-core/references/scp-v0.1.md`
- Create: `skills/llm-wiki-core/references/status-v0.1.md`

**Interfaces:**
- Produces: `load_ingest_mapping(path: Path) -> dict`。
- Produces: `validate_ingest_mapping(mapping, registry, profile) -> dict`。
- CLI: `validate-mapping --mapping-path $MAPPING_PATH --registry-path $REGISTRY_PATH --profile-path $PROFILE_PATH`。
- Status vocabulary includes `domain_mapping_required` and `already_exists`.

- [ ] **Step 1: Write failing mapping tests**

Create `tests/test_mapping.py` with fixture files for this contract:

```yaml
mapping:
  id: hr-jd-codex-thread
  version: v0.1
  domain: hr
  owner_skill_id: hr-resume-screening-copilot
  source_types: [codex_thread_jd_excerpt]
  instruction_ref: references/llm-wiki-ingest.md
produces:
  - record_type: job_profile
  - record_type: jd_version
  - log_type: hr_jd_import
```

Add this fixture helper and the three tests below the mapping text:

```python
from pathlib import Path

import pytest

from llm_wiki_runtime.mapping import load_ingest_mapping, validate_ingest_mapping
from llm_wiki_runtime.profile import load_profile


MAPPING_TEXT = """mapping:
  id: hr-jd-codex-thread
  version: v0.1
  domain: hr
  owner_skill_id: hr-resume-screening-copilot
  source_types: [codex_thread_jd_excerpt]
  instruction_ref: references/llm-wiki-ingest.md
produces:
  - record_type: job_profile
  - record_type: jd_version
  - log_type: hr_jd_import
"""


def load_contract(tmp_path: Path, *, owner_has_jd: bool = True, profile_has_log: bool = True):
    mapping_path = tmp_path / "ingest-mapping.yml"
    mapping_path.write_text(MAPPING_TEXT, encoding="utf-8")

    owner_products = [
        "    - domain: hr",
        "      record_type: job_profile",
    ]
    if owner_has_jd:
        owner_products.extend(["    - domain: hr", "      record_type: jd_version"])
    owner_products.extend(["    - domain: hr", "      log_type: hr_jd_import"])
    scp_path = tmp_path / "scp.yml"
    scp_path.write_text(
        "\n".join(
            [
                "scp_version: v0.1",
                "skill:",
                "  id: hr-resume-screening-copilot",
                "  domain: hr",
                "ingest:",
                "  produces:",
                *owner_products,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile_lines = [
        "profile:",
        "  id: hr",
        "  version: v0.1",
        "write_rules:",
        "  records:",
        "    job_profile:",
        "      path: domains/hr/jobs/{job_id}/profile.md",
        "      mode: update_allowed",
        "    jd_version:",
        "      path: domains/hr/jobs/{job_id}/versions/{jd_version_id}.md",
        "      mode: create_only",
    ]
    if profile_has_log:
        profile_lines.extend(
            [
                "logs:",
                "  types:",
                "    hr_jd_import:",
                "      path: logs/hr-jd-import.jsonl",
                "      mode: append_only",
            ]
        )
    profile_path = tmp_path / "profile.yml"
    profile_path.write_text("\n".join(profile_lines) + "\n", encoding="utf-8")
    registry = {
        "skills": {
            "hr-resume-screening-copilot": {
                "domain": "hr",
                "scp_path": str(scp_path),
            }
        }
    }
    return load_ingest_mapping(mapping_path), registry, load_profile(profile_path)


def test_mapping_products_must_be_declared_by_owner_scp_and_profile(tmp_path):
    mapping, registry, profile = load_contract(tmp_path)
    payload = validate_ingest_mapping(mapping, registry, profile)
    assert payload["status"] == "ok"


def test_mapping_rejects_product_missing_from_owner_scp(tmp_path):
    mapping, registry, profile = load_contract(tmp_path, owner_has_jd=False)
    with pytest.raises(ValueError, match="owner SCP does not produce"):
        validate_ingest_mapping(mapping, registry, profile)


def test_mapping_rejects_log_missing_from_profile(tmp_path):
    mapping, registry, profile = load_contract(tmp_path, profile_has_log=False)
    with pytest.raises(ValueError, match="profile does not declare log"):
        validate_ingest_mapping(mapping, registry, profile)
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
& $PY -m pytest tests/test_mapping.py -q
```

Expected: ERROR because `llm_wiki_runtime.mapping` does not exist.

- [ ] **Step 3: Implement mapping parser and validator**

Implement the repository's existing YAML-subset style; do not add PyYAML. Parse `mapping` scalar fields and `produces` list items. Validation must:

```python
mapping_contracts = {("record_type", "job_profile"), ("record_type", "jd_version"), ("log_type", "hr_jd_import")}
owner_contracts = contracts_from_scp(load_scp(Path(owner_registry_entry["scp_path"])))

assert mapping["domain"] == owner_registry_entry["domain"]
assert mapping_contracts <= owner_contracts
assert record types exist in profile.write_rules
assert log types exist in profile.log_rules
assert artifact types exist in profile.artifact_types
```

Return `{"status": "ok", "mapping_id": mapping["id"], "owner_skill_id": mapping["owner_skill_id"], "produces": mapping["produces"]}`. Missing mapping files return `domain_mapping_required` from the CLI with exit code 1; malformed or inconsistent mappings return `validation_error` with exit code 2.

- [ ] **Step 4: Add CLI and status reference tests**

Add `validate-mapping` parser/dispatch to `cli.py`. Add subprocess tests for `ok`, `domain_mapping_required`, and `validation_error`.

Create `skills/llm-wiki-core/references/status-v0.1.md` listing exactly:

```text
ok
enabled
missing_config
disabled
profile_mismatch
domain_mapping_required
already_exists
validation_error
read_denied
runtime_unavailable
io_error
unexpected_error
```

- [ ] **Step 5: Run focused and existing SCP tests**

```powershell
& $PY -m pytest tests/test_mapping.py tests/test_scp_registry.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Stage Task 4 only**

```powershell
git add llm_wiki_runtime/mapping.py llm_wiki_runtime/cli.py tests/test_mapping.py tests/test_cli.py skills/llm-wiki-core/references/scp-v0.1.md skills/llm-wiki-core/references/status-v0.1.md
git diff --cached --check
```

Expected: no whitespace errors; do not commit.

---

### Task 5: Split llm-wiki-core into four discoverable generic Skills

**Files:**
- Modify: `skills/llm-wiki-core/SKILL.md`
- Create: `skills/llm-wiki-core/llm-wiki-init/SKILL.md`
- Create: `skills/llm-wiki-core/llm-wiki-ingest/SKILL.md`
- Create: `skills/llm-wiki-core/llm-wiki-ingest/references/codex-thread-source.md`
- Create: `skills/llm-wiki-core/llm-wiki-query/SKILL.md`
- Create: `skills/llm-wiki-core/llm-wiki-maintain/SKILL.md`
- Create: `tests/test_skill_package.py`

**Interfaces:**
- Parent routes exactly one child and performs no runtime command itself.
- `llm-wiki-init` consumes domain/profile and emits dynamic binding state.
- `llm-wiki-ingest` consumes source adapter + mapping and enforces preview Gate.
- `llm-wiki-query` resolves domain and loads context.
- `llm-wiki-maintain` scans SCP/mapping/profile consistency.

- [ ] **Step 1: Write failing package contract tests**

Create `tests/test_skill_package.py`:

```python
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1] / "skills" / "llm-wiki-core"
CHILDREN = {
    "llm-wiki-init": "llm-wiki-init/SKILL.md",
    "llm-wiki-ingest": "llm-wiki-ingest/SKILL.md",
    "llm-wiki-query": "llm-wiki-query/SKILL.md",
    "llm-wiki-maintain": "llm-wiki-maintain/SKILL.md",
}


def test_parent_routes_exactly_one_generic_child():
    text = (PACKAGE / "SKILL.md").read_text(encoding="utf-8")
    assert "exactly one child skill" in text.lower()
    for relative in CHILDREN.values():
        assert relative in text


def test_each_child_has_discoverable_frontmatter():
    for skill_id, relative in CHILDREN.items():
        text = (PACKAGE / relative).read_text(encoding="utf-8")
        assert f"name: {skill_id}" in text
        assert "description: Use when" in text


def test_ingest_requires_preview_before_any_write():
    text = (PACKAGE / CHILDREN["llm-wiki-ingest"]).read_text(encoding="utf-8")
    assert "validate-mapping" in text
    assert "prepare-excerpt" in text
    assert "Do not call any write command before the user confirms the preview" in text
    assert "copy-source" in text


def test_phase_one_skills_do_not_claim_person_context_views():
    combined = "\n".join((PACKAGE / path).read_text(encoding="utf-8") for path in CHILDREN.values())
    assert "person_core" not in combined
    assert "ambiguous_person" not in combined
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
& $PY -m pytest tests/test_skill_package.py -q
```

Expected: FAIL because the four child Skill files do not exist.

- [ ] **Step 3: Replace the parent with a pure router**

The parent routing table must map natural intent to one child:

```markdown
| Intent | Child |
| --- | --- |
| Initialize or enable a domain Wiki | `llm-wiki-init/SKILL.md` |
| Import files, task history, or durable results | `llm-wiki-ingest/SKILL.md` |
| Answer from an existing domain Wiki | `llm-wiki-query/SKILL.md` |
| Diagnose configuration, contracts, or health | `llm-wiki-maintain/SKILL.md` |
```

State that the parent reads and follows exactly one child, owns no domain SCP, and performs no filesystem write.

- [ ] **Step 4: Create the four focused child Skills**

Each child must have narrow trigger-only frontmatter. `llm-wiki-ingest` must implement this retry-safe order:

```text
resolve domain/profile
-> locate mapping and owner SCP
-> validate-mapping
-> acquire source with host adapter
-> show exact JD-only preview
-> wait for confirmation
-> capture confirmation time as ISO-8601 and pass it to prepare-excerpt
-> copy-source with metadata
-> write-record jd_version
-> load the exact job_profile path with a runtime context filter
-> write/update job_profile only when it does not reference jd_version_id
-> append-log by log_type with event_id hr-jd-import:{source_id}:{job_id}:{jd_version_id}
-> return context_refs and next query
```

When `copy-source`, `write-record jd_version`, and `append-log` all report `already_exists` and the existing `job_profile` already references `jd_version_id`, return overall `already_exists`. A partial retry continues only the missing steps; it never rewrites the immutable JD version or a job profile that already links that version.

Every non-enabled/error state follows `references/status-v0.1.md`; no child may raw-write inside `.llm-wiki`.

- [ ] **Step 5: Document the Codex task adapter**

`codex-thread-source.md` must require `list_threads` by user-provided title, explicit task confirmation, paginated `read_thread`, oldest-to-newest ordering, and extraction references using `thread_id/turn_id/item_id/start/end`. It must define Markdown/JSON export fallback for hosts without these tools.

- [ ] **Step 6: Run package and full runtime tests**

```powershell
& $PY -m pytest tests/test_skill_package.py -q
& $PY -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Stage Task 5 only**

```powershell
git add skills/llm-wiki-core/SKILL.md skills/llm-wiki-core/llm-wiki-init/SKILL.md skills/llm-wiki-core/llm-wiki-ingest/SKILL.md skills/llm-wiki-core/llm-wiki-ingest/references/codex-thread-source.md skills/llm-wiki-core/llm-wiki-query/SKILL.md skills/llm-wiki-core/llm-wiki-maintain/SKILL.md tests/test_skill_package.py
git diff --cached --check
```

Expected: no whitespace errors; do not commit.

---

### Task 6: Add the HR JD domain contract in role-copilot-skills

**Files (repository `C:\tmp\role-copilot-skills-llm-wiki-scp`):**
- Create: `hr-agent-copilot/llm-wiki-profile.yml`
- Create: `hr-agent-copilot/ingest-mapping.yml`
- Create: `hr-agent-copilot/references/llm-wiki-ingest.md`
- Modify: `hr-agent-copilot/hr-resume-screening-copilot/scp.yml`
- Modify: `hr-agent-copilot/tests/test_llm_wiki_integration_contract.py`
- Modify: `hr-agent-copilot/README.zh.md`
- Modify: `hr-agent-copilot/README.md`

**Interfaces:**
- HR profile records: `candidate_profile`, `job_profile`, `jd_version`。
- HR profile log: `hr_jd_import` append-only。
- Mapping owner: `hr-resume-screening-copilot`。
- Mapping source: `codex_thread_jd_excerpt`。

- [ ] **Step 1: Write failing HR contract tests**

Add these methods to the existing `HrLlmWikiIntegrationContractTest` class so `python -m unittest` discovers them:

```python
def test_hr_package_publishes_jd_ingest_contract(self):
    profile = (PACKAGE_ROOT / "llm-wiki-profile.yml").read_text(encoding="utf-8")
    mapping = (PACKAGE_ROOT / "ingest-mapping.yml").read_text(encoding="utf-8")
    reference = (PACKAGE_ROOT / "references/llm-wiki-ingest.md").read_text(encoding="utf-8")

    self.assertIn("job_profile:", profile)
    self.assertIn("path: domains/hr/jobs/{job_id}/profile.md", profile)
    self.assertIn("mode: update_allowed", profile)
    self.assertIn("jd_version:", profile)
    self.assertIn("path: domains/hr/jobs/{job_id}/versions/{jd_version_id}.md", profile)
    self.assertIn("mode: create_only", profile)
    self.assertIn("hr_jd_import:", profile)
    self.assertIn("path: logs/hr-jd-import.jsonl", profile)
    self.assertIn("owner_skill_id: hr-resume-screening-copilot", mapping)
    self.assertIn("source_types: [codex_thread_jd_excerpt]", mapping)
    self.assertIn("LLM extraction must select verbatim source ranges", reference)


def test_resume_screening_scp_authorizes_jd_mapping_products(self):
    text = (PACKAGE_ROOT / "hr-resume-screening-copilot/scp.yml").read_text(encoding="utf-8")
    for fragment in (
        "record_type: job_profile",
        "record_type: jd_version",
        "log_type: hr_jd_import",
    ):
        self.assertIn(fragment, text)
```

- [ ] **Step 2: Run the HR contract test and verify RED**

```powershell
Set-Location 'C:\tmp\role-copilot-skills-llm-wiki-scp'
& $PY -m unittest -v hr-agent-copilot.tests.test_llm_wiki_integration_contract
```

Expected: FAIL because the HR profile, mapping, reference, and SCP products do not exist.

- [ ] **Step 3: Create the authoritative HR profile**

The profile must contain:

```yaml
profile:
  id: hr
  version: v0.1
  display_name: HR Talent Pool
  scope_type: talent_pool
  privacy_default: sensitive_local

layout:
  directories:
    - domains/hr/candidates
    - domains/hr/jobs
    - sources/originals/hr/jobs
    - artifacts
    - logs

write_rules:
  records:
    candidate_profile:
      path: domains/hr/candidates/{candidate_id}/profile.md
      mode: update_allowed
      required_vars: [candidate_id]
      required_refs: [source_id, resume_version_id]
    job_profile:
      path: domains/hr/jobs/{job_id}/profile.md
      mode: update_allowed
      required_vars: [job_id]
      required_refs: [source_id, jd_version_id]
    jd_version:
      path: domains/hr/jobs/{job_id}/versions/{jd_version_id}.md
      mode: create_only
      required_vars: [job_id, jd_version_id]
      required_refs: [source_id]

logs:
  types:
    hr_jd_import:
      path: logs/hr-jd-import.jsonl
      mode: append_only

read_rules:
  context_pack:
    include: [domains/hr/**]
    exclude: [sources/originals/**, .meta/**]
    max_files: 30
    max_chars_per_file: 4000

artifacts:
  types: [screening_report, candidate_detail_report, interview_plan]
```

Phase 1 query passes `glob_filters=["domains/hr/jobs/**"]` so JD lookup stays narrow. The profile keeps the existing HR domain readable for current candidate-oriented Skills; person resolution and candidate context views remain Phase 2 work.

- [ ] **Step 4: Create mapping and semantic reference**

Use the exact mapping contract from Task 4. The reference must define:

```text
Only JD content is in Phase 1 scope.
LLM extraction must select verbatim source ranges.
Do not derive jd_version_id from structured output.
Do not import resumes, candidate facts, scores, or interview feedback.
Do not merge job identities without user confirmation.
Separate source-backed facts, interpretation, and unknowns in job_profile/jd_version Markdown.
Use event_id hr-jd-import:{source_id}:{job_id}:{jd_version_id} for the import log.
```

- [ ] **Step 5: Extend owner SCP and README usage**

Add the three products to `hr-resume-screening-copilot/scp.yml`. Document these natural-language acceptance prompts in both HR READMEs:

```text
初始化 HR 知识库
把旧任务“Java 高级开发招聘筛选”中的历史 JD 导入 HR Wiki
查询刚才导入的历史 JD
```

- [ ] **Step 6: Run HR package tests**

```powershell
& $PY -m unittest -v hr-agent-copilot.tests.test_llm_wiki_integration_contract
```

Expected: all tests pass.

- [ ] **Step 7: Stage Task 6 only**

```powershell
git add hr-agent-copilot/llm-wiki-profile.yml hr-agent-copilot/ingest-mapping.yml hr-agent-copilot/references/llm-wiki-ingest.md hr-agent-copilot/hr-resume-screening-copilot/scp.yml hr-agent-copilot/tests/test_llm_wiki_integration_contract.py hr-agent-copilot/README.md hr-agent-copilot/README.zh.md
git diff --cached --check
```

Expected: no whitespace errors; do not commit.

---

### Task 7: Add deterministic end-to-end HR JD fixture coverage

**Files (runtime repository):**
- Create: `tests/fixtures/hr-jd-profile.yml`
- Create: `tests/fixtures/hr-jd-mapping.yml`
- Create: `tests/fixtures/hr-jd-owner.scp.yml`
- Create: `tests/fixtures/hr-jd-thread-items.json`
- Create: `tests/fixtures/hr-jd-selections.json`
- Create: `tests/test_hr_jd_flow.py`

**Interfaces:**
- Exercises: init-profile -> scan-scp -> validate-mapping -> prepare-excerpt -> copy-source -> write-record x2 -> append-log -> load-context-pack.
- Proves: duplicate re-run is idempotent and query excludes source originals.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_hr_jd_flow.py` using direct Python APIs; subprocess envelope behavior is already covered by the focused CLI tests. The final assertions must be:

```python
assert (scope / ".llm-wiki/domains/hr/jobs/job-java-senior/profile.md").is_file()
assert (scope / f".llm-wiki/domains/hr/jobs/job-java-senior/versions/{version_id}.md").is_file()
assert (scope / ".llm-wiki/logs/hr-jd-import.jsonl").is_file()
assert len(registry["sources"]) == 1
assert second_copy["status"] == "already_exists"
assert second_version["status"] == "already_exists"
assert second_profile_checksum == first_profile_checksum
assert len((scope / ".llm-wiki/logs/hr-jd-import.jsonl").read_text(encoding="utf-8").splitlines()) == 1
assert context_payload["status"] == "ok"
assert all("sources/originals" not in item["path"] for item in context_payload["items"])
assert "test@example.com" not in snapshot_text
```

The fixture thread must contain one clean JD message and one unrelated candidate message. The selections fixture selects only the clean JD message.

- [ ] **Step 2: Run the integration test and verify RED**

```powershell
Set-Location 'D:\tmp\github\llm-wiki-runtime'
& $PY -m pytest tests/test_hr_jd_flow.py -q
```

Expected: FAIL until Tasks 1-6 are integrated.

- [ ] **Step 3: Resolve failures in their owning tasks**

No production code belongs uniquely to Task 7. If the integration test fails, update the implementation and focused test in the owning Task 1-6 file set, then rerun that focused test before rerunning `tests/test_hr_jd_flow.py`. Do not add person resolution, context views, resume ingestion, or lifecycle status handling.

- [ ] **Step 4: Run the complete runtime and HR suites**

```powershell
Set-Location 'D:\tmp\github\llm-wiki-runtime'
& $PY -m pytest -q

Set-Location 'C:\tmp\role-copilot-skills-llm-wiki-scp'
& $PY -m unittest -v hr-agent-copilot.tests.test_llm_wiki_integration_contract
```

Expected: both commands exit 0 with no failures.

- [ ] **Step 5: Stage Task 7 only**

```powershell
Set-Location 'D:\tmp\github\llm-wiki-runtime'
git add tests/fixtures/hr-jd-profile.yml tests/fixtures/hr-jd-mapping.yml tests/fixtures/hr-jd-owner.scp.yml tests/fixtures/hr-jd-thread-items.json tests/fixtures/hr-jd-selections.json tests/test_hr_jd_flow.py
git diff --cached --check
```

Expected: no whitespace errors; do not commit.

---

### Task 8: Install and run the live init/ingest/query acceptance test

**Files:**
- Install from: `D:\tmp\github\llm-wiki-runtime\skills\llm-wiki-core`
- Install to: `C:\Users\admin\.codex-clean-20260710\skills\llm-wiki-core`
- Refresh HR package from: `C:\tmp\role-copilot-skills-llm-wiki-scp\hr-agent-copilot`
- Refresh HR package to: `C:\Users\admin\.codex-clean-20260710\skills\hr-agent-copilot`
- Runtime editable source: `D:\tmp\github\llm-wiki-runtime`

**Interfaces:**
- Human prompt 1 initializes `hr-default`.
- Human prompt 2 imports one selected old Codex task after preview confirmation.
- Human prompt 3 queries imported JD records.

- [ ] **Step 1: Run pre-install verification**

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location 'D:\tmp\github\llm-wiki-runtime'
& $PY -m pytest -q

Set-Location 'C:\tmp\role-copilot-skills-llm-wiki-scp'
& $PY -m unittest -v hr-agent-copilot.tests.test_llm_wiki_integration_contract
```

Expected: both suites pass.

- [ ] **Step 2: Back up and install both complete Skill packages**

Use native PowerShell `Copy-Item`/`Move-Item`. Resolve and verify every absolute source/target path before moving. For each package, set `$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'` and `$backup = Join-Path 'C:\tmp' "$($package.Name)-backup-$timestamp"`; move any existing target to that resolved backup path and never delete it.

- [ ] **Step 3: Verify installed package discovery contracts**

Assert these files exist:

```text
C:\Users\admin\.codex-clean-20260710\skills\llm-wiki-core\SKILL.md
C:\Users\admin\.codex-clean-20260710\skills\llm-wiki-core\llm-wiki-init\SKILL.md
C:\Users\admin\.codex-clean-20260710\skills\llm-wiki-core\llm-wiki-ingest\SKILL.md
C:\Users\admin\.codex-clean-20260710\skills\llm-wiki-core\llm-wiki-query\SKILL.md
C:\Users\admin\.codex-clean-20260710\skills\llm-wiki-core\llm-wiki-maintain\SKILL.md
C:\Users\admin\.codex-clean-20260710\skills\hr-agent-copilot\llm-wiki-profile.yml
C:\Users\admin\.codex-clean-20260710\skills\hr-agent-copilot\ingest-mapping.yml
```

Create a new Codex task and ask it to list all `llm-wiki-*` and HR Skills. Expected: parent plus four child Wiki Skills and parent plus three child HR Skills.

- [ ] **Step 4: Run live init**

Prompt:

```text
初始化 HR 知识库。请在执行前说明采用的 Skill 名称。
```

Expected:

- Uses `llm-wiki-init`.
- Asks once before creating sensitive HR storage.
- After confirmation, `resolve-config --profile hr` returns `enabled`, `scope_id=hr-default`, and an existing `profile.yml` snapshot.
- Does not modify any `scp.yml`.

- [ ] **Step 5: Run live historical JD ingest**

Prompt:

```text
先用 `list_threads(query="招聘", limit=20)` 找到旧招聘任务，让用户确认其中一个准确标题并记为 `$THREAD_TITLE`。然后执行：把旧任务“$THREAD_TITLE”中的历史 JD 导入 HR Wiki。只处理 JD，不导入简历、候选人、评分或面试信息；写入前先给我预览。
```

Expected:

- Uses `llm-wiki-ingest`.
- Uses `list_threads`, asks the user to confirm the exact task, then uses paginated `read_thread`.
- Shows JD verbatim ranges and risk flags before any write.
- Writes only after confirmation.
- Produces one source registry entry with excerpt provenance, `job_profile`, `jd_version`, and one `hr_jd_import` log event.

- [ ] **Step 6: Run live query and filesystem audit**

Prompt:

```text
查询刚才导入的历史 JD，列出岗位、JD 版本和来源引用。
```

Expected:

- Uses `llm-wiki-query`.
- Returns the imported job/version with context refs.
- Does not include `sources/originals/**` in the context pack.
- A recursive search under the created HR scope finds no resume text, candidate name, contact information, screening score, or interview feedback from the selected old task.

- [ ] **Step 7: Re-run ingest to prove idempotency**

Repeat the same import and confirm the same excerpt. Expected: overall `already_exists`; source registry and JD version counts stay unchanged, `job_profile` keeps its first checksum, and `hr-jd-import.jsonl` still contains exactly one event for the deterministic `event_id`.

- [ ] **Step 8: Report final local state**

Report:

```text
runtime test count and result
HR contract test count and result
installed Skill paths
HR scope_root and wiki_root
job_id, jd_version_id, source_id
files created under domains/hr/jobs
privacy audit result
all staged files in each repository
```

Do not commit or push either repository.
