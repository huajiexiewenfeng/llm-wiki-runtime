# HR Domain 记录检索接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已安装 HR Skill 中现有的 LLM Wiki 接入契约安全恢复到 `role-copilot-skills` 源码仓库，再接入 `find-records`、候选人消歧和 PDF 控制字符清理。

**Architecture:** HR Domain Profile 声明 `candidate_profile` 的身份与别名语义，共享 HR integration reference 定义候选人解析顺序，三个子 Skill 继续只负责各自业务。Runtime 可用时按姓名或别名先执行 `find-records`，再用精确路径加载上下文；Runtime 不可用时保持原始简历/JD 输入流程。

**Tech Stack:** Markdown Skills、SCP v0.1、Domain Profile YAML、Python 3.10+、`unittest`、`pypdf`、`llm-wiki-runtime` CLI。

## Global Constraints

- HR Skill 不读取 `graph.json`，不遍历候选人目录，不运行 `rg` 搜索候选人，不依赖文件名猜身份。
- `candidate_id` 是稳定身份；`display_name` 和已确认的 `aliases` 只用于精确解析。
- 多结果必须询问一次消歧问题，绝不自动选人。
- 无结果时先检查用户本次提供或已配置的简历输入，再说明 Wiki 中未找到。
- Runtime 缺失、禁用或异常时，HR 原业务能力必须继续。
- PDF 提取只删除 C0 中除 TAB/LF/CR 外的控制字符和 DEL，并在元数据中记录删除数量。
- 源码仓库、测试和提交不得包含真实候选人姓名、简历、档案、联系方式或私有 scope 输出。
- 当前 `D:\tmp\github\role-copilot-skills` 主目录存在其他未提交改动，实施不得修改、暂存或清理这些改动。
- 不创建新的远程开发分支；使用干净 detached worktree，验证后 fast-forward 推送 `HEAD:main`。

---

### Task 1: 建立干净源码工作区并恢复现有 HR LLM Wiki 契约

**Files:**
- Create worktree: `C:\Users\admin\Documents\New project 2\tmp\role-copilot-skills-hr-lookup`
- Create: `hr-agent-copilot/llm-wiki-profile.yml`
- Create: `hr-agent-copilot/graph-adapter.yml`
- Create: `hr-agent-copilot/ingest-mapping.yml`
- Create: `hr-agent-copilot/references/llm-wiki-integration.md`
- Create: `hr-agent-copilot/references/llm-wiki-ingest.md`
- Create: `hr-agent-copilot/tests/test_llm_wiki_integration_contract.py`
- Create: `hr-agent-copilot/hr-resume-screening-copilot/scp.yml`
- Create: `hr-agent-copilot/hr-candidate-detail-report-copilot/scp.yml`
- Create: `hr-agent-copilot/hr-interview-question-generator-copilot/scp.yml`
- Modify: `hr-agent-copilot/README.md`
- Modify: `hr-agent-copilot/README.zh.md`
- Modify: `hr-agent-copilot/hr-resume-screening-copilot/SKILL.md`
- Modify: `hr-agent-copilot/hr-candidate-detail-report-copilot/SKILL.md`
- Modify: `hr-agent-copilot/hr-interview-question-generator-copilot/SKILL.md`

**Interfaces:**
- Consumes: 已安装包 `C:\Users\admin\.codex-clean-20260710\skills\hr-agent-copilot`
- Produces: 可审计、可重新安装的 HR LLM Wiki 源码契约
- Preserves: `D:\tmp\github\role-copilot-skills` 中现有用户改动

- [ ] **Step 1: 创建 detached worktree，不创建新分支**

Run:

```powershell
git -C "D:\tmp\github\role-copilot-skills" fetch origin main
git -C "D:\tmp\github\role-copilot-skills" worktree add --detach `
  "C:\Users\admin\Documents\New project 2\tmp\role-copilot-skills-hr-lookup" `
  origin/main
```

Expected: 新 worktree 为 detached HEAD；原主目录的 staged、modified 和 untracked
文件保持不变。

- [ ] **Step 2: 生成允许同步的文件清单**

在 worktree 外的临时目录保存以下清单，不能使用 `Copy-Item -Recurse`：

