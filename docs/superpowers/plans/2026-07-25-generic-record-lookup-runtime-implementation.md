# 通用记录检索 Runtime 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `llm-wiki-runtime` 增加由 Domain Profile 声明的通用记录检索能力，并在 `write-record` 边界拒绝非法控制字符。

**Architecture:** Domain Profile 声明记录类型的身份字段、展示字段、匹配字段和返回白名单；Runtime 只执行确定性的 frontmatter 扫描、授权、精确匹配和结果裁剪。记录查询复用 context pack 的路径白名单语义，但不读取 Markdown 正文、不依赖 Graph，也不引入任何 HR 专有分支。

**Tech Stack:** Python 3.10+、stdlib、`pytest==9.1.1`、现有 `llm-wiki-runtime` CLI 和受限 frontmatter 解析器。

## Global Constraints

- Runtime 代码、错误、CLI 参数和测试夹具不得包含 HR 专有判断。
- `find-records` 只读取 scope 内当前 Profile 快照，不读取宿主 Skill registry、Graph 或 source registry。
- 字符串只做 Unicode NFC 规范化，保持大小写敏感，不做子串、模糊或 LLM 推断。
- 结果只返回 Profile 的 `return_fields` 白名单、相对 POSIX 路径、checksum、`identity` 和 `display`。
- `.meta/**` 始终强制排除，其他路径遵循 Profile 的 `read_rules.context_pack`。
- `write-record` 允许 TAB、LF、CR，拒绝其他 C0 控制字符和 DEL；校验必须发生在 scope lock 和文件修改之前。
- 测试只使用 `project_record`、`package_record` 等合成数据，不包含真实候选人资料。
- 不新增运行时第三方依赖。
- 不创建新的远程开发分支；验证后使用 fast-forward `HEAD:main`。

---

### Task 1: 扩展 Domain Profile 的声明模型

**Files:**
- Modify: `llm_wiki_runtime/models.py`
- Modify: `llm_wiki_runtime/frontmatter.py`
- Modify: `llm_wiki_runtime/profile.py`
- Modify: `tests/test_profile.py`

**Interfaces:**
- Produces: `RecordLookupRule`
- Produces: `Profile.record_lookup: dict[str, RecordLookupRule]`
- Produces: `is_frontmatter_field_name(value: str) -> bool`
- Consumes: 现有 `write_rules.records` 和受限 YAML-like Profile 解析器

- [ ] **Step 1: 写入 Profile 声明解析的失败测试**

在 `tests/test_profile.py` 增加：

```python
def lookup_profile_text() -> str:
    return "\n".join(
        [
            "profile:",
            "  id: projects",
            "  version: v0.1",
            "write_rules:",
            "  records:",
            "    project_record:",
            "      path: domains/projects/{project_id}/profile.md",
            "      mode: update_allowed",
            "      required_vars: [project_id]",
            "      required_refs: []",
            "read_rules:",
            "  context_pack:",
            "    include: [domains/projects/**]",
            "    exclude: [.meta/**]",
            "  record_lookup:",
            "    project_record:",
            "      identity_field: project_id",
            "      display_field: display_name",
            "      match_fields: [display_name, aliases]",
            "      return_fields:",
            "        - project_id",
            "        - display_name",
            "        - aliases",
            "        - status",
            "      max_results: 10",
        ]
    )


def test_load_profile_parses_record_lookup_rules(tmp_path):
    profile_path = tmp_path / "profile.yml"
    profile_path.write_text(lookup_profile_text(), encoding="utf-8")

    profile = load_profile(profile_path)

    rule = profile.record_lookup["project_record"]
    assert rule.identity_field == "project_id"
    assert rule.display_field == "display_name"
    assert rule.match_fields == ("display_name", "aliases")
    assert rule.return_fields == ("project_id", "display_name", "aliases", "status")
    assert rule.max_results == 10


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("      unknown_key: value", "unsupported record lookup fields"),
        ("      match_fields: []", "match_fields must not be empty"),
        ("      return_fields: [display_name]", "return_fields must contain identity_field"),
        ("      max_results: 0", "max_results must be an integer from 1 through 100"),
    ],
)
def test_load_profile_rejects_invalid_record_lookup_rules(tmp_path, replacement, message):
    profile_path = tmp_path / "profile.yml"
    text = lookup_profile_text().replace("      max_results: 10", replacement)
    profile_path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_profile(profile_path)


def test_load_profile_rejects_lookup_for_undeclared_record_type(tmp_path):
    profile_path = tmp_path / "profile.yml"
    text = lookup_profile_text().replace("    project_record:\n      identity_field", "    package_record:\n      identity_field")
    profile_path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="lookup record type is not writable"):
        load_profile(profile_path)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_profile.py -q
```

