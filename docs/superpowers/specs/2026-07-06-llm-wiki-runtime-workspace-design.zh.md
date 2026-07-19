# llm-wiki-runtime 工作空间设计

## 状态

这是将 `llm-wiki-runtime` 作为独立顶层 skill 工作空间引入 `role-copilot-skills` 的设计文档。

目标是把 `llm-wiki-runtime` 做成一个可复用的本地知识库运行时和 `.llm-wiki` 接入层，供不同领域 skill 使用。它不是 HR、DevOps、Project、Learning 或 AI Radar 的业务模块。

## 命名

公开 GitHub 项目名：

```text
llm-wiki-runtime
```

Skill 包目录：

```text
llm-wiki-runtime
```

面向用户的 CLI：

```text
llm-wiki
```

Python 入口文件：

```text
llm_wiki.py
```

内部实现仍然可以包含 core access layer，但公开项目名统一使用 `llm-wiki-runtime`。

## 仓库位置

`llm-wiki-runtime` 应作为顶层 skill 包创建：

```text
D:\tmp\github\role-copilot-skills\
  llm-wiki-runtime\
  hr-agent-copilot\
  devops-agent-copilot\
  project-agent-copilot\
```

这个位置表示 `llm-wiki-runtime` 是横向基础 skill，和各个领域 skill 组平级。

`project-agent-copilot` 不是 V0.1 的迁移目标。它已经有自己的 project-local wiki 生命周期，第一期应该把它作为经验来源，而不是第一批接入对象。

## V0.1 目标

1. 每个 domain skill 声明自己的 `llm-wiki-profile.yml`。
2. 所有可复用、有价值的领域数据，都写入对应 domain 的 `.llm-wiki`。
3. 每次 skill 执行前，都可以从 `.llm-wiki` 加载该 domain 的 context pack。
4. `llm-wiki-runtime` 不解释业务语义。
5. `llm-wiki-runtime` 负责安全接入、source registry、artifact registry、日志、checksum 和 fallback 状态。
6. 当 `llm-wiki-runtime` 不可用、被禁用或配置错误时，domain skill 保持原有输出行为。

## Runtime Home、Scope 和 Profile 模型

V0.1 分成两个层次：

```text
LLM Wiki Home
  runtime 级别的本地根目录，用于存放共享的 domain scopes。

Domain Wiki Scope
  一个具体的 HR、DevOps、Learning 或 AI Radar 知识库。
```

安装后或首次使用时，`llm-wiki-runtime` 应引导用户选择 `LLM_WIKI_HOME`。

如果用户不设置，使用平台默认路径：

```text
Windows: C:\Users\<user>\Documents\LLM Wiki
macOS:   ~/Documents/LLM Wiki
Linux:   ~/.local/share/llm-wiki-runtime
```

Runtime home 可以包含：

```text
LLM Wiki/
  config.yml
  scopes/
    hr-default/
      .llm-wiki/
    learning-default/
      .llm-wiki/
    ai-radar-default/
      .llm-wiki/
  logs/
```

Runtime config 也可以记录 profile 级别的拒绝状态，让 home-scope domain 从不同工作目录运行时不会反复询问：

```yaml
profiles:
  hr:
    storage_mode: home
    default_scope_id: hr-default
    enabled: false
    declined_at: 2026-07-06T10:30:00+08:00
```

`LLM_WIKI_HOME` 按以下顺序解析：

1. `LLM_WIKI_HOME` 环境变量。
2. runtime 用户配置。
3. 平台默认路径。

Runtime 用户配置位置：

```text
Windows: %APPDATA%\llm-wiki-runtime\config.yml
macOS:   ~/Library/Application Support/llm-wiki-runtime/config.yml
Linux:   ~/.config/llm-wiki-runtime/config.yml
```

V0.1 支持两种存储模式：

```text
local
  wiki_root = scope_root / storage

home
  wiki_root = LLM_WIKI_HOME / scopes / scope_id / .llm-wiki
```

Local scope config：

```yaml
llm_wiki:
  enabled: true
  storage_mode: local
  storage: .llm-wiki
  primary_profile: hr
```

Home scope config：

```yaml
llm_wiki:
  enabled: true
  storage_mode: home
  scope_id: hr-default
  primary_profile: hr
```

对于 home scope，scope config 位于：

```text
LLM_WIKI_HOME/scopes/{scope_id}/.llm-wiki.yml
```

wiki root 位于：