```powershell
$allowed = @(
  "llm-wiki-profile.yml",
  "graph-adapter.yml",
  "ingest-mapping.yml",
  "references/llm-wiki-integration.md",
  "references/llm-wiki-ingest.md",
  "hr-resume-screening-copilot/scp.yml",
  "hr-candidate-detail-report-copilot/scp.yml",
  "hr-interview-question-generator-copilot/scp.yml"
)
```

逐个读取已安装文件并通过 `apply_patch` 写入源码。不得复制安装目录中的缓存、
运行输出、候选人文件或绝对路径。

- [ ] **Step 3: 将三个子 Skill 接回共享契约**

每个子 Skill 的 `## Optional LLM Wiki Augmentation` 必须包含：

```markdown
This skill declares its memory contract in `scp.yml`. Before the main business
workflow, read `../references/llm-wiki-integration.md`, run the
`resolve-config` preflight, and apply the declared query flow when HR memory is
enabled. If any runtime step fails, follow the shared fallback contract and
complete the original workflow.
```

筛选 Skill 保留“只问材料、不要提前读取简历”的 preparation-only gate，不允许
LLM Wiki preflight 绕过该 gate。

- [ ] **Step 4: 增加源码级契约测试**

创建 `hr-agent-copilot/tests/test_llm_wiki_integration_contract.py`，至少包含：

```python
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CHILDREN = (
    "hr-resume-screening-copilot",
    "hr-candidate-detail-report-copilot",
    "hr-interview-question-generator-copilot",
)


class HrLlmWikiIntegrationContractTest(unittest.TestCase):
    def test_profile_and_shared_contract_are_source_controlled(self):
        for relative in (
            "llm-wiki-profile.yml",
            "graph-adapter.yml",
            "ingest-mapping.yml",
            "references/llm-wiki-integration.md",
            "references/llm-wiki-ingest.md",
        ):
            self.assertTrue((PACKAGE_ROOT / relative).is_file(), relative)

    def test_each_child_has_scp_and_runtime_fallback(self):
        for child in CHILDREN:
            root = PACKAGE_ROOT / child
            text = (root / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue((root / "scp.yml").is_file())
            self.assertIn("../references/llm-wiki-integration.md", text)
            self.assertIn("resolve-config", text)
            self.assertIn("fallback", text.lower())

    def test_original_sources_and_meta_are_excluded(self):
        profile = (PACKAGE_ROOT / "llm-wiki-profile.yml").read_text(encoding="utf-8")
        self.assertIn("exclude: [sources/originals/**, .meta/**]", profile)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: 运行恢复后的契约测试和隐私路径扫描**

Run:

```powershell
python -m unittest discover -s hr-agent-copilot/tests -p "test_*.py" -v
git diff --check
$changed = git status --short
$changed | Select-String -Pattern 'candidate-[0-9a-f]{8,}','\.pdf$','(^|/)\.llm-wiki/'
```

Expected: 测试 PASS，diff check 无输出，隐私路径扫描无匹配。

- [ ] **Step 6: 提交源码契约恢复**

```powershell
git add hr-agent-copilot
git commit -m "feat(hr): restore llm wiki integration source"
```

---

### Task 2: 声明候选人检索并定义消歧流程

**Files:**
- Modify: `hr-agent-copilot/llm-wiki-profile.yml`
- Modify: `hr-agent-copilot/references/llm-wiki-integration.md`
- Modify: `hr-agent-copilot/tests/test_llm_wiki_integration_contract.py`
- Modify: `hr-agent-copilot/hr-candidate-detail-report-copilot/SKILL.md`
- Modify: `hr-agent-copilot/hr-interview-question-generator-copilot/SKILL.md`

**Interfaces:**
- Consumes: Runtime `find-records`
- Produces: HR candidate resolution contract
- Match fields: `display_name`、`aliases`
- Return fields: `candidate_id`、`display_name`、`aliases`、`current_resume_version_id`

- [ ] **Step 1: 写入候选人解析契约的失败测试**

在 integration contract 测试中增加：

```python
def test_candidate_lookup_is_declared_with_minimal_return_fields(self):
    profile = (PACKAGE_ROOT / "llm-wiki-profile.yml").read_text(encoding="utf-8")
    for fragment in (
        "record_lookup:",
        "candidate_profile:",
        "identity_field: candidate_id",
        "display_field: display_name",
        "match_fields: [display_name, aliases]",
        "current_resume_version_id",
        "max_results: 20",
    ):
        self.assertIn(fragment, profile)


