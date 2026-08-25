# LLM Wiki Runtime 0.3.0 Principal + Workload 设计

- 状态：已批准，待书面规格复核
- 日期：2026-08-25
- 目标版本：`llm-wiki-runtime 0.3.0`
- 当前基线：`llm-wiki-runtime 0.2.0`
- 首个 Workload 验收方：AI Research Observatory Harness

## 1. 背景与问题

`llm-wiki-runtime 0.2.0` 是面向 Agent Skills 与 Copilot 的确定性本地知识运行时。它通过 Domain Profile、SCP、Ingest Mapping、Skill Registry 和 Runtime CLI，为多个 Domain Skill 提供受控的知识读写能力。

这一模型适合以 Skill 为主要执行方的业务，但把以下三个概念绑定在了同一个 `skill.id` 上：

- 领域语义入口；
- Runtime 调用主体；
- Mapping 与产物的技术所有者。

AI Research Observatory 暴露了这个抽象的局限。它的 Skill 负责自然语言入口、Evidence 价值判断以及 `fact / inference / hypothesis` 的语义边界；真正长期运行的主体却是 Harness。Harness 负责 Workflow、Plan、Human Gate、Receipt、恢复以及 Runtime Adapter，并且还需要支持 CLI、Scheduler 或其他非 Skill 入口。

当前 Mapping 又强制使用 `owner_skill_id`，Registry 的一等对象也是 `skills`。因此，Harness 即使是 Runtime 的主要程序调用方，仍必须借用或伪装成某个 Skill 身份。Skill 安装缺失、安装副本落后或 Skill 路径变化，也会不必要地影响 Harness 的 Memory 能力。

问题的本质不是 Observatory 是否应该继续叫 Harness，而是 Runtime 缺少独立于 Skill 的程序主体抽象。

## 2. 目标

核心目标是：

> 让 `llm-wiki-runtime` 从必须依附 Skill 的知识后端，演进为可被 Skill 与独立 Workload 共同使用的通用 Agent Memory + Knowledge Runtime。

`0.3.0` 必须实现：

1. Skill 与 Workload 是并列 Principal，而不是彼此替代。
2. AI Research Observatory Harness 能在未安装 Observatory Skill 时独立查询和受控写入自己的 Domain Workspace。
3. Skill 与 Harness 可以同时接入同一个 Domain、Profile 和 Workspace。
4. Runtime 内部使用统一 Principal Registry 与授权模型。
5. 旧 SCP、Skill Registry 输入、`owner_skill_id` 和现有 CLI 保持兼容。
6. Principal-aware 调用在真实 Query 与写入操作上执行授权，不能只做装饰性预检。
7. Runtime 的 Profile、路径、锁、原子写和记录查询核心继续复用，不因接入模型升级而重写。

最简目标定义为：

> Skill 可以使用 Runtime，但 Runtime 不再必须依赖 Skill；Harness 作为 Workload，成为独立、受控、可审计的一等调用方。

## 3. 非目标

`0.3.0` 不实现：

- 向量检索、Embedding 或新的通用语义搜索；
- MCP Server；
- 云端 Runtime、团队权限或多用户身份认证；
- `agent`、`service`、`operator` 等新的 Principal kind；
- Workload 的密码学身份、签名 manifest 或 OS workload identity；
- 自动 Promotion、无人审批的长期知识写入；
- Observatory 的完整 Claim、Decision、Outcome 数据飞轮；
- 新的存储引擎、第二套文件锁或新的事务系统；
- 删除 `0.2.0` 的 SCP、Mapping 或 CLI 兼容入口。

## 4. 术语与核心不变量

### 4.1 术语

- `Domain`：知识所属领域，例如 `ai-research-observatory`。
- `Principal`：向 Runtime 请求能力的逻辑主体。
- `Skill Principal`：由现有 SCP 兼容得到的 Skill 主体。
- `Workload Principal`：独立运行的软件主体；首版只允许 `role: domain_harness`。
- `Interface`：Principal 使用 Runtime 的方式，例如 CLI、Python API 或未来 MCP；Interface 不是身份。
- `Harness`：承载并约束一个或多个 Workflow 的领域执行与治理组件，包括状态、Human Gate、Receipt 和恢复。
- `Workflow`：Harness 内部的步骤和控制流，不等同于 Runtime Principal。

### 4.2 不变量