Expected: FAIL，因为 `Profile` 还没有 `record_lookup`，解析器也不会读取该段。

- [ ] **Step 3: 增加不可变的声明模型和字段名校验**

在 `llm_wiki_runtime/models.py` 增加：

```python
@dataclass(frozen=True)
class RecordLookupRule:
    record_type: str
    identity_field: str
    display_field: str
    match_fields: tuple[str, ...]
    return_fields: tuple[str, ...]
    max_results: int = 20
```

并在 `Profile` 增加：

```python
record_lookup: dict[str, RecordLookupRule] = field(default_factory=dict)
```

在 `llm_wiki_runtime/frontmatter.py` 增加：

```python
def is_frontmatter_field_name(value: str) -> bool:
    return isinstance(value, str) and bool(_KEY_RE.fullmatch(value))
```

- [ ] **Step 4: 在 Profile 解析器中实现严格的 `record_lookup` 解析**

在 `llm_wiki_runtime/profile.py` 引入 `RecordLookupRule` 和
`is_frontmatter_field_name`，增加 `_build_record_lookup_rule`：

```python
_LOOKUP_KEYS = {
    "identity_field",
    "display_field",
    "match_fields",
    "return_fields",
    "max_results",
}


def _build_record_lookup_rule(
    record_type: str,
    values: dict[str, object],
) -> RecordLookupRule:
    unknown = sorted(set(values) - _LOOKUP_KEYS)
    if unknown:
        raise ValueError(f"unsupported record lookup fields: {unknown}")

    identity_field = values.get("identity_field")
    display_field = values.get("display_field")
    match_fields = tuple(values.get("match_fields", []))
    return_fields = tuple(values.get("return_fields", []))
    max_results = values.get("max_results", 20)

    named_fields = [identity_field, display_field, *match_fields, *return_fields]
    if not all(is_frontmatter_field_name(value) for value in named_fields):
        raise ValueError(f"invalid frontmatter field name in record lookup: {record_type}")
    if not match_fields:
        raise ValueError(f"match_fields must not be empty: {record_type}")
    if len(set(match_fields)) != len(match_fields):
        raise ValueError(f"match_fields must be unique: {record_type}")
    if identity_field not in return_fields:
        raise ValueError(f"return_fields must contain identity_field: {record_type}")
    if display_field not in return_fields:
        raise ValueError(f"return_fields must contain display_field: {record_type}")
    if type(max_results) is not int or not 1 <= max_results <= 100:
        raise ValueError("max_results must be an integer from 1 through 100")

    return RecordLookupRule(
        record_type=record_type,
        identity_field=identity_field,
        display_field=display_field,
        match_fields=match_fields,
        return_fields=return_fields,
        max_results=max_results,
    )
```

在 `load_profile` 中维护 `record_lookup_values`、当前 lookup 类型、当前规则和
`current_lookup_list_key`。`read_rules.record_lookup` 的四空格层级表示记录类型，
六空格层级表示规则键；`match_fields:` 或 `return_fields:` 后的八空格 `- value`
需要追加到当前列表。核心分支使用：

```python
elif section == "read_rules":
    if indent == 2 and stripped == "context_pack:":
        in_context_pack = True
        in_record_lookup = False
    elif indent == 2 and stripped == "record_lookup:":
        flush_lookup_rule()
        in_context_pack = False
        in_record_lookup = True
    elif in_context_pack and indent >= 4 and ":" in stripped:
        key, value = stripped.split(":", 1)
        context_values[key] = parse_scalar(value)
    elif in_record_lookup and indent == 4 and stripped.endswith(":"):
        flush_lookup_rule()
        current_lookup_record = stripped[:-1]
    elif current_lookup_record and indent == 6 and ":" in stripped:
        key, value = stripped.split(":", 1)
        value = value.strip()
        current_lookup_list_key = None
        if key in {"match_fields", "return_fields"} and not value:
            current_lookup_rule[key] = []
            current_lookup_list_key = key
        else:
            current_lookup_rule[key] = parse_scalar(value)
    elif (
        current_lookup_record
        and current_lookup_list_key
        and indent == 8
        and stripped.startswith("- ")
    ):
        current_lookup_rule[current_lookup_list_key].append(
            parse_scalar(stripped[2:])
        )
```

