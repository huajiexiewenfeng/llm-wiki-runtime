# HR Skill 接入 llm-wiki-runtime 教程与测试步骤

本文说明 HR domain skill 如何接入 `llm-wiki-runtime`，以及如何在本地用 CLI 验证 HR 知识库的初始化、写入和读取流程。

## 一、接入目标

HR skill 接入后要做到三件事：

1. 首次运行时，发现 HR wiki 尚未启用，询问用户是否启用本地知识库。
2. 用户确认后，初始化 HR scope，并把有价值的数据写入 `.llm-wiki`。
3. 后续执行 HR 子技能时，先从 `.llm-wiki` 读取上下文，再结合本次输入完成筛选、报告或面试问题生成。

职责边界：

- `llm-wiki-runtime` 只负责安全读写、scope 发现、路径校验、锁、索引、日志和 context pack。
- HR skill 负责业务语义，比如候选人 ID、简历版本、JD、筛选批次、报告内容。
- HR profile 负责声明 HR 需要哪些目录、record type、write rule 和 read rule。

## 二、HR Skill 的推荐调用流程

### 1. 每次运行 HR 子技能前先 resolve

HR skill 先调用：

```powershell
llm-wiki resolve-config --cwd <当前工作目录> --profile hr
```

根据返回结果决定行为：

| status | HR skill 行为 |
| --- | --- |
| `enabled` | 读取 context pack，并在产出有价值数据后写入 wiki |
| `missing_config` | 首次询问用户是否启用 HR 本地知识库 |
| `disabled` | 不再打扰用户，按原 markdown/临时文件流程运行 |
| `profile_mismatch` | 当前目录属于其他 domain，降级运行 |
| `invalid_config` / `io_error` | 降级运行，并提示 wiki backend 未使用 |

首次询问建议用一句白话：

```text
是否启用 HR 本地知识库？启用后会把候选人档案、简历解析结果、筛选批次和报告保存到本机 .llm-wiki，方便后续复用。
```

### 2. 用户确认启用时初始化 HR scope

HR 默认使用 home scope：

```text
<LLM_WIKI_HOME>/scopes/hr-default/.llm-wiki
```

确认后，HR skill 调用：

```powershell
llm-wiki init-home --home <LLM_WIKI_HOME>
llm-wiki init-profile --scope-root <LLM_WIKI_HOME>\scopes\hr-default --profile-path <hr-profile.yml> --storage-mode home --scope-id hr-default
```

### 3. 用户拒绝启用时记录 decline

如果用户拒绝，HR skill 调用：

```powershell
llm-wiki init-profile --decline --profile hr --storage-mode home --scope-root <当前工作目录>
```

这会把 HR 的拒绝记录写到 runtime user config，之后从其他目录运行 HR skill 也不会反复询问。

### 4. 写入有价值数据

推荐写入时机：

- 原始简历：用 `copy-source` 复制到 `sources/originals/hr/...` 并登记 `source_id`。
- 候选人长期档案：用 `write-record` 写入 `candidate_profile`。
- 筛选报告、排名、面试计划：根据 HR profile 增加对应 record type 后用 `write-record` 写入。
- 过程日志：用 `append-log` 追加到 `logs/...`。

### 5. 读取上下文

HR 子技能调用 LLM 前，先调用：

```powershell
llm-wiki load-context-pack --wiki-root <wiki_root> --include-json "[...]" --exclude-json "[...]"
```

然后把返回的 `items[].content` 拼入 prompt。注意：

- 不要把 `sources/originals/**` 原始简历默认塞进上下文。
- 不要读取 `.meta/**`。
- 面向某个候选人或某个筛选批次时，HR skill 应传更窄的 include/filter，避免把整个人才库都塞进去。

## 三、本地测试步骤

下面步骤不会污染真实用户目录。所有数据都写到 `C:\tmp\llm-wiki-hr-demo`。

### 0. 准备变量

在 PowerShell 中执行：

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

### 1. 验证首次运行返回 missing_config

```powershell
& $PY -m llm_wiki_runtime.cli resolve-config --cwd "$DEMO\work" --profile hr
```

预期：

- 输出 JSON 中 `status` 为 `missing_config`。
- 退出码为 `1`，这是 fallback 状态，不是异常。

### 2. 初始化 runtime home 和 HR profile

```powershell
& $PY -m llm_wiki_runtime.cli init-home --home "$DEMO\home"

& $PY -m llm_wiki_runtime.cli init-profile `
  --scope-root "$DEMO\home\scopes\hr-default" `
  --profile-path "$PROFILE" `
  --storage-mode home `
  --scope-id hr-default
```

预期文件：

```text
C:\tmp\llm-wiki-hr-demo\runtime-config.yml
C:\tmp\llm-wiki-hr-demo\home\scopes\hr-default\.llm-wiki.yml
C:\tmp\llm-wiki-hr-demo\home\scopes\hr-default\.llm-wiki\
```