```text
Domain != Principal != Interface

Domain Skill 负责领域语义
Harness 负责 Workflow、治理、授权与审计
Runtime 负责确定性访问与能力校验
Human 负责语义 Review 和持久写入批准
Skill 与 Harness 都不得直接写 .llm-wiki
```

Principal 的 `kind` 只描述主体类别，不直接授予权限。最终能力必须来自声明与 Host/Domain Policy、Profile 和 Mapping 的交集。

## 5. 方案比较与选择

### 5.1 方案 A：统一 Principal Registry

旧 SCP 与新 Workload Manifest 经过不同入口进入同一个 Principal Registry。Mapping 统一引用 Principal。

优点：Runtime 内部只有一种主体与授权模型；旧 Skill 可兼容；Harness 不依赖 Skill 安装目录；未来扩展不需要增加更多 Registry。

缺点：需要升级 Registry schema，并实现兼容适配、冲突检测和迁移诊断。

结论：采用。

### 5.2 方案 B：每次调用显式传 Workload Manifest

Workload 不注册，每个命令都携带完整 Manifest。

优点：没有 Registry 缓存漂移。

缺点：每次调用重复绑定 Manifest，审计与 Domain 汇总困难；旧 Skill Registry 仍然存在，Runtime 内部形成两套主体模型。

结论：不采用。

### 5.3 方案 C：Skill Registry 与 Workload Registry 并存

优点：初始改动较小。

缺点：权限、Trust、Domain、Profile 和 Mapping 校验需要双分支；未来容易继续增加 Agent Registry、Service Registry，永久固化割裂。

结论：不采用。

## 6. 总体架构

```text
用户 / Agent
    |
    v
Skill Principal ----------------------+
  语义理解、自然语言交互              |
    | query Runtime 或调用 Harness     |
    v                                 |
Workload Principal                    |
  kind: workload                      |
  role: domain_harness                |
  Workflow、Plan、Gate、Receipt、恢复  |
    |                                 |
    +---------------+-----------------+
                    v
           llm-wiki-runtime
           Principal + Policy 校验
           Profile / Mapping / IO
                    |
                    v
            同一个 Domain Workspace
```

Skill 与 Harness 可以共享：

- Domain；
- Domain Workspace；
- Active Profile；
- 长期知识记录；
- Evidence 引用；
- Runtime Query 能力。

它们必须分别拥有：

- `principal_id`；
- `kind` 与适用的 `role`；
- Contract digest；
- Trust 声明；
- 查询与产物声明；
- 审计中的 caller identity。

## 7. Principal Contract

### 7.1 Workload Manifest

Harness 在自己的仓库或安装包中携带 `principal.yml`：

```yaml
principal_version: v0.1

principal:
  id: ai-research-observatory-harness
  kind: workload
  role: domain_harness
  domain: ai-research-observatory

llm_wiki:
  profile: ai-research-observatory
  required: false
  fallback_mode: markdown

trust:
  level: internal_sensitive
  source_type: harness_generated
  instruction_policy: data_only

query:
  primary_domain: ai-research-observatory
  supports: []

ingest:
  produces:
    - domain: ai-research-observatory
      record_type: research_direction_revision
    - domain: ai-research-observatory
      artifact_type: observatory_memory_promotion
    - domain: ai-research-observatory
      log_type: observatory_memory_event
```

首版只支持：

```text
principal.kind: skill | workload
workload.role: domain_harness
```

`principal.yml` 只能声明主体、Domain、Profile、Trust、Query 和允许产物。它不得包含：

- Runtime executable；
- Workspace 绝对路径；
- Token、Cookie 或其他凭据；
- Human Approval；
- 任意物理写入路径；
- 可以覆盖 Host/Domain Policy 的自授权字段。

### 7.2 Skill Compatibility Adapter

现有 SCP 保持原格式。Runtime 在 Registry 构建阶段把它规范化为：

```yaml
principal:
  id: <skill.id>
  kind: skill
  domain: <skill.domain>
```

SCP 中的 `llm_wiki`、`trust`、`query` 和 `ingest` 语义原样进入统一 Principal 模型。适配不得提高 Trust、扩大 Domain 或增加产物。

### 7.3 Contract Digest

Runtime 对规范化后的 Principal Contract 计算 canonical digest。Registry、Invocation Observation、Promotion Plan 和 Receipt 使用该 digest，而不是依赖 Manifest 文件时间。