`flush_lookup_rule()` 使用 `_build_record_lookup_rule` 生成不可变规则，并清空
当前记录、规则和列表键。所有记录和 lookup 规则 flush 完成后执行：

```python
for lookup_record_type in record_lookup:
    if lookup_record_type not in write_rules:
        raise ValueError(
            f"lookup record type is not writable: {lookup_record_type}"
        )
```

构造 `Profile` 时传入：

```python
record_lookup=record_lookup,
```

- [ ] **Step 5: 运行 Profile 测试**

Run:

```powershell
python -m pytest tests/test_profile.py tests/test_init_profile.py -q
```

Expected: PASS，旧 Profile 不含 `record_lookup` 时仍能正常解析。

- [ ] **Step 6: 提交声明模型**

```powershell
git add llm_wiki_runtime/models.py llm_wiki_runtime/frontmatter.py llm_wiki_runtime/profile.py tests/test_profile.py
git commit -m "feat: declare generic record lookup rules"
```

---

### Task 2: 统一读取路径白名单枚举

**Files:**
- Create: `llm_wiki_runtime/read_paths.py`
- Modify: `llm_wiki_runtime/runtime.py`
- Create: `tests/test_read_paths.py`
- Modify: `tests/test_context_pack.py`

**Interfaces:**
- Produces: `iter_readable_files(wiki_root, include, exclude, order) -> list[Path]`
- Consumes: scope 相对 POSIX 路径和 Profile 的 include/exclude glob
- Preserves: `load_context_pack` 现有排序、强制 `.meta/**` 排除和过滤行为

- [ ] **Step 1: 写入共享路径枚举的失败测试**

创建 `tests/test_read_paths.py`：

```python
from llm_wiki_runtime.read_paths import iter_readable_files


def test_iter_readable_files_uses_posix_order_and_forces_meta_exclusion(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    (wiki_root / "domains/projects/b").mkdir(parents=True)
    (wiki_root / "domains/projects/a").mkdir(parents=True)
    (wiki_root / ".meta").mkdir(parents=True)
    (wiki_root / "domains/projects/b/profile.md").write_text("b", encoding="utf-8")
    (wiki_root / "domains/projects/a/profile.md").write_text("a", encoding="utf-8")
    (wiki_root / ".meta/profile.yml").write_text("secret", encoding="utf-8")

    paths = iter_readable_files(wiki_root, ["**"], [], "path_asc")

    assert [path.relative_to(wiki_root).as_posix() for path in paths] == [
        "domains/projects/a/profile.md",
        "domains/projects/b/profile.md",
    ]
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run:

```powershell
python -m pytest tests/test_read_paths.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 创建通用读取路径模块**

创建 `llm_wiki_runtime/read_paths.py`：

```python
from __future__ import annotations

import fnmatch
from pathlib import Path


FORCED_EXCLUDES = (".meta/**",)


def effective_excludes(exclude: list[str]) -> list[str]:
    return list(dict.fromkeys([*exclude, *FORCED_EXCLUDES]))


def is_included(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def is_excluded(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def iter_readable_files(
    wiki_root: Path,
    include: list[str],
    exclude: list[str],
    order: str = "path_asc",
) -> list[Path]:
    excluded = effective_excludes(exclude)
    paths = []
    for path in wiki_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(wiki_root).as_posix()
        if is_included(relative, include) and not is_excluded(relative, excluded):
            paths.append(path)
    if order == "mtime_desc":
        return sorted(
            paths,
            key=lambda item: (
                -item.stat().st_mtime,
                item.relative_to(wiki_root).as_posix(),
            ),
        )
    if order != "path_asc":
        raise ValueError(f"unsupported read order: {order}")
    return sorted(paths, key=lambda item: item.relative_to(wiki_root).as_posix())
```

- [ ] **Step 4: 让 context pack 复用共享枚举**

在 `llm_wiki_runtime/runtime.py` 删除本地 `is_included`、`is_excluded` 和
`sort_context_paths`，引入：

```python
from .read_paths import iter_readable_files
```

把 `load_context_pack` 的候选文件循环替换为：

