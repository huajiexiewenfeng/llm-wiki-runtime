# Domain Skill 接入 llm-wiki-runtime：5 分钟手册

本文用于把一个本地 Domain Skill 接入通用 `llm-wiki-runtime`，同时不改变用户原来的使用方式。

一句话原则：

> Domain 负责业务语义，`llm-wiki-core` 负责编排，`llm-wiki-runtime` 负责安全读写。

## 谁执行哪些步骤

- **第 1–5 步由 LLM 执行**：把本文交给 Codex、Claude Code 或其他编码 Agent，由它检查并改造本地 Domain Skill。
- **第 6 步开始由人操作**：人只使用自然语言完成启用、初始化、首次导入和真实验证，不编辑 YAML，也不直接运行 CLI。

LLM 在完成第 5 步前不得要求人手工创建目录、填写配置或拼接 runtime 命令。

## 第 1–5 步：LLM 完成接入

### 第 1 步：检查 Domain 并准备三个声明文件

LLM 先读取 Domain 下所有 `SKILL.md`，确认业务边界、已有数据来源、原流程和降级方式，再创建或更新：

```text
my-domain-copilot/
  llm-wiki-profile.yml     # 存什么、放哪里、怎么读
  ingest-mapping.yml       # 外部资料如何变成领域记录
  my-business-skill/
    SKILL.md
    scp.yml                # 这个 Skill 能读写什么
```

不要让 Domain Skill 直接写 `.llm-wiki`，所有读写都走 runtime CLI。

### 0.3：选择 Skill/SCP 兼容入口或 Workload 入口

普通业务 Skill 继续使用本章的 `scp.yml`，由维护流程执行
`scan-scp --scp-path-json ... --write`。受治理的 Harness 是 Workload，必须额外
携带并显式注册 `principal.yml`，不能把 Workload 当作 SCP Skill：

```yaml
principal_version: v0.1
principal:
  id: my-domain-harness
  kind: workload
  role: domain_harness
  domain: my-domain
llm_wiki:
  profile: my-domain
  fallback_mode: evidence_only
query:
  primary_domain: my-domain
  supports: []
ingest:
  produces:
    - domain: my-domain
      record_type: knowledge_note
```

```powershell
llm-wiki register-principal --manifest .\principal.yml --registry-path .\principal-registry.json
llm-wiki scan-scp --scp-path-json '[".\\my-business-skill\\scp.yml"]' --write --output .\principal-registry.json
```

顶层 `skills` 是 Registry `principals` 中 `kind: skill` 的确定性只读投影，
用于兼容旧调用；它不是独立授权来源，不能独立修改。扫描 SCP 只能刷新
Skill 条目，且必须保留已注册 Workload。

`principal.id` 是协议中的主体标识，用于契约 digest 与审计绑定；它不是密码、
证书、签名密钥或任何加密学身份保证。

Workload 通过一个 `invoke` 请求调用 Runtime。完整 Query 请求和命令如下：

```json
{
  "protocol_version": "v0.1",
  "request_id": "req-query-001",
  "principal_id": "my-domain-harness",
  "operation": "find_records",
  "scope_root": "C:\\work\\my-domain-project",
  "payload": {
    "record_type": "knowledge_note",
    "lookup_value": "note-001"
  }
}
```

```powershell
llm-wiki invoke --request .\request.query.json --registry-path .\principal-registry.json --profile-path .\llm-wiki-profile.yml
```

写入必须同时绑定 Workload、活动 Profile 和 v0.2 Mapping。Workload 的完整
`ingest-mapping.yml` 如下（`owner_principal_id` 必须等于注册的主体）：

```yaml
mapping:
  id: my-domain-import
  version: v0.2
  domain: my-domain
  owner_principal_id: my-domain-harness
  source_types: [user_file]
  instruction_ref: references/llm-wiki-ingest.md

produces:
  - record_type: knowledge_note
```

完整写请求和命令如下：

```json
{
  "protocol_version": "v0.1",
  "request_id": "req-write-001",
  "principal_id": "my-domain-harness",
  "operation": "write_record",
  "scope_root": "C:\\work\\my-domain-project",
  "mapping_id": "my-domain-import",
  "payload": {
    "record_type": "knowledge_note",
    "variables": {"record_id": "note-001"},
    "refs": {"source_id": "source-001"},
    "content_file": "C:\\work\\my-domain-project\\prepared-note.md"
  }
}
```

