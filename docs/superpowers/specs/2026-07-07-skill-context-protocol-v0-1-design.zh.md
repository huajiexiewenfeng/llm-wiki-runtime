# Skill Context Protocol v0.1 设计文档

## 1. 背景

`llm-wiki-runtime` 解决的是 `.llm-wiki` 的确定性读写问题：scope 发现、路径安全、锁、原子写、索引、日志和 context pack。

但只有 runtime 还不够。不同 domain skill，例如 HR、Learning、AI Radar、DevOps，需要一种统一方式声明：

- 我是谁，属于哪个 domain。
- 我如何接入 `llm-wiki-core`。
- 我默认读写哪个 `.llm-wiki` profile。
- 我能生产哪些知识。
- 我查询时可以消费哪些 domain 的上下文。
- 当 wiki 不可用时，我如何降级。

因此引入 **SCP：Skill Context Protocol**。

SCP 不是存储协议，也不是数据格式协议。SCP 是 skill 与 `llm-wiki-core` 之间的上下文协作协议。

## 2. 核心目标

SCP v0.1 目标：

1. 让每个 domain skill 通过一个 `scp.yml` 声明自己的 domain、profile、读写能力和降级策略。
2. 让 `llm-wiki-core` 可以扫描已安装 skills，生成本机级 `skill-registry.json`。
3. 让 `llm-wiki-core` 的主动技能 `init`、`ingest`、`query`、`maintain` 能基于 SCP 编排 runtime CLI。
4. 让 query 支持 `primary_domain + supporting_domains` 的多 domain 上下文组合。
5. V0.1 不做跨 domain 写入、自动同步、derived records 或 cross reference index。

一句话定义：

```text
SCP v0.1 用于 skill 与 llm-wiki-core 的协作声明；
跨 domain 能力只发生在 query 阶段；
写入仍然只写 primary domain。
```

## 3. 分层关系

```text
Domain Skill
  HR / Learning / AI Radar / DevOps
  提供业务语义、用户交互、领域判断

SCP: scp.yml
  声明 skill 如何接入 llm-wiki-core
  声明 skill 的 domain、profile、query 消费关系和 ingest 产物

llm-wiki-core skill
  主动能力层
  提供 init / ingest / query / maintain
  解释 SCP，编排 runtime CLI

llm-wiki-runtime CLI
  执行层
  提供 resolve-config / init-home / init-profile / copy-source / write-record / load-context-pack / append-log

.llm-wiki
  domain knowledge store
```

三种合同：

```text
SCP
  skill 与 llm-wiki-core 的协作合同

llm-wiki-profile.yml
  domain 与 llm-wiki-runtime 的存储合同

runtime CLI contract
  llm-wiki-core 与 llm-wiki-runtime 的执行合同
```

## 4. SCP 文件位置

每个 skill 自带 `scp.yml`。

示例：

```text
hr-resume-screening/
  SKILL.md
  scp.yml

learning-companion/
  SKILL.md
  scp.yml

ai-radar-newsroom/
  SKILL.md
  scp.yml

devops-package-copilot/
  SKILL.md
  scp.yml
```

选择每个 skill 自带 `scp.yml` 的原因：

- skill 可独立发布到 GitHub。
- 安装 skill 后即可被 `llm-wiki-core` 扫描发现。
- 不需要 `llm-wiki-core` 硬编码所有 domain。
- 更符合“低成本接入”的目标。

## 5. SCP v0.1 最小结构

```yaml
scp_version: v0.1

skill:
  id: hr-resume-screening
  name: HR Resume Screening
  domain: hr
  role: domain_skill

llm_wiki:
  profile: hr
  default_storage_mode: home
  required: false
  fallback_mode: markdown

query:
  primary_domain: hr
  supports:
    - domain: ai-radar
      types: [hiring_trend, tool_trend]
      optional: true

ingest:
  produces:
    - domain: hr
      record_type: candidate_profile
    - domain: hr
      artifact_type: screening_report
    - domain: hr
      log_type: screening_log
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `scp_version` | SCP 协议版本 |
| `skill.id` | skill 唯一 ID |
| `skill.domain` | skill 默认所属 domain |
| `llm_wiki.profile` | 默认对应的 runtime profile |
| `llm_wiki.default_storage_mode` | `home` 或 `local` |
| `llm_wiki.required` | wiki 不可用时是否阻断主流程 |
| `llm_wiki.fallback_mode` | 降级模式，V0.1 推荐 `markdown` |
| `query.primary_domain` | 查询时默认主 domain |
| `query.supports` | 查询时可选补充 domain |
| `ingest.produces` | skill 可写入的本 domain 产物 |

## 6. 示例 SCP

### 6.1 HR

```yaml
scp_version: v0.1