```python
eligible_paths: list[str] = []
items = []
for path in iter_readable_files(wiki_root, include, exclude, order):
    rel = path.relative_to(wiki_root).as_posix()
    eligible_paths.append(rel)
    if not matches_any_filter(rel, path_filters) or not matches_any_filter(rel, glob_filters):
        continue
    if len(items) >= max_files:
        continue
    text = path.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]
    checksum = "sha256:" + sha256_file(path)
    item = {"path": rel, "content": text, "checksum": checksum}
    if effective_policy == "data_only":
        risk_flags = data_only_flags(text)
        item.update(
            {
                "instruction_policy": "data_only",
                "sanitized": bool(risk_flags),
                "risk_flags": risk_flags,
            }
        )
    else:
        item.update(
            {
                "instruction_policy": "trusted_content",
                "sanitized": False,
                "risk_flags": [],
            }
        )
    items.append(item)
```

- [ ] **Step 5: 运行路径和 context pack 回归测试**

Run:

```powershell
python -m pytest tests/test_read_paths.py tests/test_context_pack.py -q
```

Expected: PASS，context pack 输出保持不变。

- [ ] **Step 6: 提交路径复用**

```powershell
git add llm_wiki_runtime/read_paths.py llm_wiki_runtime/runtime.py tests/test_read_paths.py tests/test_context_pack.py
git commit -m "refactor: share authorized read path enumeration"
```

---

### Task 3: 实现 frontmatter-only 记录检索

**Files:**
- Create: `llm_wiki_runtime/record_lookup.py`
- Create: `tests/test_record_lookup.py`

**Interfaces:**
- Produces: `find_records(scope_root, record_type, lookup_value, *, caller_domain, target_domain, domain_policies, caller_groups) -> dict`
- Consumes: `Profile.record_lookup`、`iter_readable_files`、`parse_frontmatter`、现有授权策略
- Output statuses: `found`、`not_found`、`multiple_matches`、`read_denied`

- [ ] **Step 1: 写入核心检索失败测试**

创建 `tests/test_record_lookup.py`，使用 `project_record` 合成 Profile 和记录，
至少覆盖以下断言：

```python
def test_find_records_matches_display_name_and_returns_allowlisted_fields(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Atlas",
        caller_domain="projects",
        target_domain="projects",
    )

    assert payload["status"] == "found"
    assert payload["truncated"] is False
    assert payload["matches"][0]["path"] == "domains/projects/project-001/profile.md"
    assert payload["matches"][0]["identity"] == "project-001"
    assert payload["matches"][0]["display"] == "Atlas"
    assert payload["matches"][0]["fields"] == {
        "project_id": "project-001",
        "display_name": "Atlas",
        "aliases": ["Atlas Platform"],
        "status": "active",
    }
    assert "private_note" not in payload["matches"][0]["fields"]


def test_find_records_matches_alias_with_unicode_nfc(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Cafe\u0301 Platform",
        caller_domain="projects",
        target_domain="projects",
    )

    assert payload["status"] == "found"
    assert payload["matches"][0]["display"] == "Café"


def test_find_records_returns_multiple_matches_without_selecting_one(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Shared",
        caller_domain="projects",
        target_domain="projects",
    )

    assert payload["status"] == "multiple_matches"
    assert [match["path"] for match in payload["matches"]] == sorted(
        match["path"] for match in payload["matches"]
    )


def test_find_records_does_not_read_markdown_body(project_scope):
    path = project_scope / ".llm-wiki/domains/projects/body-only/profile.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nrecord_type: project_record\nproject_id: body-only\n"
        "display_name: Other\naliases: []\nstatus: active\n---\nAtlas",
        encoding="utf-8",
    )

    payload = find_records(
        project_scope,
        "project_record",
        "Atlas",
        caller_domain="projects",
        target_domain="projects",
    )

    assert all(match["identity"] != "body-only" for match in payload["matches"])


def test_find_records_denies_cross_domain_without_returning_metadata(project_scope):
    payload = find_records(
        project_scope,
        "project_record",
        "Atlas",
        caller_domain="learning",
        target_domain="projects",
        domain_policies={"projects": {"readable_by": []}},
    )

    assert payload == {
        "status": "read_denied",
        "reason": "domain_not_readable_by_caller",
        "record_type": "project_record",
        "matches": [],
        "context_refs": [],
        "warnings": [],
        "truncated": False,
    }
```