```text
LLM_WIKI_HOME/scopes/{scope_id}/.llm-wiki
```

各 domain 的默认存储策略：

```text
hr        -> home
devops    -> local
learning  -> home
ai-radar  -> home
```

`resolve-config` 按以下顺序发现 active scope：

1. 解析 `LLM_WIKI_HOME`。
2. 如果传入 `--scope <path>`，除非该路径配置了 `storage_mode: home`，否则把它作为 local scope root。
3. 否则从 `--cwd` 开始向上查找，直到找到 `.llm-wiki.yml`。
4. 如果找到 local config，根据其中的 `storage_mode` 解析 `wiki_root`。
5. 如果没有 local config，再检查 runtime 用户配置中是否有 profile 级别的禁用或拒绝记录。如果请求的 profile 已禁用，返回 `disabled`。
6. 如果没有 local config，但调用方传入 `--profile <id>` 且该 profile 有默认 home 策略，则只有在该 home scope 已经存在初始化后的 `.llm-wiki.yml` 时才使用它。
7. 如果默认 home scope 尚不存在，返回 `missing_config`，让 domain skill 触发首次启用确认。
8. 如果没有 config，也没有适用的默认 home 策略，返回 `missing_config`，并把 `scope_root` 设为 `--cwd`。

Runtime 用户配置中的 profile 级别拒绝只适用于默认 home 策略，不能禁用带有自己 `.llm-wiki.yml` 的显式 local scope。

`resolve-config` 不能静默创建 home scope。Home scope 只能在用户明确确认首次启用后，通过 `init-home` 和 `init-profile` 创建。

虽然 domain 路径使用 `domains/hr/...` 这样的前缀，但 V0.1 仍然把一个 scope 视为单 primary profile 工作区。这个前缀用于让路径更明确，并为未来多 profile 共存留空间。V0.1 不能让 HR 写入 DevOps scope，也不能让 DevOps 写入 HR scope。

同一个 `.llm-wiki` 中多 profile 共存延后处理。未来版本可以通过显式 `profiles:` 配置支持；但在 V0.1 中，`profile_mismatch` 表示当前目录已经属于另一个 primary profile，调用方必须降级。

## 第一批接入对象

第一批深度接入：

- `hr-agent-copilot`
- `devops-agent-copilot`

外部 skill 轻接入样例：

- `learning-companion-skills`
- `ai-radar-harness`

V0.1 暂不接入：

- `project-agent-copilot`

## 核心原则

```text
domain 负责说明；
core 负责接入。

domain 判断什么有价值；
core 负责可靠落库。

domain 负责业务语义；
core 负责文件系统和索引可信操作。
```

`llm-wiki-runtime` 可以增强 domain skill，但不能成为 domain skill 的单点故障。

## 职责边界

`llm-wiki-runtime` 负责：

- `init-home`
- `resolve-config`
- `init-profile`
- `copy-source`
- `write-record`
- `load-context-pack`
- `register-artifact`
- `append-log`
- 路径边界检查
- checksum 计算和记录
- source registry 写入
- artifact index 写入
- append-only log 写入
- active profile snapshot 写入和读取
- 确定性的 fallback 状态

Domain skill 负责：

- `llm-wiki-profile.yml`
- 判断哪些数据有价值
- 生成文件内容
- 生成业务 ID
- 解释读取到的上下文
- 判断上下文如何影响业务结论
- 面向用户的确认话术
- 业务报告和分析结论

Codex、Claude Code 等 agent shell 负责自然语言交互、skill 路由和结果展示。

## V0.1 CLI 范围

第一期公开 CLI 范围：

```text
init-home
resolve-config
init-profile
copy-source
write-record
load-context-pack
register-artifact
append-log
```

`init-home` 用于引导或记录 runtime 级别的 `LLM_WIKI_HOME`。Domain skill 可以在首次启用时调用它，但它也应该足够简单，方便开发者直接使用。

`safe-write` 可以作为内部能力存在，但 domain skill 应优先使用 `write-record`。`write-record` 根据当前 domain profile 解析路径、写入模式、必需变量、必需引用和 artifact 注册行为。

所有公开命令都通过 stdout 返回 JSON，并统一使用 exit code：

```text
0  成功
1  用户或配置导致的降级，具体 status 写在 JSON 中
2  校验错误，例如不安全路径、缺少变量、缺少引用
3  IO 或锁失败
4  未预期的内部错误
```

Fallback 状态通过 JSON 表达，而不是依赖 stderr 自由文本。例如：