skill:
  id: hr-resume-screening
  name: HR Resume Screening
  domain: hr
  role: domain_skill

llm_wiki:
  profile: hr
  default_storage_mode: home
  required: false
  fallback_mode: markdown

query:
  primary_domain: hr
  supports:
    - domain: ai-radar
      types: [hiring_trend, tool_trend]
      optional: true

ingest:
  produces:
    - domain: hr
      record_type: candidate_profile
    - domain: hr
      artifact_type: screening_report
```

### 6.2 Learning

```yaml
scp_version: v0.1

skill:
  id: learning-companion
  name: Learning Companion
  domain: learning
  role: domain_skill

llm_wiki:
  profile: learning
  default_storage_mode: home
  required: false
  fallback_mode: markdown

query:
  primary_domain: learning
  supports:
    - domain: ai-radar
      types: [tool_trend, learning_material]
      optional: true

ingest:
  produces:
    - domain: learning
      record_type: study_note
    - domain: learning
      record_type: learning_plan
    - domain: learning
      log_type: progress_log
```

### 6.3 AI Radar

```yaml
scp_version: v0.1

skill:
  id: ai-radar-newsroom
  name: AI Radar Newsroom
  domain: ai-radar
  role: domain_skill

llm_wiki:
  profile: ai-radar
  default_storage_mode: home
  required: false
  fallback_mode: markdown

query:
  primary_domain: ai-radar
  supports: []

ingest:
  produces:
    - domain: ai-radar
      record_type: model_release
    - domain: ai-radar
      record_type: tool_trend
    - domain: ai-radar
      record_type: learning_material
```

### 6.4 DevOps

```yaml
scp_version: v0.1

skill:
  id: devops-package-copilot
  name: DevOps Package Copilot
  domain: devops
  role: domain_skill

llm_wiki:
  profile: devops
  default_storage_mode: local
  required: false
  fallback_mode: markdown

query:
  primary_domain: devops
  supports:
    - domain: ai-radar
      types: [tool_update, ci_cd_trend]
      optional: true

ingest:
  produces:
    - domain: devops
      record_type: package_run
    - domain: devops
      artifact_type: verification_result