同一文件继续覆盖：大小写不匹配、数字和字符串不混淆、Graph 缺失、
`.meta/**` 排除、`sources/originals/**` 排除、64 KiB 超限、缺失结束分隔符、
无效 frontmatter、正文含 NUL 的旧记录仍可按 frontmatter 找到、稳定告警码、
`max_results` 截断和 `context_refs`。

- [ ] **Step 2: 运行测试并确认模块不存在**

Run:

```powershell
python -m pytest tests/test_record_lookup.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 创建记录检索模块**

创建 `llm_wiki_runtime/record_lookup.py`，实现以下完整公共契约：

```python
from __future__ import annotations

import math
import unicodedata
from pathlib import Path

from .frontmatter import FrontmatterScalar, FrontmatterValue, parse_frontmatter
from .io import sha256_file
from .policy import assert_read_allowed, load_domain_policies
from .profile import load_active_profile
from .read_paths import iter_readable_files


MAX_FRONTMATTER_BYTES = 64 * 1024
LookupScalar = str | int | float | bool


def _is_lookup_scalar(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str)


def _scalar_equal(stored: FrontmatterScalar, lookup: LookupScalar) -> bool:
    if isinstance(stored, str) and isinstance(lookup, str):
        return unicodedata.normalize("NFC", stored) == unicodedata.normalize("NFC", lookup)
    return type(stored) is type(lookup) and stored == lookup


def _field_matches(value: FrontmatterValue | None, lookup: LookupScalar) -> bool:
    if isinstance(value, list):
        return any(_scalar_equal(item, lookup) for item in value)
    return _scalar_equal(value, lookup)


def _read_frontmatter(path: Path) -> tuple[dict[str, FrontmatterValue] | None, str | None]:
    with path.open("rb") as handle:
        data = handle.read(MAX_FRONTMATTER_BYTES + 1)
    lines = data.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        return None, None

    end = len(lines[0])
    for line in lines[1:]:
        end += len(line)
        if end > MAX_FRONTMATTER_BYTES:
            return None, "frontmatter_too_large"
        if line.rstrip(b"\r\n") == b"---":
            try:
                text = data[:end].decode("utf-8")
                metadata, _ = parse_frontmatter(text)
            except (UnicodeDecodeError, ValueError):
                return None, "frontmatter_invalid"
            return metadata, None

    if len(data) > MAX_FRONTMATTER_BYTES:
        return None, "frontmatter_too_large"
    return None, "frontmatter_missing_closing_delimiter"


def _warning(code: str, relative_path: str) -> dict[str, str]:
    return {"code": code, "path": relative_path}


def find_records(
    scope_root: Path,
    record_type: str,
    lookup_value: LookupScalar,
    *,
    caller_domain: str | None = None,
    target_domain: str | None = None,
    domain_policies: dict | None = None,
    caller_groups: list[str] | None = None,
) -> dict:
    if not _is_lookup_scalar(lookup_value):
        raise ValueError("lookup value must be a non-null finite JSON scalar")

    profile = load_active_profile(scope_root)
    rule = profile.record_lookup.get(record_type)
    if rule is None:
        raise ValueError(f"record lookup is not declared: {record_type}")

    policies = load_domain_policies(domain_policies)
    allowed, reason = assert_read_allowed(
        caller_domain,
        target_domain,
        policies,
        caller_groups,
    )
    if not allowed:
        return {
            "status": "read_denied",
            "reason": reason,
            "record_type": record_type,
            "matches": [],
            "context_refs": [],
            "warnings": [],
            "truncated": False,
        }

    wiki_root = scope_root / ".llm-wiki"
    matches: list[dict] = []
    warnings: list[dict[str, str]] = []
    matched_count = 0

    for path in iter_readable_files(
        wiki_root,
        profile.context_pack.include,
        profile.context_pack.exclude,
    ):
        relative = path.relative_to(wiki_root).as_posix()
        metadata, warning_code = _read_frontmatter(path)
        if warning_code is not None:
            warnings.append(_warning(warning_code, relative))
            continue
        if metadata is None or metadata.get("record_type") != record_type:
            continue
        if not any(
            _field_matches(metadata.get(field), lookup_value)
            for field in rule.match_fields
        ):
            continue

        identity = metadata.get(rule.identity_field)
        display = metadata.get(rule.display_field)
        if not _is_lookup_scalar(identity) or not _is_lookup_scalar(display):
            warnings.append(_warning("record_identity_invalid", relative))
            continue

        matched_count += 1
        if len(matches) >= rule.max_results:
            continue
        fields = {
            field: metadata[field]
            for field in rule.return_fields
            if field in metadata
        }
        matches.append(
            {
                "path": relative,
                "checksum": "sha256:" + sha256_file(path),
                "identity": identity,
                "display": display,
                "fields": fields,
            }
        )

    status = (
        "not_found"
        if matched_count == 0
        else "found"
        if matched_count == 1
        else "multiple_matches"
    )
    return {
        "status": status,
        "record_type": record_type,
        "lookup_value": lookup_value,
        "matches": matches,
        "context_refs": [
            {"path": match["path"], "checksum": match["checksum"]}
            for match in matches
        ],
        "warnings": warnings,
        "truncated": matched_count > len(matches),
    }