Manifest/SCP 内容变化后必须重新注册或重建 Registry；依赖旧 digest 的 Principal-aware Plan 和 Approval 立即 stale。

## 8. Principal Registry v0.2

逻辑 schema：

```json
{
  "version": "v0.2",
  "principals": {
    "ai-research-observatory": {
      "kind": "skill",
      "origin": "legacy_scp",
      "contract_digest": "sha256:..."
    },
    "ai-research-observatory-harness": {
      "kind": "workload",
      "role": "domain_harness",
      "origin": "principal_manifest",
      "contract_digest": "sha256:..."
    }
  },
  "domains": {},
  "domain_policies": {},
  "skills": {},
  "warnings": []
}
```

Registry 的物理文件名由 Host/Runtime 配置决定，不属于协议身份。`0.3.0` 必须继续接受显式传入的旧 `skill-registry.json`，但内部一律规范化为 v0.2 Principal Registry。

顶层 `skills` 仅是从 `principals` 中筛选 `kind: skill` 后确定性生成的只读兼容投影，用于保持现有 `scan-scp` 调用方兼容。它不得独立更新、不得拥有与对应 Principal 不同的 Contract digest，也不是第二份授权权威；任何不一致都返回 `principal_conflict`。

### 8.1 构建与注册入口

```text
scan-scp
→ 替换/刷新 origin=legacy_scp 的 Principal
→ 保留已注册的 Workload Principal

register-principal --manifest <principal.yml>
→ 原子注册或刷新一个 Workload Principal
```

`scan-scp --write` 不得因重建 Skill 条目而删除 Workload 条目。`register-principal` 不得修改由 SCP 管理的 Skill 条目。

### 8.2 冲突规则

- 相同 ID、相同 kind、相同 digest：幂等成功。
- 相同 ID、相同 kind、不同 digest：普通注册与调用返回 `principal_contract_stale`；只有显式 `register-principal --refresh` 才能替换 Workload Contract digest。
- 相同 ID、不同 kind：`principal_conflict`，fail closed。
- 重复 Manifest 路径但不同 ID：按 Contract 内容分别校验，不用路径作为身份。
- Registry 中未知字段按 schema 版本规则处理，不得被静默当作授权。

### 8.3 迁移规则

- 读取 v0.1 Skill Registry 时允许只在内存中规范化。
- 普通 Query 不得静默重写 Registry 文件。
- 只有显式 `scan-scp --write`、`register-principal` 或迁移动作可以落盘 v0.2。
- `scan-scp --write` 可以刷新由 SCP 管理的 Skill Contract；`register-principal --refresh` 只能刷新由 Manifest 管理的 Workload Contract，二者不得越权修改对方条目。
- Registry 存储位置发生变化时必须由显式迁移或 Host 配置完成，不能在读取时猜测并复制。
- Runtime、Principal、Profile 或 Mapping 升级会使尚未执行的旧 Plan/Approval stale；已经拥有 terminal complete Receipt 且记录 checksum 仍一致的既有记录必须保持只读可召回。升级后的召回使用新的 Principal-aware Query 重新校验实际记录，但不得重写历史 Receipt 或把旧 Receipt 冒充为 `0.3.0` 写入凭证。

## 9. Mapping v0.2 与兼容

新 Mapping 使用：

```yaml
mapping:
  id: ai-research-observatory-memory
  version: v0.2
  domain: ai-research-observatory
  owner_principal_id: ai-research-observatory-harness
```

旧 Mapping 继续允许：

```yaml
owner_skill_id: ai-research-observatory
```

规则：

1. 旧 `owner_skill_id` 在内存中规范化为 `owner_principal_id`。
2. 新 Mapping 不得继续产生 `owner_skill_id`。
3. 同一 Mapping 同时出现两个 Owner 字段时拒绝。
4. 一份 Mapping 只有一个 Owner Principal。
5. 其他 Principal 可以在授权范围内读取同一 Domain，但不能借用该 Mapping 写入。
6. 校验结果统一返回 `owner_principal_id`、`principal_kind` 和 Mapping digest。

对 Observatory，新的长期语义 Mapping 归 Harness 所有。Skill 负责产生候选或发起请求，Harness 负责 Review、Plan、Approval、Promotion 与 Receipt。

## 10. 授权模型

有效能力定义为：

```text
Effective Capability
= Principal Contract 声明
∩ Principal Registry 当前条目
∩ Host/Domain Policy
∩ Active Profile
∩ Ingest Mapping（写入时）
```