def test_shared_query_contract_uses_lookup_without_graph_or_shell_search(self):
    text = (
        PACKAGE_ROOT / "references/llm-wiki-integration.md"
    ).read_text(encoding="utf-8")
    self.assertIn("find-records", text)
    self.assertIn("multiple_matches", text)
    self.assertIn("not_found", text)
    self.assertIn("candidate_id", text)
    self.assertIn("aliases", text)
    self.assertNotIn("graph.json", text)
    self.assertNotIn("run `rg`", text)
```

- [ ] **Step 2: 运行契约测试并确认失败**

Run:

```powershell
python -m unittest hr-agent-copilot.tests.test_llm_wiki_integration_contract -v
```

Expected: FAIL，因为 Profile 和共享 reference 尚未包含 `find-records`。

- [ ] **Step 3: 在 HR Profile 声明 lookup**

在 `read_rules.context_pack` 后增加：

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

- [ ] **Step 4: 在共享 reference 中定义候选人解析顺序**

将 `## Query Before Work` 扩展为：

```markdown
### Candidate Resolution

1. If a trusted `candidate_id` is already known, narrow `load-context-pack` to
   that exact candidate path.
2. If only a candidate name or confirmed alias is available, call
   `find-records` for `candidate_profile` with `caller_domain=hr` and
   `target_domain=hr`.
3. On `found`, load only the returned path.
4. On `multiple_matches`, ask one short disambiguation question using only the
   returned non-contact fields. Never select a candidate automatically.
5. On `not_found`, check the resume files or text supplied for this request
   before saying that candidate material is unavailable.
6. On a missing lookup declaration, runtime failure, or disabled Wiki, continue
   with the original HR inputs and emit the normal one-line fallback notice.

Never infer candidate identity from Graph output, filenames, directory names,
company names, Markdown body search, or approximate string matching. Write a
confirmed alternate name to the Domain-owned `aliases` field only through the
normal candidate profile update flow.
```

- [ ] **Step 5: 强化候选人详情与面试题 Skill**

在两个 Skill 的工作流开始处增加：

```markdown
When the user names a candidate without supplying the resume again, apply the
shared Candidate Resolution flow before concluding that the resume is missing.
Do not search Graph output or candidate directories as a fallback.
```

- [ ] **Step 6: 运行契约测试并提交**

Run:

```powershell
python -m unittest discover -s hr-agent-copilot/tests -p "test_*.py" -v
git diff --check
```

Expected: PASS。

Commit:

```powershell
git add hr-agent-copilot/llm-wiki-profile.yml hr-agent-copilot/references/llm-wiki-integration.md hr-agent-copilot/tests/test_llm_wiki_integration_contract.py hr-agent-copilot/hr-candidate-detail-report-copilot/SKILL.md hr-agent-copilot/hr-interview-question-generator-copilot/SKILL.md
git commit -m "feat(hr): resolve candidate names through runtime"
```

---

### Task 3: 清理 PDF 提取产生的非法控制字符

**Files:**
- Modify: `hr-agent-copilot/scripts/extract_resumes.py`
- Create: `hr-agent-copilot/tests/test_extract_resumes.py`

**Interfaces:**
- Produces: `remove_forbidden_controls(text: str) -> tuple[str, int]`
- Adds metadata: `removed_control_characters: int`
- Preserves: 普通 Unicode、TAB、LF、CR 和原有页分隔结构

- [ ] **Step 1: 写入文本清理失败测试**

创建 `hr-agent-copilot/tests/test_extract_resumes.py`：

```python
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_resumes.py"
SPEC = importlib.util.spec_from_file_location("extract_resumes", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ResumeTextSanitizationTest(unittest.TestCase):
    def test_removes_only_forbidden_controls(self):
        cleaned, count = MODULE.remove_forbidden_controls(
            "姓名\tJava\n项目\r经历\x00\x01\x0b\x7f完成"
        )

        self.assertEqual(cleaned, "姓名\tJava\n项目\r经历完成")
        self.assertEqual(count, 4)

    def test_clean_text_is_unchanged(self):
        text = "中文 English\n第二行"
        self.assertEqual(MODULE.remove_forbidden_controls(text), (text, 0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试并确认 helper 不存在**

Run:

```powershell
python -m unittest hr-agent-copilot.tests.test_extract_resumes -v
```

Expected: FAIL with missing `remove_forbidden_controls`.

- [ ] **Step 3: 实现确定性清理函数**

在 `extract_resumes.py` 增加：

```python
_ALLOWED_C0 = {"\t", "\n", "\r"}