```

- [ ] **Step 4: 运行核心检索测试**

Run:

```powershell
python -m pytest tests/test_record_lookup.py -q
```

Expected: PASS，且测试不创建 Graph 目录。

- [ ] **Step 5: 运行读取相关回归**

Run:

```powershell
python -m pytest tests/test_frontmatter.py tests/test_policy.py tests/test_context_pack.py tests/test_record_lookup.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交检索核心**

```powershell
git add llm_wiki_runtime/record_lookup.py tests/test_record_lookup.py
git commit -m "feat: resolve records from declared metadata"
```

---

### Task 4: 增加 `find-records` CLI

**Files:**
- Modify: `llm_wiki_runtime/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces CLI: `llm-wiki find-records`
- Consumes CLI JSON scalar: `--lookup-value-json`
- Exit codes: 0 for `found`、`not_found`、`multiple_matches`; 1 for `read_denied`; 2 for validation errors

- [ ] **Step 1: 写入 CLI 失败测试**

在 `tests/test_cli.py` 增加一个合成 scope fixture，并增加：

```python
def test_cli_find_records_returns_multiple_matches_with_exit_zero(project_lookup_scope):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "find-records",
            "--scope-root",
            str(project_lookup_scope),
            "--record-type",
            "project_record",
            "--lookup-value-json",
            json.dumps("Shared"),
            "--caller-domain",
            "projects",
            "--target-domain",
            "projects",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["status"] == "multiple_matches"
    assert payload["context_refs"]


@pytest.mark.parametrize("lookup_json", ["null", "[]", "{}", "NaN"])
def test_cli_find_records_rejects_non_scalar_or_non_finite_values(
    project_lookup_scope,
    lookup_json,
):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_wiki_runtime.cli",
            "find-records",
            "--scope-root",
            str(project_lookup_scope),
            "--record-type",
            "project_record",
            "--lookup-value-json",
            lookup_json,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "validation_error"
```

- [ ] **Step 2: 运行 CLI 测试并确认失败**

Run:

```powershell
python -m pytest tests/test_cli.py -q
```

Expected: FAIL，因为 parser 不认识 `find-records`。

- [ ] **Step 3: 实现参数解析与状态退出码**

在 `llm_wiki_runtime/cli.py` 引入：

```python
import math