```powershell
llm-wiki invoke --request .\request.write.json --registry-path .\principal-registry.json --profile-path .\llm-wiki-profile.yml --mapping-path .\ingest-mapping.yml
```

Workload Invocation 失败时不得静默回退到旧 `write-record`、`copy-source`、
`append-log` 等命令；旧命令只保留给 Skill/operator 兼容使用。Runtime 0.2
已经完成的记录仍可读取，但旧契约下待处理的批准为 stale，必须重新校验后才可写入。

### 第 2 步：定义 Domain Profile

最小 `llm-wiki-profile.yml`：

```yaml
profile:
  id: my-domain
  version: v0.1
  display_name: My Domain
  scope_type: personal
  privacy_default: user_owned

layout:
  directories:
    - domains/my-domain/records
    - sources/originals/my-domain
    - logs

write_rules:
  records:
    knowledge_note:
      path: domains/my-domain/records/{record_id}.md
      mode: update_allowed
      required_vars: [record_id]
      required_refs: [source_id]

read_rules:
  context_pack:
    include: [domains/my-domain/**]
    exclude: [sources/originals/**, .meta/**]
    max_files: 30
    max_chars_per_file: 4000
  record_lookup:
    knowledge_note:
      identity_field: record_id
      display_field: title
      match_fields: [title]
      return_fields: [record_id, title]
      max_results: 10
```

Profile 由 Domain 维护；runtime 只执行其中的路径、引用和读写规则。

### 第 3 步：定义 Ingest Mapping

本节的 v0.1 `owner_skill_id` 示例只适用于既有 Skill/SCP 兼容入口；它与
上面的 Workload `principal.yml` 路径隔离。Workload 写入必须使用上一节的
v0.2 Mapping 和 `owner_principal_id`，不得以 v0.1 Mapping 静默回退。

最小 `ingest-mapping.yml`：

```yaml
mapping:
  id: my-domain-user-file
  version: v0.1
  domain: my-domain
  owner_skill_id: my-business-skill
  source_types: [user_file]
  instruction_ref: references/llm-wiki-ingest.md

produces:
  - record_type: knowledge_note
```

Mapping 只声明输入来源和产物。如何理解资料、生成 `record_id`、区分事实与推断，仍由 Domain Skill 决定。

### 第 4 步：给每个业务 Skill 增加 SCP

最小 `scp.yml`：

```yaml
scp_version: v0.1

skill:
  id: my-business-skill
  name: My Business Skill
  domain: my-domain
  role: domain_skill

llm_wiki:
  profile: my-domain
  required: false
  fallback_mode: markdown

trust:
  level: user_owned
  source_kind: user_local_data
  instruction_policy: trusted_content

query:
  primary_domain: my-domain
  supports: []

ingest:
  produces:
    - domain: my-domain
      record_type: knowledge_note
```

`scp.yml` 不声明 `storage_mode`。知识库放在 home、项目目录还是未来的服务器，由宿主策略决定。

### 第 5 步：接入运行流程并完成自检

LLM 必须把下面的前后置流程写入每个业务 `SKILL.md`；只新增 Profile、Mapping 和 SCP，不算完成接入。

### 尚未启用 Wiki

```text
执行原业务任务并返回结果
  → 判断本次是否产生了值得复用的数据
  → 在结果末尾提示安装 llm-wiki
  → 用户同意后安装 runtime/core
  → init 当前 Domain
  → 预览本次准备入库的数据
  → 用户确认后 ingest 当前任务
```

不要在用户第一次使用 Skill 时先弹安装提示。先让 Skill 完成业务，再说明长期记忆能带来什么。

推荐提示：

> 本次产生了可复用的资料。是否启用本地知识库？启用后，后续同类任务可以自动读取这次记录；未经确认不会写入当前资料。

安装方式由 Codex、Claude Code 或其他宿主适配器负责。Domain Skill 不要硬编码某一个宿主的安装命令。

用户拒绝安装时，宿主按 Domain 记录全局偏好，不再自动提示。该偏好只记录 `domain`、`declined_at` 和状态，不保存业务数据。用户主动说“启用 `<domain>` 知识库”时可以重新开启。

### 已启用 Wiki

每次业务调用固定执行：