```json
{
  "status": "disabled",
  "enabled": false,
  "scope_root": "D:/work/hr-pool",
  "wiki_root": null,
  "primary_profile": null,
  "fallback_mode": "markdown"
}
```

`resolve-config` 至少返回：

```json
{
  "status": "enabled",
  "enabled": true,
  "scope_root": "D:/work/hr-pool",
  "storage_mode": "home",
  "wiki_home": "C:/Users/alice/Documents/LLM Wiki",
  "wiki_root": "C:/Users/alice/Documents/LLM Wiki/scopes/hr-default/.llm-wiki",
  "scope_id": "hr-default",
  "primary_profile": "hr",
  "scope_type": "talent_pool",
  "privacy": "sensitive_local",
  "fallback_mode": "markdown"
}
```

`fallback_mode` 是给 domain skill 消费的建议字段，不由 `llm-wiki-runtime` 解释业务逻辑。

V0.1 取值：

```text
markdown
  继续原有 Markdown 报告或输出行为。

original_output
  继续 skill 原有的非 wiki 输出行为。

none
  没有可用降级路径，主要用于开发者直接调用 CLI 的场景。
```

HR V0.1 应使用 `markdown`。DevOps 可根据现有 skill 行为使用 `original_output` 或 `markdown`。

## 工作空间结构

第一期 `llm-wiki-runtime` 工作空间只包含通用接入层：

```text
llm-wiki-runtime/
  SKILL.md
  README.md

  bin/
    llm_wiki.py

  docs/
    contract.md
    cli.md
    profile-spec.md
    integration-guide.md
    fallback-behavior.md

  examples/
    hr/
      .llm-wiki.yml
      llm-wiki-profile.yml
    devops/
      llm-wiki-profile.yml
    learning/
      llm-wiki-profile.yml
    ai-radar/
      llm-wiki-profile.yml

  tests/
    fixtures/
      hr-profile/
      disabled-config/
      invalid-config/
    test_resolve_config.py
    test_write_record.py
    test_context_pack.py
```

`examples/` 下的 profile 只是示例。HR 的权威 profile 应该放在 HR skill 包里，例如：

```text
hr-agent-copilot/
  hr-resume-screening-copilot/
    llm-wiki-profile.yml
```

## Profile 契约

每个 domain skill 通过 `llm-wiki-profile.yml` 声明自己的 wiki 接入规则。

`init-profile` 初始化 scope 时，必须把传入的 active profile 快照到：

```text
.llm-wiki/.meta/profile.yml
```

后续 `write-record` 和 `load-context-pack` 默认读取 scope 内的 active profile snapshot，而不是重新依赖原 skill 包中的 `llm-wiki-profile.yml`。这样即使 skill 被移动、升级或卸载，已有 scope 仍然保留可解释的读写规则。若 snapshot 缺失或与 `.llm-wiki.yml` 中的 primary profile 不一致，命令应返回配置类 fallback status，而不是猜测读取规则。

V0.1 的 profile 只包含五个部分：

```yaml
profile:
layout:
write_rules:
read_rules:
artifacts:
```

### profile

```yaml
profile:
  id: hr
  version: v0.1
  display_name: HR Talent Pool
  scope_type: talent_pool
  privacy_default: sensitive_local
```

`profile.id` 是 domain ID，例如 `hr`、`devops`、`learning`、`ai-radar`。

### layout

```yaml
layout:
  directories:
    - domains/hr/candidates
    - domains/hr/resumes
    - domains/hr/jobs
    - domains/hr/screenings
    - sources/originals/hr
    - sources/extracts/hr
    - artifacts
    - logs
```

`llm-wiki-runtime` 只负责创建声明过的目录，不解释这些目录的业务含义。

### write_rules

```yaml
write_rules:
  records:
    candidate_profile:
      path: domains/hr/candidates/{candidate_id}/profile.md
      mode: update_allowed
      required_vars:
        - candidate_id
      required_refs:
        - source_id
        - resume_version_id
      register_artifact: false

    screening_report:
      path: domains/hr/screenings/{job_id}/{run_id}/report.md
      mode: create_only
      required_vars:
        - job_id
        - run_id
      required_refs:
        - job_id
        - candidate_ids
      register_artifact: true
      artifact_type: screening_report
```

支持三种写入模式：

```text
create_only
update_allowed
append_only
```

`create_only` 拒绝覆盖已有文件。`update_allowed` 允许受控替换。`append_only` 用于日志和只追加记录。