```

## 7. SCP Registry

`llm-wiki-core` 扫描 `scp.yml` 后生成本机级 registry。

推荐位置：

```text
%APPDATA%\llm-wiki-runtime\skill-registry.json
```

它不属于任何 domain 的业务知识库，不放进 `.llm-wiki/domains/<domain>/`。

最小结构：

```json
{
  "version": "v0.1",
  "generated_at": "2026-07-07T10:00:00+08:00",
  "skills": {
    "hr-resume-screening": {
      "domain": "hr",
      "profile": "hr",
      "scp_path": "C:/Users/admin/.agents/skills/hr-resume-screening/scp.yml",
      "storage_mode": "home",
      "fallback_mode": "markdown",
      "produces": ["candidate_profile", "screening_report"],
      "supports": ["ai-radar"]
    }
  },
  "domains": {
    "hr": {
      "skills": ["hr-resume-screening"],
      "profiles": ["hr"],
      "produces": ["candidate_profile", "screening_report"],
      "supports": ["ai-radar"]
    },
    "learning": {
      "skills": ["learning-companion"],
      "profiles": ["learning"],
      "produces": ["study_note", "learning_plan", "progress_log"],
      "supports": ["ai-radar"]
    },
    "ai-radar": {
      "skills": ["ai-radar-newsroom"],
      "profiles": ["ai-radar"],
      "produces": ["model_release", "tool_trend", "learning_material"],
      "supports": []
    },
    "devops": {
      "skills": ["devops-package-copilot"],
      "profiles": ["devops"],
      "produces": ["package_run", "verification_result"],
      "supports": ["ai-radar"]
    }
  }
}
```

Registry 生成时机：

1. `llm-wiki-core scan`
2. `llm-wiki-core init`
3. `llm-wiki-core maintain`

V0.1 不需要文件监听。需要时扫描，扫描结果缓存。

## 8. SCP 文件发现规则

V0.1 支持固定 skill roots：

```text
C:\Users\admin\.agents\skills\**\scp.yml
C:\Users\admin\.codex\skills\**\scp.yml
<current-repo>\.agents\skills\**\scp.yml
```

未来可扩展：

```text
Claude Code skills
Codex skills
GitHub 安装路径
用户自定义 skill roots
```

发现规则：

1. 扫描所有候选 `scp.yml`。
2. 校验 `scp_version`。
3. 校验 `skill.id`、`skill.domain`、`llm_wiki.profile`。
4. 生成 registry。
5. 冲突时保留错误信息，不让错误 skill 影响其他 skill。

冲突示例：

- 两个 skill 使用同一个 `skill.id`。
- `skill.domain` 与 `query.primary_domain` 不一致。
- `ingest.produces.domain` 不是当前 skill domain。
- `supports.domain` 未安装，但 `optional: false`。

## 9. llm-wiki-core 主动技能

`llm-wiki-core` 提供四个主动技能。

### 9.1 init

职责：

- 根据 SCP 找到 domain/profile/storage mode。
- 调用 `resolve-config` 判断是否已启用。
- 必要时引导用户首次确认。
- 调用 `init-home` 和 `init-profile` 初始化 scope。
- 用户拒绝时调用 `init-profile --decline`。

输入：

```text
domain/profile 可显式指定，也可从当前 skill 的 SCP 推断。
```

### 9.2 ingest

职责：

- 根据 SCP 的 `ingest.produces` 判断当前 skill 可以写入哪些 record/artifact/log。
- 调用 `copy-source`、`write-record`、`append-log`。
- V0.1 只允许写入当前 primary domain。

不做：

- 不写 supporting domain。
- 不做跨 domain 派生写入。
- 不自动复制其他 domain 数据。

### 9.3 query

职责：

- 确定 `primary_domain`。
- 确定 `supporting_domains`。
- 分别调用 `resolve-config`。
- 对 enabled 的 domains 调用 `load-context-pack`。
- 合并成分层 context。

V0.1 的跨 domain 能力只在这里发生。

### 9.4 maintain

职责：

- 重新扫描 `scp.yml`。
- 重建 `skill-registry.json`。
- 检查 SCP 与 profile 是否一致。
- 检查 registry 中声明的 domains 是否能 resolve。
- 检查 disabled/declined 状态是否符合预期。

V0.1 不做深度业务校验。

## 10. Domain Routing

`llm-wiki-core query` 的 domain 决策顺序：

```text
1. 用户显式指定 domain/profile
2. 当前调用方 skill 在 registry 中声明了 domain
3. 当前目录 .llm-wiki.yml 有 primary_profile
4. registry + 简单关键词意图识别
5. 不确定时反问用户
```

示例关键词：

| domain | 关键词 |
| --- | --- |
| `hr` | 候选人、简历、JD、面试、筛选 |
| `learning` | 学习、课程、进度、复习、计划 |
| `ai-radar` | 模型、AI 新闻、工具趋势、Claude、OpenAI |
| `devops` | 打包、镜像、发布、Docker、CI、部署 |

意图识别只能辅助，不能覆盖显式指定。

多义示例：

```text
结合 Claude Code 帮我设计学习计划
```

应解析为：

```json
{
  "primary_domain": "learning",
  "supporting_domains": ["ai-radar"]
}
```

原因：

- “学习计划”是本次任务目标。
- “Claude Code”是补充知识来源。

## 11. Query 阶段的跨 Domain 上下文

V0.1 只做 query-time context composition。

```text
primary_context
  来自 primary_domain，是本次回答的主依据

supporting_context
  来自 supporting_domains，只作为补充材料