from .record_lookup import find_records
```

新增校验函数：

```python
def parse_lookup_value(raw: str):
    value = json.loads(raw)
    if value is None or isinstance(value, (list, dict)):
        raise ValueError("lookup value must be a non-null finite JSON scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("lookup value must be a non-null finite JSON scalar")
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError("lookup value must be a non-null finite JSON scalar")
    return value
```

在 `build_parser` 增加：

```python
lookup = sub.add_parser("find-records")
lookup.add_argument("--scope-root", required=True)
lookup.add_argument("--record-type", required=True)
lookup.add_argument("--lookup-value-json", required=True)
lookup.add_argument("--caller-domain")
lookup.add_argument("--target-domain")
lookup.add_argument("--domain-policies-json")
lookup.add_argument("--caller-groups-json", default="[]")
```

在 `main` 增加：

```python
if args.command == "find-records":
    payload = find_records(
        Path(args.scope_root),
        args.record_type,
        parse_lookup_value(args.lookup_value_json),
        caller_domain=args.caller_domain,
        target_domain=args.target_domain,
        domain_policies=(
            json.loads(args.domain_policies_json)
            if args.domain_policies_json
            else None
        ),
        caller_groups=json.loads(args.caller_groups_json),
    )
    return emit(payload, 1 if payload["status"] == "read_denied" else 0)
```

- [ ] **Step 4: 运行 CLI 测试**

Run:

```powershell
python -m pytest tests/test_cli.py tests/test_record_lookup.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 CLI**

```powershell
git add llm_wiki_runtime/cli.py tests/test_cli.py
git commit -m "feat: expose generic record lookup cli"
```

---

### Task 5: 在 `write-record` 边界拒绝非法控制字符

**Files:**
- Create: `llm_wiki_runtime/content_validation.py`
- Modify: `llm_wiki_runtime/runtime.py`
- Modify: `tests/test_write_record.py`

**Interfaces:**
- Produces: `validate_record_text(text: str) -> None`
- Consumes: `write_record` 从 `content_file` 读取的文本
- Preserves: `copy-source` 字节保真行为

- [ ] **Step 1: 写入原子拒绝和允许字符测试**

在 `tests/test_write_record.py` 增加：

```python
@pytest.mark.parametrize("character", ["\x00", "\x01", "\x0b", "\x0c", "\x1f", "\x7f"])
def test_write_record_rejects_forbidden_controls_without_changing_target(
    tmp_path,
    character,
):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "profile.yml"
    write_profile(profile)
    target = wiki_root / "domains/hr/screenings/run-001/report.md"
    target.parent.mkdir(parents=True)
    target.write_text("original", encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text(f"unsafe{character}text", encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden control character"):
        write_record(
            tmp_path,
            profile,
            "screening_report",
            {"run_id": "run-001"},
            {},
            content,
        )

    assert target.read_text(encoding="utf-8") == "original"


def test_write_record_allows_tab_line_feed_and_carriage_return(tmp_path):
    wiki_root = tmp_path / ".llm-wiki"
    wiki_root.mkdir()
    profile = tmp_path / "profile.yml"
    write_profile(profile)
    content = tmp_path / "content.md"
    content.write_text("one\ttwo\nthree\rfour", encoding="utf-8")

    payload = write_record(
        tmp_path,
        profile,
        "screening_report",
        {"run_id": "run-safe"},
        {},
        content,
    )

    assert payload["status"] == "ok"
```

- [ ] **Step 2: 运行测试并确认非法字符仍能写入或覆盖**

Run:

```powershell
python -m pytest tests/test_write_record.py -q
```

Expected: FAIL，目标内容被修改或未抛出校验错误。

- [ ] **Step 3: 创建内容校验模块**

创建 `llm_wiki_runtime/content_validation.py`：

```python
from __future__ import annotations


_ALLOWED_C0 = {"\t", "\n", "\r"}


def validate_record_text(text: str) -> None:
    for character in text:
        codepoint = ord(character)
        if (codepoint < 0x20 and character not in _ALLOWED_C0) or codepoint == 0x7F:
            raise ValueError(
                f"record content contains forbidden control character U+{codepoint:04X}"
            )
```

- [ ] **Step 4: 在加锁前调用校验**

在 `llm_wiki_runtime/runtime.py` 引入：

```python
from .content_validation import validate_record_text
```

在 `write_record` 中保持读取顺序，并在 `ScopeLock` 之前加入：

```python
content = content_file.read_text(encoding="utf-8")
validate_record_text(content)
with ScopeLock(wiki_root, command="write-record"):
```

- [ ] **Step 5: 运行写入与来源回归测试**

Run:

```powershell
python -m pytest tests/test_write_record.py tests/test_cli.py -q
```

Expected: PASS。`copy_source` 不调用该校验，二进制来源行为不变。

- [ ] **Step 6: 提交内容边界**

```powershell
git add llm_wiki_runtime/content_validation.py llm_wiki_runtime/runtime.py tests/test_write_record.py
git commit -m "fix: reject unsafe record control characters"
```

---

### Task 6: 更新 Core Query、示例和端到端验收

**Files:**
- Modify: `skills/llm-wiki-core/llm-wiki-query/SKILL.md`
- Modify: `tests/test_skill_package.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `examples/hr/llm-wiki-profile.yml`
- Create: `tests/test_record_lookup_end_to_end.py`

**Interfaces:**
- Core query 顺序: 已知路径直接加载；只有人类展示值时先 `find-records`，再按返回路径 `load-context-pack`
- Ambiguity contract: 多结果必须交给 Domain Skill 消歧
- Fallback contract: 缺少 lookup 声明或 Runtime 不可用时，Domain Skill 原流程继续

- [ ] **Step 1: 写入 Core Skill 契约失败测试**

在 `tests/test_skill_package.py` 的 query 测试增加：

```python
assert "find-records" in text
assert "multiple_matches" in text
assert "never infer identity from graph output" in text.lower()
assert "record lookup is not declared" in text.lower()
```

- [ ] **Step 2: 更新通用 Query 流程**

在 `skills/llm-wiki-core/llm-wiki-query/SKILL.md` 的 target resolution 后加入：

```markdown
When the request identifies a record by a human-facing scalar instead of an
authorized path or stable ID, inspect the active Domain Profile declaration and
call `find-records` before `load-context-pack`.

- `found`: narrow `load-context-pack` to the returned path.
- `multiple_matches`: return the allowlisted choices to the Domain Skill for one
  short disambiguation question; never select a record automatically.
- `not_found`: let the Domain Skill check its ordinary user-provided inputs
  before claiming the record is absent.
- `record lookup is not declared`: continue the Domain Skill's documented
  fallback without filesystem search.

Never infer identity from Graph output, filenames, directory names, Markdown
body text, or approximate matches.
```

- [ ] **Step 3: 更新 HR 示例 Profile**

在 `examples/hr/llm-wiki-profile.yml` 的 `read_rules` 中增加：

```yaml
  record_lookup:
    candidate_profile:
      identity_field: candidate_id
      display_field: display_name
      match_fields: [display_name, aliases]
      return_fields:
        - candidate_id
        - display_name
        - aliases
        - current_resume_version_id
      max_results: 20
```

该文件只是 Domain 示例；Runtime 单元测试仍不得使用 HR 标识。

- [ ] **Step 4: 更新 README CLI 清单**

在中英文 README 的读取命令中加入 `find-records`，说明它只执行声明式
frontmatter 精确匹配，不读取正文、不依赖 Graph。

- [ ] **Step 5: 写入端到端合成测试**

创建 `tests/test_record_lookup_end_to_end.py`，通过 CLI 完成以下流程：

```python
def test_lookup_then_context_load_without_graph(tmp_path):
    profile = write_project_profile(tmp_path)
    init_profile(tmp_path, profile, "local", "project-test")
    write_project_records(tmp_path)

    lookup = run_cli(
        "find-records",
        "--scope-root",
        str(tmp_path),
        "--record-type",
        "project_record",
        "--lookup-value-json",
        json.dumps("Atlas"),
        "--caller-domain",
        "projects",
        "--target-domain",
        "projects",
    )
    lookup_payload = json.loads(lookup.stdout)

    context = load_context_pack(
        tmp_path / ".llm-wiki",
        ["domains/projects/**"],
        [],
        30,
        4000,
        path_filters=[lookup_payload["matches"][0]["path"]],
    )

    assert lookup.returncode == 0
    assert lookup_payload["status"] == "found"
    assert context["items"][0]["path"] == lookup_payload["matches"][0]["path"]
    assert not (tmp_path / ".llm-wiki/.meta/graph").exists()
```

同文件增加 NUL 写入失败且目标不变化的 CLI 验收。

- [ ] **Step 6: 运行完整验证**

Run:

```powershell
python -m pytest -q
git diff --check
```

Expected: 全部测试 PASS，`git diff --check` 无输出。

- [ ] **Step 7: 执行仓库隐私扫描**

Run:

```powershell
$changed = git diff --name-only origin/main...HEAD
$changed | Select-String -Pattern '(^|/)(scopes?|candidates?|resumes?|sources/originals|\.llm-wiki)(/|$)','\.pdf$'
```

Expected: 无匹配。示例只包含虚构 ID，不包含本地 scope、简历或候选人档案。

- [ ] **Step 8: 提交文档和端到端验收**

```powershell
git add skills/llm-wiki-core/llm-wiki-query/SKILL.md tests/test_skill_package.py README.md README.zh-CN.md examples/hr/llm-wiki-profile.yml tests/test_record_lookup_end_to_end.py
git commit -m "docs: route human record queries through lookup"
```

- [ ] **Step 9: 快进推送 main**

```powershell
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git push origin HEAD:main
```

Expected: `main` 快进到当前 HEAD；若祖先检查失败则停止，不 rebase、不 force push。