### read_rules

```yaml
read_rules:
  context_pack:
    include:
      - domains/hr/**
      - artifacts/**
      - logs/**
    exclude:
      - sources/originals/**
      - .meta/**
    max_files: 30
    max_chars_per_file: 4000
```

V0.1 的 context pack 是确定性读取，不依赖 embedding、向量搜索、语义排序或跨 domain 搜索。

Context pack 应返回文件路径、标题或 heading、受限长度的内容片段、checksum，以及 domain skill 判断业务时需要的元数据。

`.meta/**` 下的 core-managed metadata 默认从 context pack 排除，即使 profile include 了 `logs/**` 这类宽路径。未来可以提供显式 `--include-meta` 给维护命令使用，但业务 skill 默认不应消费这些元数据。

即使 domain profile 没有在 `layout.directories` 中声明，`llm-wiki-runtime` 也会在 `init-profile` 时创建 `.llm-wiki/.meta/`。

### artifacts

```yaml
artifacts:
  types:
    - screening_report
    - ranking
    - interview_plan
```

`llm-wiki-runtime` 应拒绝当前 profile 未声明的 artifact type。

## 安全和一致性规则

### 路径变量安全

`{candidate_id}`、`{run_id}`、`{image_id}` 这类路径变量是数据，不是可信路径。

在渲染路径模板前，`llm-wiki-runtime` 必须校验每个变量值：