约束：

- `kind` 与 `role` 不直接授予 Query 或写权限。
- Workload 自报 `ingest.produces` 不能覆盖 Host/Domain Policy。
- Query 必须满足 Principal 的 primary/supporting Domain 声明与 Domain Policy。
- Write 必须由对应 Mapping 的 Owner Principal 发起，并且产物同时存在于 Contract、Mapping 和 Profile 中。
- Profile、Policy 或 Mapping 任一侧缩小权限后立即生效。
- `llm_wiki.required: false` 只允许原业务流程诚实降级；任何持久写入仍必须 fail closed。

## 11. Principal-aware Invocation

### 11.1 新应用边界

`0.3.0` 新增统一调用入口：

```powershell
llm-wiki invoke --request <request.json>
```

Invocation Envelope 示例：

```json
{
  "protocol_version": "v0.1",
  "request_id": "req-...",
  "principal_id": "ai-research-observatory-harness",
  "operation": "write_record",
  "scope_root": "<explicit-workspace>",
  "mapping_id": "ai-research-observatory-memory",
  "payload": {}
}
```

Host/Adapter 还必须显式提供或配置 Registry、Profile 和适用的 Mapping 来源。Runtime 以逻辑 ID 和实际 digest 双重核验，不能只相信请求中的路径或 ID。临时 Invocation 可以包含本机绝对路径，但持久 Plan、Receipt 和领域记录只保存 Workspace identity、逻辑 ID、digest 与必要的相对路径。

### 11.2 首版操作 allow-list

```text
resolve
find_records
load_context
copy_source
write_record
register_artifact
append_log
```

每次 Invocation 只执行一个 Runtime 操作。Harness 继续负责多步骤 Workflow、write-ahead State、Human Gate、Receipt 和恢复。

### 11.3 执行管线

```text
解析 Invocation Envelope
→ 加载并校验 Principal Registry
→ 复核 Principal Contract digest
→ 计算 Effective Capability
→ 校验 Domain / Active Profile / Mapping
→ 调用现有 Runtime Core
→ 复核结果路径、checksum 和 cardinality
→ 返回 Principal + Authorization Observation
```

`invoke` 不复制现有 Core 的存储、锁、原子写或读取实现。

### 11.4 成功结果

Principal-aware 结果增加：

```json
{
  "status": "ok",
  "principal": {
    "id": "ai-research-observatory-harness",
    "kind": "workload",
    "role": "domain_harness",
    "contract_digest": "sha256:..."
  },
  "authorization": {
    "operation": "write_record",
    "domain": "ai-research-observatory",
    "decision": "allowed",
    "registry_digest": "sha256:...",
    "policy_digest": "sha256:...",
    "profile_digest": "sha256:...",
    "mapping_digest": "sha256:..."
  },
  "result": {}
}
```

不适用的 digest 字段可以省略，但不能伪造为空字符串。

## 12. Query 与 Write 流程

### 12.1 Query

```text
Skill 或 Harness
→ invoke(find_records/load_context)
→ Principal Registry 校验
→ Domain Policy 校验
→ Active Profile 与预算校验
→ exact lookup/load
→ Context + Principal Observation
```

Skill 与 Harness 可以分别查询同一 Domain。每次结果保留自己的 Principal identity，不共享或传递调用权限。

### 12.2 Write

```text
Harness Promotion Plan
→ invoke(copy/write/register/log)
→ Principal 校验
→ Mapping Owner 校验
→ Contract/Mapping/Profile 产物交集校验
→ Runtime Core 原子操作
→ checksum + Principal Observation
→ Harness terminal Receipt
```

Principal-aware Promotion Plan 与 Receipt 至少绑定：

- `principal_id`；
- Principal Contract digest；
- Registry digest；
- Domain Policy digest；
- Active Profile digest；
- Mapping digest；
- Runtime version；
- 预期与实际内容 checksum。

任一绑定项变化使旧 Plan/Approval stale。

### 12.3 Skill 调用 Harness

Skill 调用 Harness 时存在两段身份：

```json
{
  "requested_by": {
    "principal_id": "ai-research-observatory",
    "kind": "skill"
  },
  "executed_by": {
    "principal_id": "ai-research-observatory-harness",
    "kind": "workload"
  }
}
```