```text
resolve-config
  → preflight query（只取本次相关上下文）
  → 执行原业务逻辑
  → postflight 判断可复用数据
  → ingest / write-record / append-log
  → 返回业务结果和 context_refs
```

`init` 是每个 Domain/scope 的一次性动作，不是每个子 Skill 都初始化一次。同一 Domain 下的多个 Skill 共用该 scope。

LLM 使用四个 Core Skill 完成编排：

| Core Skill | 用途 | 常用 runtime CLI |
| --- | --- | --- |
| `llm-wiki-init` | 首次启用 Domain | `resolve-config`、`init-home`、`init-profile` |
| `llm-wiki-query` | 业务执行前读取上下文 | `resolve-config`、`load-context-pack` |
| `llm-wiki-ingest` | 保存来源和有价值结果 | `copy-source`、`write-record`、`append-log` |
| `llm-wiki-maintain` | 检查声明与数据健康 | `scan-scp`、mapping/profile 校验 |

`llm_wiki.required` 默认设为 `false`。runtime/core 未安装、用户禁用、profile 不匹配、mapping 校验失败或发生 IO 错误时，原业务流程必须继续，只提示：

> 本次未使用本地知识库，已按原流程继续。

LLM 在交付前必须验证：

- [ ] 未安装 runtime 时原 Skill 仍能完成任务。
- [ ] Profile、Mapping 与 SCP 可以通过现有校验。
- [ ] 首次任务先返回业务结果，再提示安装。
- [ ] 用户拒绝后不再自动提示该 Domain。
- [ ] `init` 只发生一次，多个子 Skill 共用同一 scope。
- [ ] 首次 ingest 前展示待写入内容并取得确认。
- [ ] query 使用窄范围过滤，不默认读取 `sources/originals/**` 和 `.meta/**`。
- [ ] 所有写入都通过 runtime CLI，失败时安全降级。

完成后，LLM 只向人报告：修改了哪些 Skill、使用哪个 Domain/profile，以及第 6–8 步的自然语言测试提示。不要让人学习上表中的 CLI。

## 第 6 步：完成第一次真实业务任务

人在一个新任务中正常使用 Domain Skill，例如：

```text
请使用 <domain> Skill 完成这次真实任务。
```

预期体验：

- Skill 先完成原业务，不先打断用户安装组件。
- 本次产生可复用数据时，结果末尾才提示启用本地知识库。
- 没有可复用数据时，不显示安装提示。

## 第 7 步：确认安装、初始化和当前任务入库

人只需回答自然语言确认，不填写路径或 YAML：

```text
确认安装并启用 <domain> 知识库，使用推荐目录。
```

Agent 应依次说明并等待确认：

1. 安装 `llm-wiki-core` 和 runtime。
2. 初始化当前 Domain scope。
3. 展示当前任务中准备写入的资料和敏感数据风险。
4. 只在确认后 ingest 当前任务。

初始化成功后，历史导入是可选的第二步，不应阻塞当前任务第一次入库。

## 第 8 步：在新任务中验证记忆

新开一个任务，不重新提供第一次的完整资料，直接继续业务：

```text
继续刚才的 <domain> 工作，请先读取已有知识库再回答。
```

成功标准：Agent 能引用第一次保存的相关记录；如果 Wiki 不可用，原业务仍然能继续，并明确说明本次已降级。

## 第 9 步：人的最终验收

- [ ] 第一次使用没有被安装流程打断。
- [ ] 安装、初始化和资料写入分别经过确认。
- [ ] 人没有手工编辑配置或执行 CLI。
- [ ] 第二个任务能复用第一次保存的数据。
- [ ] 拒绝启用后不再反复提示；主动说“启用知识库”仍可重新开启。
- [ ] Wiki 故障不会让原 Domain Skill 无法使用。

## 附录：可直接参考的实现

- HR Domain：`role-copilot-skills/hr-agent-copilot`
- HR Profile：`hr-agent-copilot/llm-wiki-profile.yml`
- HR Mapping：`hr-agent-copilot/ingest-mapping.yml`
- HR SCP：`hr-agent-copilot/hr-resume-screening-copilot/scp.yml`
- Core Skill：`skills/llm-wiki-core`

第一次接入只完成一个真实闭环：**当前任务产生数据 → 确认写入 → 下一次任务成功读取**。跑通后再增加更多 record type、历史导入和跨 Domain query。