### 3. 再次 resolve，应返回 enabled

```powershell
& $PY -m llm_wiki_runtime.cli resolve-config --cwd "$DEMO\work" --profile hr
```

预期：

- `status` 为 `enabled`。
- `wiki_root` 指向 `$DEMO\home\scopes\hr-default\.llm-wiki`。

### 4. 准备一份模拟简历并登记 source

```powershell
$SCOPE = "$DEMO\home\scopes\hr-default"
$WIKI = "$SCOPE\.llm-wiki"
$RESUME = "$DEMO\zhang-san-resume.txt"

@"
张三
Java 后端工程师
Spring Boot / MySQL / Docker
"@ | Set-Content -Path $RESUME -Encoding UTF8

$sourcePayload = & $PY -m llm_wiki_runtime.cli copy-source `
  --wiki-root "$WIKI" `
  --source "$RESUME" `
  --logical-path "sources/originals/hr/resumes/zhang-san/resume.txt" `
  --source-type resume_text

$source = $sourcePayload | ConvertFrom-Json
$sourceId = $source.source_id
$sourceId
```

预期：

- 输出一个 `src-...` 格式的 `source_id`。
- `$WIKI\sources\registry.json` 中出现该 source。

### 5. 写入候选人档案

```powershell
$CANDIDATE = "$DEMO\candidate-profile.md"

@"
# 张三

- 候选人 ID：zhang-san
- 方向：Java 后端
- 标签：Spring Boot, Docker
- 当前状态：待筛选
"@ | Set-Content -Path $CANDIDATE -Encoding UTF8

$vars = (@{ candidate_id = "zhang-san" } | ConvertTo-Json -Compress).Replace('"','\"')
$refs = (@{ source_id = $sourceId; resume_version_id = "rv-001" } | ConvertTo-Json -Compress).Replace('"','\"')

& $PY -m llm_wiki_runtime.cli write-record `
  --scope-root "$SCOPE" `
  --profile-path "$PROFILE" `
  --record-type candidate_profile `
  --variables-json $vars `
  --refs-json $refs `
  --content-file "$CANDIDATE"
```

预期文件：

```text
$WIKI\domains\hr\candidates\zhang-san\profile.md
```

### 6. 读取 HR context pack

```powershell
& $PY -m llm_wiki_runtime.cli load-context-pack `
  --wiki-root "$WIKI" `
  --include-json ('["domains/hr/**","logs/**"]'.Replace('"','\"')) `
  --exclude-json ('["sources/originals/**",".meta/**"]'.Replace('"','\"')) `
  --max-files 30 `
  --max-chars-per-file 4000
```

预期：

- JSON 中包含 `domains/hr/candidates/zhang-san/profile.md`。
- 不包含 `.meta/**`。
- 不包含 `sources/originals/**`。

### 7. 验证拒绝启用不会覆盖 home config

```powershell
& $PY -m llm_wiki_runtime.cli init-profile --decline --profile learning --storage-mode home --scope-root "$DEMO\work"
& $PY -m llm_wiki_runtime.cli init-profile --decline --profile hr --storage-mode home --scope-root "$DEMO\work"
Get-Content "$DEMO\runtime-config.yml"
```

预期：

- `home:` 仍然存在。
- `profiles.learning.enabled: false` 存在。
- `profiles.hr.enabled: false` 存在。
- 后一次 decline 不会覆盖前一次 decline。

## 四、HR Skill 集成伪代码

```text
run_hr_skill(input):
  config = llm-wiki resolve-config --cwd cwd --profile hr

  if config.status == "missing_config":
    ask user: 是否启用 HR 本地知识库？
    if yes:
      llm-wiki init-home
      llm-wiki init-profile
      config = llm-wiki resolve-config --cwd cwd --profile hr
    else:
      llm-wiki init-profile --decline --profile hr --storage-mode home
      run original HR flow
      return

  if config.status != "enabled":
    run original HR flow
    return

  context = llm-wiki load-context-pack --wiki-root config.wiki_root
  result = run HR LLM flow with context + input

  for each valuable source:
    llm-wiki copy-source

  for each valuable record/report/log:
    llm-wiki write-record or append-log

  return result
```

## 五、验收标准

HR 接入完成后，至少满足：

1. 首次 HR skill 运行不会静默创建知识库，必须先确认。
2. 用户拒绝后不会反复询问。
3. 用户启用后，HR 数据写入 home scope 的 `hr-default`。
4. `copy-source` 会登记 `source_id`。
5. `candidate_profile` 写入前会校验 `source_id` 存在。
6. `load-context-pack` 默认不读取 `.meta/**` 和原始简历。
7. `llm-wiki-runtime` 出错时，HR skill 能降级为原始流程。