`requested_by` 是 Harness 治理 artifact 中的 provenance，不向 `executed_by` 传递权限。Runtime 对物理操作审计 `executed_by` 的 Workload Principal。

## 13. Legacy / Operator Compatibility Interface

现有命令保持可用：

```text
write-record
find-records
load-context-pack
copy-source
register-artifact
append-log
```

它们明确归类为 `legacy/operator compatibility interface`。旧 Skill 在 `0.3.x` 中无需迁移，但没有通过 `invoke` 的结果不能宣称经过 Workload Principal 授权。

新 Harness 必须使用 `invoke`。Principal-aware 调用失败时不得静默回退到 Legacy CLI。未来版本可以迁移 Skill 到 `invoke`，但 `0.3.0` 不强制。

保留 Legacy CLI 是向后兼容，不代表 Runtime 提供了本机恶意进程隔离。能够直接修改 Domain Workspace 的本机进程本就超出 `0.3.0` 的协议身份边界。

## 14. 错误模型

稳定状态至少包括：

| 状态 | 含义 |
| --- | --- |
| `principal_not_found` | Registry 中不存在主体 |
| `principal_conflict` | 相同 ID 对应不同 kind 或不可自动接受的 Contract |
| `principal_contract_stale` | Manifest/SCP 已变化但尚未刷新 Registry |
| `principal_kind_unsupported` | 当前协议不支持该 kind |
| `principal_role_unsupported` | Workload role 不受支持 |
| `principal_domain_mismatch` | Principal 请求未声明的 Domain |
| `capability_denied` | Effective Capability 不允许本次操作 |
| `mapping_owner_mismatch` | Principal 不是 Mapping Owner |
| `profile_mismatch` | Principal、Mapping 与 Active Profile 不一致 |
| `operation_not_allowed` | 操作不在 Invocation allow-list |
| `invalid_invocation` | Envelope、字段、预算或路径不合法 |

错误 Envelope：

```json
{
  "status": "capability_denied",
  "principal_id": "ai-research-observatory-harness",
  "operation": "write_record",
  "retryable": false,
  "error": "...",
  "next_actions": []
}
```

规则：

- Principal-aware 写入失败一律 fail closed。
- `principal_not_found` 不得伪装成 Query `empty`。
- Query 是否继续原业务由 Contract 和 Harness/Skill 决定；Runtime 只返回真实状态。
- Invocation 失败不得回退到未绑定 Principal 的写命令。
- Runtime 成功、调用方状态不确定的窗口继续使用 checksum、幂等和 reconciliation 机制。
- 历史正文始终按 `data_only` 处理，Principal 类型不能提高正文信任等级。

## 15. 安全与信任边界

- Principal Manifest 是能力请求，不是最终授权。
- Host/Domain Policy 可以缩小或拒绝 Principal 声明，不能被 Manifest 扩大。
- Registry 与 Contract digest 提供版本绑定和审计，不提供密码学调用者认证。
- `0.3.0` 不声称能阻止拥有相同本机文件与进程权限的恶意程序伪造 `principal_id`。
- 用户内容、网页、历史记录和模型总结不能成为 executable、operation、flag、Profile、Mapping 或路径模板。
- Runtime/Adapter 必须继续限制 path traversal、symlink/junction 越界、超时、输出大小、文件数和上下文预算。
- Token、Cookie、环境变量和私人绝对路径不得进入持久领域记录或公开 artifact。
- Principal-aware 审计必须区分请求发起者 provenance 与实际 Runtime 执行者。

## 16. 测试策略

### 16.1 Contract 与 Registry

- 合法和非法 `principal.yml`；
- safe ID、kind、role、Domain、Trust 和产物约束；
- SCP 到 Skill Principal 的无损规范化；
- v0.1 Registry 到 v0.2 的只读兼容；
- 同 ID/同 digest 幂等；
- 同 ID/不同 digest 的 stale/刷新流程；
- 同 ID/不同 kind 冲突；
- `scan-scp` 保留 Workload Principal；
- 普通 Query 不产生隐式 Registry 写入。

### 16.2 Mapping 与授权

- `owner_principal_id` 正常校验；
- `owner_skill_id` 兼容校验；
- 两个 Owner 字段同时出现时拒绝；
- Skill 与 Harness 同 Domain 并存；
- 非 Owner Principal 写入被拒绝；
- Policy、Profile 或 Mapping 缩小权限时拒绝；
- Principal 自报能力不能覆盖 Host Policy。

