# HR 接入 llm-wiki-runtime 教程

> 版本边界：本文记录的是源自 Runtime 0.1、由 Runtime 0.3 compatibility adapter 继续支持的 **Skill-only** 接入。它不包含 Workload Principal，也不是新 Harness 的实现模板。新 Harness 必须使用 `principal.yml`、v0.2 Mapping 和 `llm-wiki invoke`，Invocation 失败不得回退到本文中的 legacy 写命令。

本文说明 HR domain skill 如何接入 `llm-wiki-runtime`。目标不是让 HR 用户直接学习 CLI，而是让 HR skill 在内部自动使用 wiki backend，并在不可用时安静降级。

## V0.1 接入顺序

1. HR skill 启动时先走 `llm-wiki-core init` 语义，也就是调用 `llm-wiki resolve-config --profile hr`。
2. 如果返回 `missing_config`，HR skill 用一句话询问是否启用本地知识库。
3. 用户确认后，runtime 初始化 HR profile，并创建 `.llm-wiki/.meta/profile.yml` 快照。
4. 简历原件通过 `copy-source` 进入 `sources/originals/hr/**`。
5. 候选人长期档案通过 `write-record candidate_profile` 写入。
6. 筛选报告、排名、面试计划等输出通过 `register-artifact` 或后续 profile 扩展进入 wiki。
7. 后续每次 HR 子技能执行前，先 `load-context-pack` 读取 HR primary context，再结合本次输入生成答案。

## 首次确认文案

HR 数据敏感，首次启用不能静默创建。建议使用这一句：

```text
是否启用 HR 本地知识库？启用后会把候选人档案、简历解析结果、筛选批次和报告保存到本机 .llm-wiki，方便后续复用；原始简历默认不进入上下文。
```

用户拒绝时，HR skill 应调用：

```powershell
llm-wiki init-profile --decline --profile hr --storage-mode home --scope-root <当前工作目录>
```

拒绝会写入 runtime 用户配置，后续不会反复打扰。

## 默认读写边界

HR 默认策略：

- HR 是敏感 domain，`readable_by` 默认为空，不允许其他 domain 跨域读取。
- HR 可以把 AI Radar 作为 supporting domain，但 AI Radar 必须按 `data_only` 处理。
- `sources/originals/**` 不默认进入 context pack。
- `.meta/**` 不进入 context pack。
- 面向某个候选人或某个筛选批次时，HR skill 应传更窄的 `--path-json` 或 `--glob-json`。

## 测试步骤

以下步骤写入 `C:\tmp\llm-wiki-hr-demo`，不会污染真实目录。

```powershell
$PY = "C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$REPO = "D:\tmp\github\llm-wiki-runtime"
$DEMO = "C:\tmp\llm-wiki-hr-demo"
$PROFILE = "$REPO\examples\hr\llm-wiki-profile.yml"
$env:LLM_WIKI_RUNTIME_CONFIG = "$DEMO\runtime-config.yml"
$env:LLM_WIKI_HOME = "$DEMO\home"

Remove-Item -LiteralPath $DEMO -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$DEMO\work" | Out-Null
Set-Location $REPO
```

首次 resolve 应返回 `missing_config`：

```powershell
& $PY -m llm_wiki_runtime.cli resolve-config --cwd "$DEMO\work" --profile hr
```

初始化 HR profile：

```powershell
& $PY -m llm_wiki_runtime.cli init-home --home "$DEMO\home"
& $PY -m llm_wiki_runtime.cli init-profile `
  --scope-root "$DEMO\home\scopes\hr-default" `
  --profile-path "$PROFILE" `
  --storage-mode home `
  --scope-id hr-default
```

写入一个候选人档案：

```powershell
$SCOPE = "$DEMO\home\scopes\hr-default"
$WIKI = "$SCOPE\.llm-wiki"
$RESUME = "$DEMO\zhang-san-resume.txt"
"张三`nJava 后端工程师，Spring Boot / MySQL / Docker" | Set-Content -Path $RESUME -Encoding UTF8

$sourcePayload = & $PY -m llm_wiki_runtime.cli copy-source `
  --wiki-root "$WIKI" `
  --source "$RESUME" `
  --logical-path "sources/originals/hr/resumes/zhang-san/resume.txt" `
  --source-type resume_text
$sourceId = ($sourcePayload | ConvertFrom-Json).source_id

$CANDIDATE = "$DEMO\candidate-profile.md"
@"
---
record_type: candidate_profile
candidate_id: zhang-san
display_name: "张三"
age: "30岁"
years_experience: "7年"
education_level: "本科"
summary: "30岁 · 7年 · 本科 · Java · Spring Boot"
tags: ["Java", "Spring Boot", "Docker"]
---

# 候选人档案：张三

- 候选人 ID：zhang-san
- 方向：Java 后端
"@ | Set-Content -Path $CANDIDATE -Encoding UTF8

$vars = (@{ candidate_id = "zhang-san" } | ConvertTo-Json -Compress).Replace('"','\"')
$refs = (@{ source_id = $sourceId; resume_version_id = "rv-001" } | ConvertTo-Json -Compress).Replace('"','\"')

& $PY -m llm_wiki_runtime.cli write-record `
  --scope-root "$SCOPE" `
  --record-type candidate_profile `
  --variables-json $vars `
  --refs-json $refs `
  --content-file "$CANDIDATE"
```

读取 HR context pack：

```powershell
& $PY -m llm_wiki_runtime.cli load-context-pack `
  --wiki-root "$WIKI" `
  --include-json ('["domains/hr/**","logs/**"]'.Replace('"','\"')) `
  --exclude-json ('["sources/originals/**",".meta/**"]'.Replace('"','\"')) `
  --target-domain hr `
  --caller-domain hr
```

验收要点：

- 返回里包含 `domains/hr/candidates/zhang-san/profile.md`。
- 返回里不包含 `.meta/**`。
- 返回里不包含 `sources/originals/**`。
- `context_refs` 和每个 item 的 `checksum` 存在。
- runtime 出错时，HR skill 继续原有流程，并提示本次没有使用 wiki backend。
- `candidate_profile` frontmatter 包含 `display_name`；可确认时同时写入 `age`、`years_experience`、`education_level`、`summary` 和 `tags`，供离线图谱按白名单展示。