```

推荐输出结构：

```json
{
  "primary_domain": "learning",
  "supporting_domains": ["ai-radar"],
  "context": {
    "primary": [
      {
        "domain": "learning",
        "path": "domains/learning/plans/current.md",
        "content": "当前目标：系统学习 Claude Code。当前阶段：基础实践。"
      }
    ],
    "supporting": [
      {
        "domain": "ai-radar",
        "path": "domains/ai-radar/tools/claude-code.md",
        "content": "Claude Code 近期能力变化：更适合长任务执行、代码库导航和本地工具协作。"
      }
    ]
  }
}
```

Prompt 约束：

```text
你正在回答 primary_domain 的问题。
primary context 是主上下文。
supporting context 只能作为补充引用，不能覆盖 primary domain 的事实状态。
如果 supporting context 与 primary context 冲突，以 primary context 为准。
```

示例：

```text
primary_domain = learning
supporting_domains = [ai-radar]
```

Learning 的学习进度是主事实。AI Radar 的工具趋势只能帮助生成建议，不能改变用户已经学到哪里的事实。

## 12. 写入边界

V0.1 写入规则：

```text
默认只能写 primary_domain。
supporting_domains 只读。
query 不写入跨 domain refs。
query 不生成 derived records。
query 不改变任何 domain 的数据归属。
```

因此：

- HR skill 写 HR。
- Learning skill 写 Learning。
- AI Radar skill 写 AI Radar。
- DevOps skill 写 DevOps。

AI Radar 可以在 query 阶段被 HR、Learning、DevOps 引用，但不会被这些 skills 直接修改。

## 13. 降级策略

`llm_wiki.required: false` 时，wiki 不可用不阻断 domain skill。

常见状态：

| 状态 | 行为 |
| --- | --- |
| `missing_config` | first-party skill 可询问是否启用 |
| `disabled` | 不再询问，按 fallback mode 运行 |
| `profile_mismatch` | 降级运行 |
| `invalid_config` | 降级运行并提示配置异常 |
| `io_error` | 降级运行并提示 wiki backend 未使用 |

V0.1 推荐：

```yaml
fallback_mode: markdown
```

## 14. 与 Runtime CLI 的关系

SCP 不直接写文件。`llm-wiki-core` 解释 SCP 后调用 runtime CLI。

映射关系：

| llm-wiki-core 主动技能 | runtime CLI |
| --- | --- |
| `init` | `resolve-config`, `init-home`, `init-profile` |
| `ingest` | `copy-source`, `write-record`, `append-log`, `register-artifact` |
| `query` | `resolve-config`, `load-context-pack` |
| `maintain` | V0.1 可先做 registry scan，未来接 `lint` / `doctor` |

## 15. 非目标

SCP v0.1 不做：

- 跨 domain 写入。
- 跨 domain 自动同步。
- `cross_refs/index.json`。
- derived records。
- vector search。
- 实时监听 skill 目录变化。
- 完整 YAML 复杂语法。
- 外部第三方 skill 的完全自动兼容。

## 16. 验收标准

SCP v0.1 设计满足：

1. 每个 first-party skill 可以通过 `scp.yml` 声明接入信息。
2. `llm-wiki-core` 可以扫描 `scp.yml` 并生成 `skill-registry.json`。
3. `llm-wiki-core query` 可以根据显式 domain、当前 skill、当前目录或意图识别决定 primary domain。
4. `llm-wiki-core query` 可以组合 `primary_domain + supporting_domains`。
5. supporting domain 只读，不参与写入。
6. `llm-wiki-core ingest` 只写当前 primary domain。
7. wiki 不可用时，domain skill 可以根据 `fallback_mode` 降级。
8. HR、Learning、AI Radar、DevOps 四类 first-party domain 都能用同一套 SCP 表达。

## 17. 推荐 V0.1 实施顺序

1. 在 `llm-wiki-core` skill 中定义 `scp.yml` schema 文档。
2. 给 HR、Learning、AI Radar、DevOps 各写一个 `scp.yml` 示例。
3. 实现 `scan`，生成 `skill-registry.json`。
4. 实现 `query` domain routing。
5. 实现 query-time `primary_context + supporting_context` 合并。
6. 实现 `maintain` 的 registry 检查。

暂不实现跨 domain refs 和 derived records。