### 16.3 Invocation

- 每种 allow-list 操作与直接调用 Runtime Core 的结果一致；
- 未知操作、malformed JSON 和超预算 Envelope 拒绝；
- 路径穿越、控制字符和非法配置引用拒绝；
- 输出包含正确 Principal、Policy、Profile、Mapping 和 Runtime Observation；
- `invoke` 失败不回退到 Legacy CLI；
- 现有 timeout、输出预算、cardinality、锁和原子写规则继续生效。

### 16.4 回归

- Runtime 当前全部测试继续通过；
- HR、Learning、AI Radar 等旧 SCP 示例无需修改；
- 现有 `write-record`、`find-records`、`load-context-pack` 等 CLI 行为保持兼容；
- Windows 路径、编码与原子临时文件测试继续通过；
- Registry 迁移与 Workload 注册不访问用户真实 Workspace。

### 16.5 Observatory 真实验收

在临时或专用 Workspace 中完成：

1. 不安装 Observatory Skill。
2. 注册 `ai-research-observatory-harness` Workload Principal。
3. 初始化 Observatory Domain Profile。
4. 通过 Harness 与 `invoke` 写入一条已批准的 `research_direction_revision`。
5. Receipt 绑定 Principal、Registry、Policy、Profile 和 Mapping digests。
6. 下一次 Harness 任务按 exact ref 召回该记录。
7. 随后注册 Observatory Skill Principal。
8. Skill 与 Harness 分别查询同一条记录。
9. Skill 使用 Harness Mapping 写入时被拒绝。
10. `0.2.0` 已完成 Receipt 所引用的记录在升级后仍可通过 Harness 只读召回；未执行的 `0.2.0` Plan/Approval 被判定为 stale。
11. Runtime Doctor、Observatory Memory Doctor 与两边回归测试通过。

## 17. 交付边界

`0.3.0` 按以下边界交付，但详细任务拆分由后续实施计划定义：

1. Principal Contract、canonical digest 与 Registry v0.2。
2. SCP Compatibility Adapter 与 Mapping v0.2 兼容。
3. `register-principal` 与 Principal Registry 诊断。
4. `invoke`、Effective Capability 与 Principal Observation。
5. 旧 CLI/SCP/Mapping 回归。
6. Observatory Workload Manifest、Harness Adapter 接入与真实闭环验收。
7. Runtime、Domain Skill 与 Harness 接入文档更新。

MCP、Semantic Search 和其他 Workload role 必须在 `0.3.0` 真实验收后另行设计，不得捆绑进入本次实现。

## 18. 验收标准

`0.3.0` 只有同时满足以下条件才能宣称完成：

1. Runtime 不再把 Skill 作为唯一主体抽象。
2. `skill` 与 `workload/domain_harness` 是并列 Principal。
3. Skill 与 Workload 进入同一个 Principal Registry 和授权模型。
4. Harness 不依赖 Skill 安装也能独立完成 Query 与受控写入。
5. Skill 与 Harness 可以同时接入同一 Domain Workspace。
6. 旧 SCP、Skill Registry 输入、`owner_skill_id` 和现有 CLI 保持兼容。
7. Principal-aware Invocation 在真实 Core 操作上执行授权，不是装饰性检查。
8. Mapping 只有一个 Owner Principal，非 Owner 写入被拒绝。
9. Principal Contract、Registry、Policy、Profile 或 Mapping 变化会使旧 Plan/Approval stale。
10. 写入失败关闭，Query 降级诚实，不出现 Principal-aware 到 Legacy 写入的静默回退。
11. Observatory 完成一次无 Skill 依赖的真实 Workload 闭环，并验证 Skill 与 Harness 共存。
12. `0.2.0` terminal complete Receipt 的记录保持只读可召回，未执行的旧 Plan/Approval 不得继续授权写入。
13. Runtime 现有 Profile、路径、锁、原子 IO、查询能力和全部兼容测试保持通过。
14. 文档明确 `0.3.0` 的 Principal 是协议身份而非密码学身份。
15. 没有引入 MCP、向量检索、多用户认证或新的存储核心。

## 19. 后续入口

本设计书面复核通过后，为 `0.3.0` 单独编写实施计划。实施计划必须先完成 Runtime 的 Principal 基础能力，再接入 Observatory Harness；不能先在 Observatory 中做绕过 Runtime 的局部模拟。