- 拒绝空值
- 拒绝 `.` 和 `..`
- 拒绝 `/`、`\`、盘符前缀、冒号和路径分隔符
- 拒绝控制字符
- 拒绝超过配置长度的值，默认上限 128 字符
- V0.1 使用保守 slug 规则：`[A-Za-z0-9][A-Za-z0-9._-]*`

人类可读的显示名称可以留在 Markdown 内容中。路径 ID 必须由 domain skill 生成安全 slug，并由 `llm-wiki-runtime` 强制校验。

路径模板渲染后，`llm-wiki-runtime` 必须 normalize 最终路径，并确认最终路径仍然位于 `wiki_root` 内。

### 必需引用校验

`required_refs` 不能只检查“有没有传”。

V0.1 应校验 core 自己拥有的 registry 引用：

- `source_id` 必须存在于 `sources/registry.json`。
- `artifact_id` 必须存在于 `artifacts/index.json`。
- 当命令提供了足够信息时，`checksum` 必须和引用的 source 或内容匹配。

`candidate_ids`、`job_id`、`run_id` 这类 domain-owned 引用，V0.1 只校验类型和非空值。它们更深层的业务存在性由 domain skill 负责，除非未来 profile 明确声明某个引用可由 core 校验。

引用值可以是字符串，也可以是数组。未来 profile 可以声明引用类型；但 V0.1 至少要拒绝空字符串、空数组和非字符串数组元素。

### 原子写和锁

任何写入 `.llm-wiki` 的命令，在修改文件前都必须获得 scope 独占锁。

获取锁之前，`llm-wiki-runtime` 可以先创建 `.llm-wiki/.meta/` 目录。这个 bootstrap 目录创建是允许的，这样 `init-profile` 本身也能被同一套锁保护。

锁文件为：

```text
.llm-wiki/.meta/lock.json
```

锁文件至少包含：

```json
{
  "pid": 12345,
  "host": "machine-name",
  "command": "write-record",
  "acquired_at": "2026-07-06T10:30:00+08:00"
}
```

默认锁行为：

- 通过原子文件创建获取锁，等价于 `O_CREAT | O_EXCL`，避免两个进程同时抢锁成功。
- 最多等待 30 秒获取锁。
- 超时仍无法获取锁时，返回 exit code `3`。
- 锁超过 10 分钟视为 stale。
- 同一 host 上，如果记录的 PID 已不存在，可以回收 stale lock。
- 不同或未知 host 上，超过 stale 阈值的锁可以先重命名为 `.llm-wiki/.meta/lock.stale.{timestamp}.json`，再获取新锁。

锁保护以下操作：

- profile 初始化
- source registry 写入
- artifact index 写入
- append-only log
- `write-record`
- `copy-source`

JSON registry 和可替换 record 的写入必须是原子的：

```text
在同目录写临时文件
可用时执行 fsync
原子 rename/replace
```

Append-only log 应在同一把锁下写入；如果平台不能保证原子 append，则使用 temp-and-rename 策略。

### update_allowed 和 checksum

`update_allowed` 不等于无记录覆盖。

当 `write-record` 更新已有文件时，`llm-wiki-runtime` 必须记录：

- 旧 checksum
- 新 checksum
- 时间戳
- 命令名
- record type
- logical path
- domain skill 提供的 refs

V0.1 可以把这条 revision entry 存入 core 管理的 change log，例如：

```text
.llm-wiki/.meta/change-log.jsonl
```

当前文件可以被替换，但更新必须可审计。通过 CLI 写入的 `create_only` 文件仍然保持不可变。

### Context Pack 确定性

`load-context-pack` 必须是确定性的。

默认选择顺序：

1. 先应用调用方提供的显式 `--path` 或 `--glob` 过滤。
2. 再应用 profile 的 `read_rules.context_pack.include` 和 `exclude`。
3. 默认按路径升序排序。
4. 如果显式传入 `--order mtime_desc`，则按修改时间倒序，再按路径升序。
5. 排序后再应用 `max_files` 和 `max_chars_per_file`。

命令应支持调用方过滤：

```text
--path domains/hr/candidates/zhang-san/profile.md
--glob domains/hr/candidates/**
--record-type candidate_profile
--ref candidate_id=zhang-san
--policy data_only
```

过滤条件只能缩小 profile read rules 允许的范围，不能扩大到 active profile 之外。

Domain integration guide 应要求业务 skill 在用户意图明确时传入缩小范围的过滤条件，例如 candidate ID、job ID、release ID、topic ID 或日期范围。宽泛读取适合小 scope，但不应作为定向问题的默认方式。

当调用方传入 `--policy data_only` 时，`load-context-pack` 必须对输出内容执行确定性预处理：扫描最小风险词、标记 `sanitized`、输出 `risk_flags`，并在每个 context item 的 metadata 中保留生效的 `instruction_policy`。该策略只负责结构化隔离和标记，不承诺 LLM 绝对不受文本影响；调用方仍必须把这些内容放在 supporting context，并避免把它们当作指令执行。

### 隐私语义

`privacy_default` 是 domain 的默认值，用于 `init-profile`。

`llm-wiki-runtime` 会把解析后的隐私级别写入 `.llm-wiki.yml`。运行时 config 覆盖 profile 默认值。V0.1 中，privacy 只影响默认用户提示和 Git 建议，尤其是是否建议把 `.llm-wiki/` 加入忽略。它不是加密系统，也不是权限控制系统。

### 拒绝启用的持久化

当用户拒绝首次启用时，问题由 domain skill 询问，但 `llm-wiki-runtime` 应提供确定性的写入操作，创建最小 disabled config：

```yaml
llm_wiki:
  enabled: false
```

这样可以保证不同 domain 下“本 scope 不再询问”的行为一致。

对于 `local` storage domain，disabled config 写入 local scope root。

对于 `home` storage domain，拒绝记录写入该 profile 对应的 runtime 用户配置，而不是当前工作目录。这样 HR、Learning、AI Radar 从另一个文件夹再次运行时不会重复询问。

### 暂缓的兼容规则

Profile `version` 兼容和旧磁盘 domain 数据迁移延后到 V0.1 之后处理。V0.1 可以对不支持的 profile version 返回 `invalid_config`，而不是尝试迁移。

## Domain 示例

### HR

HR 中可复用的数据包括：

- 候选人档案
- 简历版本
- JD 记录
- 筛选批次
- 候选人-岗位匹配记录
- 风险信号
- 面试关注点
- 筛选报告

HR skill 负责候选人评分、JD 匹配、报告生成、ID 策略和面向用户的确认话术。

### DevOps

DevOps 中可复用的数据包括：

- 打包记录
- 构建摘要
- 镜像 manifest
- 发布说明
- 验证结果
- 部署环境快照
- 排障日志

DevOps skill 负责打包决策、验证含义、部署解释和发布建议。

### Learning

Learning 中可复用的数据包括：

- 学习者档案
- 学习目标
- 生成的课程
- 学习 session
- 进度复盘
- 学习日志

Learning skill 负责陪伴式教学、课程设计、进度判断和提醒语气。

### AI Radar

AI Radar 中可复用的数据包括：

- 信号
- 来源
- 评估
- 报告
- 趋势日志

AI Radar skill 负责信号判断、主题聚类、评估标准和报告写作。

## 降级行为

`io_error`：

- Runtime 命令已启动，但文件系统、锁或 IO 失败。
- Domain skill 正常降级运行。
- 结果中可以提示本次没有使用 wiki backend。

`runtime_unavailable`：

- Core/agent shell 找不到或无法执行 runtime 命令。
- Domain skill 正常降级运行。
- 结果中可以提示本次没有使用 wiki backend。

`missing_config`：

- First-party domain 可以询问是否启用 `.llm-wiki`。
- 如果用户在 `local` storage domain 中拒绝，写入一个最小 `.llm-wiki.yml`，其中 `enabled: false`。
- 如果用户在 `home` storage domain 中拒绝，把 profile 级别的拒绝记录写入 runtime 用户配置。
- 对于 home-scope domain，`missing_config` 表示默认 home scope 尚未初始化；runtime 不能静默创建它。
- 外部轻接入默认不打扰用户，除非用户显式要求启用 wiki mode。

`disabled`：

- 不再询问。
- 不写 `.llm-wiki`。
- 保持原有行为。

`invalid_config`：

- 不写 `.llm-wiki`。
- 报告配置问题。
- 尽可能继续输出业务结果。

`profile_mismatch`：

- 不跨 domain 写入。
- 尽可能继续原有输出。
- 提示当前目录配置的是另一个 profile。

## 验收标准

1. `llm-wiki-runtime` 可以作为顶层 skill 工作空间引入 `role-copilot-skills`。
2. V0.1 设计不要求迁移 `project-agent-copilot`。
3. HR 和 DevOps 是第一批深度接入目标。
4. Learning Companion 和 AI Radar 可以作为外部轻接入示例记录。
5. Domain skill 提供自己的 `llm-wiki-profile.yml`。
6. `llm-wiki-runtime` 可以从 domain 提供的 manifest 初始化 profile。
7. `write-record` 只写入当前 profile 声明过的 record type。
8. `write-record` 拒绝缺少必需变量或必需引用的写入。
9. `write-record` 执行 `create_only`、`update_allowed` 和 `append_only` 规则。
10. `load-context-pack` 只读取当前 profile read rules 允许的路径。
11. `llm-wiki-runtime` 不可用、禁用、配置错误或 profile 不匹配时，不阻断原始 domain skill 输出。
12. `safe-write` 可以作为内部能力存在，但 domain 集成应使用 `write-record`。
13. `resolve-config` 明确定义 scope 发现、`wiki_root` 解析和单 primary profile 行为。
14. V0.1 拒绝 multi-profile 写入，除非当前 primary profile 与调用方 profile 匹配。
15. 路径变量在模板渲染前必须被校验，normalize 后的最终路径必须仍在 `wiki_root` 内。
16. `source_id`、`artifact_id` 这类 core-owned 引用必须根据 core registry 校验。
17. Registry、artifact、log、source 和 record 写入都必须受 scope lock 保护。
18. JSON registry 和可替换 record 写入必须是原子的。
19. `update_allowed` 写入必须记录 revision metadata，包括旧 checksum 和新 checksum。
20. `load-context-pack` 必须定义确定性排序，并支持 `--path`、`--glob`、`--record-type`、`--ref` 等缩小范围的过滤。
21. 公开 CLI 命令必须返回 JSON，并使用文档化的 exit code。
22. `privacy_default` 被定义为提示和 Git 建议默认值，不是加密或权限控制。
23. `init-home` 支持用户自定义 `LLM_WIKI_HOME`，也支持平台默认路径。
24. V0.1 支持 `local` 和 `home` 两种存储模式。
25. HR、Learning、AI Radar 默认使用 home scope；DevOps 默认使用 local scope。
26. `resolve-config` 只有在 home scope 已初始化后才使用它；否则返回 `missing_config`。
27. Home-scope domain 的拒绝记录写入 runtime 用户配置，而不是当前工作目录。
28. `fallback_mode` 有明确取值，并且只是给 domain skill 的建议字段。
29. Scope lock 必须定义超时、stale lock 检测和恢复行为。
30. Core-managed `.meta/**` 默认从 context pack 排除。
31. Profile version 兼容和磁盘数据迁移明确延后到 V0.1 之后。
32. `init-profile` 必须把 active profile 快照到 `.llm-wiki/.meta/profile.yml`，后续读写命令默认使用该 snapshot。
33. `load-context-pack --policy data_only` 必须返回 `sanitized`、`risk_flags` 和生效 `instruction_policy`，供上层 core 做 supporting context 隔离。