def remove_forbidden_controls(text: str) -> tuple[str, int]:
    output: list[str] = []
    removed = 0
    for character in text:
        codepoint = ord(character)
        if (codepoint < 0x20 and character not in _ALLOWED_C0) or codepoint == 0x7F:
            removed += 1
            continue
        output.append(character)
    return "".join(output), removed
```

在 `ResumeExtract` 增加：

```python
removed_control_characters: int
```

把 `extract_pdf_text` 的返回类型改为：

```python
def extract_pdf_text(path: Path) -> tuple[str, int, list[str], int]:
```

在完成 page 拼接后执行：

```python
text = "\n".join(parts).strip()
text, removed_controls = remove_forbidden_controls(text)
if removed_controls:
    warnings.append(
        f"Removed {removed_controls} forbidden control character(s) from extracted text."
    )
if not text:
    warnings.append("No extractable text. The PDF may be scanned or image-based.")
return text, len(reader.pages), warnings, removed_controls
```

调用处接收 `removed_controls`，并写入 `ResumeExtract`。

- [ ] **Step 4: 运行脚本单元测试与契约测试**

Run:

```powershell
python -m unittest discover -s hr-agent-copilot/tests -p "test_*.py" -v
```

Expected: PASS，测试不需要读取真实 PDF。

- [ ] **Step 5: 提交提取清理**

```powershell
git add hr-agent-copilot/scripts/extract_resumes.py hr-agent-copilot/tests/test_extract_resumes.py
git commit -m "fix(hr): sanitize extracted resume controls"
```

---

### Task 4: 使用合成 scope 做跨仓库验收

**Files:**
- Create: `hr-agent-copilot/tests/test_candidate_lookup_flow.py`
- No private scope files are created in the repository

**Interfaces:**
- Consumes: 已实现的 `llm-wiki find-records`
- Verifies: HR Profile 可被 Runtime 解析，0/1/N 结果和 fallback 契约一致

- [ ] **Step 1: 创建完全合成的候选人 scope**

测试通过临时目录复制 HR Profile，写入三个虚构候选人记录：

```python
def candidate_record(candidate_id: str, display_name: str, aliases: list[str]) -> str:
    alias_text = ", ".join(f'"{item}"' for item in aliases)
    return "\n".join(
        [
            "---",
            "record_type: candidate_profile",
            f"candidate_id: {candidate_id}",
            f'display_name: "{display_name}"',
            f"aliases: [{alias_text}]",
            "current_resume_version_id: resume-example-001",
            "---",
            "# Synthetic profile",
            "",
        ]
    )
```

测试 ID 使用 `candidate-example-001` 等虚构值，不使用真实姓名。

- [ ] **Step 2: 覆盖 found、multiple 和 not_found**

通过 `subprocess.run` 调用：

```python
command = [
    sys.executable,
    "-m",
    "llm_wiki_runtime.cli",
    "find-records",
    "--scope-root",
    str(scope),
    "--record-type",
    "candidate_profile",
    "--lookup-value-json",
    json.dumps("Example Candidate"),
    "--caller-domain",
    "hr",
    "--target-domain",
    "hr",
]
result = subprocess.run(
    command,
    text=True,
    capture_output=True,
    check=False,
)
```

断言：

```python
self.assertEqual(found["status"], "found")
self.assertEqual(multiple["status"], "multiple_matches")
self.assertEqual(missing["status"], "not_found")
self.assertNotIn("phone", found["matches"][0]["fields"])
self.assertFalse((scope / ".llm-wiki/.meta/graph").exists())
```

- [ ] **Step 3: 运行跨仓库验收**

确保当前 Python 环境安装的是本次 Runtime 源码，然后执行：

```powershell
python -m unittest discover -s hr-agent-copilot/tests -p "test_*.py" -v
git diff --check
```

Expected: 全部 PASS。

- [ ] **Step 4: 提交验收测试**

```powershell
git add hr-agent-copilot/tests/test_candidate_lookup_flow.py
git commit -m "test(hr): verify candidate lookup contract"
```

---

### Task 5: 推送源码、重新安装 Skill 并清理本地旧记录

**Files:**
- Source repository: no private data files
- Installed target: `C:\Users\admin\.codex-clean-20260710\skills\hr-agent-copilot`
- Private scope: `C:\Users\admin\Documents\LLM Wiki\scopes\hr-default`

**Interfaces:**
- Produces: GitHub `main` 上可复现的 HR Skill 源码
- Produces: 本机重新安装的 HR Skill
- Produces: 本地旧候选人记录控制字符清理结果

- [ ] **Step 1: 推送前执行隐私和 Git 检查**

Run:

```powershell
git status --short
git diff --check origin/main...HEAD
$changed = git diff --name-only origin/main...HEAD
$changed | Select-String -Pattern 'candidate-[0-9a-f]{8,}','\.pdf$','(^|/)\.llm-wiki/','scopes/hr-default'
```

Expected: 工作区干净，diff check 无输出，敏感路径无匹配。

- [ ] **Step 2: 仅在可以快进时推送 main**

Run:

```powershell
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git push origin HEAD:main
```

Expected: `main` 快进；祖先检查失败时停止，不 force push，也不修改原始脏 worktree。

- [ ] **Step 3: 从已推送源码重新安装 HR Skill**

先列出本地包可发现的 Skill：

```powershell
npx skills add `
  "C:\Users\admin\Documents\New project 2\tmp\role-copilot-skills-hr-lookup" `
  --list
```

确认包含 `hr-agent-copilot` 后安装：

```powershell
npx skills add `
  "C:\Users\admin\Documents\New project 2\tmp\role-copilot-skills-hr-lookup" `
  --skill hr-agent-copilot `
  --global `
  --agent codex `
  --yes
```

安装后比较源码与安装目标的 Profile、reference、脚本和契约测试 checksum。

- [ ] **Step 4: 在私有 scope 外创建备份**

备份目录必须位于源码仓库之外：

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "C:\Users\admin\Documents\LLM Wiki Backups\hr-default-$stamp"
Copy-Item `
  "C:\Users\admin\Documents\LLM Wiki\scopes\hr-default\.llm-wiki\domains\hr" `
  $backup `
  -Recurse
```

Expected: 备份成功，Git 仓库没有新增文件。

- [ ] **Step 5: 只扫描非法控制字符，不输出记录正文**

使用一次性本地脚本统计受影响文件路径和字符数量，输出中不得包含正文、
frontmatter 值、姓名或联系方式。允许字符是 TAB、LF、CR，其余 C0 和 DEL
计入问题。

Expected: 得到受影响文件数和每个 scope 相对路径，不生成仓库文件。

- [ ] **Step 6: 通过 Runtime 写入清理后的记录**

对每个受影响的 `candidate_profile`：

1. 在 `%TEMP%` 生成仅删除禁止控制字符的临时 Markdown。
2. 从记录相对路径取得 `candidate_id`。
3. 从 frontmatter 读取 `source_ids` 的第一项和 `current_resume_version_id`。
4. 将这些已验证值放入本地 PowerShell 变量，并调用 `llm-wiki write-record`：

```powershell
$variablesJson = @{
  candidate_id = $candidateId
} | ConvertTo-Json -Compress
$refsJson = @{
  source_id = $sourceId
  resume_version_id = $resumeVersionId
} | ConvertTo-Json -Compress

llm-wiki write-record `
  --scope-root "C:\Users\admin\Documents\LLM Wiki\scopes\hr-default" `
  --record-type candidate_profile `
  --variables-json $variablesJson `
  --refs-json $refsJson `
  --content-file $temporarySanitizedFile
```

实际值只存在命令内存和本地临时文件，不写入日志、计划或仓库。若字段缺失，
停止该记录迁移并保留原文件，不能猜测引用。

- [ ] **Step 7: 验证本地查询不依赖 Graph**

临时重命名 `.llm-wiki/.meta/graph`，用一个已确认姓名执行 `find-records`，
确认 `found` 后立即恢复 Graph 目录。终端输出不得保存到源码仓库。

然后验证：

- 所有候选人记录不再包含禁止控制字符；
- `.meta/change-log.jsonl` 记录正常 checksum 更新；
- Graph 缺失期间查询仍成功；
- 原始简历和候选人数据未进入 Git；
- 原始脏 `role-copilot-skills` 主目录状态完全未变。
