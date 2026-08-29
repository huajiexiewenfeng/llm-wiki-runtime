# Skill + Harness 接入 llm-wiki-runtime 0.3：LLM 评估与实施手册

本文不是供人逐条照抄的 CLI 教程，而是一份交给编码 LLM 的执行协议。LLM 必须先审计目标项目，再选择 Skill-only、Harness-only 或 Skill+Harness；不能因为项目中存在 `SKILL.md` 就默认由 Skill 拥有所有 Runtime 权限。

Runtime 0.3 的核心不变量是：

> Domain、Principal 与 Interface 是三个不同概念。Skill 和 `workload/domain_harness` 是并列 Principal；它们可以查询同一 Domain，但不能共享身份或借用对方的 Mapping 写入。

完整 Runtime 0.3 参考位于 `examples/ai-research-observatory/`。HR 文档记录的是源自 Runtime 0.1、由 Runtime 0.3 兼容层继续支持的 Skill-only 模式。

## 0. LLM 执行协议

在修改目标项目之前完成以下动作：

1. 读取所有业务入口、`SKILL.md`、CLI、Scheduler、Service、Adapter 和知识契约。
2. 确认哪个组件实际执行 Query，哪个组件执行持久写入。
3. 确认是否存在 Plan、Human Gate、Receipt、恢复或长期独立运行要求。
4. 输出下列评估记录，获得项目范围内的一致结论后再修改文件：

```text
detected_mode: skill_only | harness_only | skill_plus_harness | no_integration
runtime_callers: [实际调用 Runtime 的组件]
principal_ids: [每个调用主体的稳定 ID]
domain: <知识 Domain>
workspace_owner: <负责选择和维护 Domain Workspace 的组件>
mapping_owner: <实际执行该写入管线的 Principal>
query_path: <Skill、Harness 或二者>
write_path: <唯一受治理写入主体>
fallback_policy: <查询/原业务的诚实降级；持久写入必须 fail closed>
existing_assets: [Profile、SCP、Principal、Mapping、Adapter、测试]
missing_assets: [按所选模式缺少的资产]
selected_reference: hr_skill_only | observatory_runtime_0_3
```

禁止事项：

- Skill、Harness 或示例脚本直接写 `.llm-wiki`。
- 为了复用权限让两个组件使用同一个 Principal ID。
- 把 `examples/**` 当作 Runtime 运行时配置源或包资源。
- 在 Workload Invocation 失败后调用 legacy 写命令。
- 把 Query 的 `principal_not_found` 或授权错误报告为空结果。

## 1. 接入前项目盘点

LLM 应使用只读检查回答以下问题：

| 检查面 | 必须查明的事实 |
| --- | --- |
| 业务入口 | 自然语言 Skill、CLI、Scheduler、后台 Service 是否能分别启动 |
| 生命周期 | 调用主体是否必须在未安装 Skill 时独立运行 |
| 知识类型 | 要保存的 record、artifact、log、source 类型及其来源 |
| 治理 | 是否有 Review、Plan digest、Human Approval、Receipt、恢复 |
| Workspace | 源码仓库和持久 Domain Workspace 是否分离 |
| 查询 | 精确 identity、窄范围过滤、预算和 `data_only` Review |
| 写入 | 谁生成候选、谁批准、谁最终调用 Runtime |
| 兼容 | 是否已有 v0.1 SCP、v0.1 Mapping 或 legacy CLI 调用 |
| 失败 | Runtime 不可用时原业务如何继续，写入如何失败关闭 |

若项目只需要一次性缓存、无需跨任务复用或不能定义稳定来源与 Review，则输出 `no_integration`，不要增加 Runtime 资产。

## 2. Skill-only、Harness-only、Skill+Harness 决策树

```text
需要跨任务持久知识？
├─ 否 → no_integration
└─ 是
   └─ 哪些主体直接调用 Runtime？
      ├─ 只有 Domain Skill
      │  └─ Skill-only
      │     ├─ SCP 注册 Skill Principal
      │     └─ Mapping 归实际写入的 Skill Principal
      ├─ 只有独立 CLI / Scheduler / Service / Harness
      │  └─ Harness-only
      │     ├─ principal.yml 注册 workload/domain_harness
      │     ├─ 不创建伪装 Skill
      │     └─ Mapping 归 Harness，所有知识操作走 invoke
      └─ Skill 与独立 Harness 都会调用 Runtime
         └─ Skill+Harness
            ├─ 两个不同 Principal ID
            ├─ 共享 Domain、Profile、Workspace 和已接受记录
            ├─ 分别以自己的身份 Query
            └─ 受治理 Promotion Mapping 归 Harness
```

强制判定信号：

- 需要在未安装 Skill 时由 CLI、Scheduler 或 Service 继续运行：至少是 Harness-only。
- Skill 只负责自然语言入口和领域判断，Harness 负责 Plan、Gate、Receipt、恢复：Skill+Harness。
- 没有独立进程或治理组件，所有 Query/写入都由 Skill 生命周期执行：Skill-only。

每份 Mapping 只有一个 Owner。确有两条独立写入管线时建立两份不同 Mapping，并分别证明产物边界；不要共享 Principal。

## 3. Domain、Principal、Interface 与 Mapping Owner

```text
Domain != Principal != Interface
```

- Domain：知识所属领域，例如 `ai-research-observatory`。
- Principal：向 Runtime 请求能力的逻辑主体。
- Interface：CLI、Python Adapter 或未来其他调用界面，不是身份。
- Mapping Owner：被允许执行该 Mapping 产物写入的唯一 Principal。

有效能力不是由 `kind` 或 `role` 自动授予：

```text
Effective Capability
= Principal Contract 声明
∩ Principal Registry 当前条目
∩ Host/Domain Policy
∩ Active Profile
∩ Ingest Mapping（写入时）
```

Observatory 的身份分工：

| Caller | Principal ID | 职责 | Mapping 写所有权 |
| --- | --- | --- | --- |
| Skill | `ai-research-observatory` | 自然语言入口、Evidence 解释、研究判断 | 无 |
| Harness | `ai-research-observatory-harness` | Workflow、Plan、Human Gate、Promotion、Receipt、恢复 | `ai-research-observatory-memory` |

两者都能查询已接受的 `research_direction_revision`。Skill 使用 Harness Mapping 写入必须得到 `mapping_owner_mismatch`。

## 4. 三种模式的最小接入资产

### Skill-only

```text
domain-package/
├── llm-wiki-profile.yml
├── ingest-mapping.yml       # 既有兼容模式可为 v0.1 owner_skill_id
└── business-skill/
    ├── SKILL.md
    └── scp.yml
```

既有 Skill 可继续使用 Runtime 0.3 的 legacy/operator compatibility interface。不要据此推导新 Harness 也可使用 legacy 写入。

### Harness-only

```text
harness-package/
├── principal.yml
├── llm-wiki-profile.yml
├── ingest-mapping.yml       # v0.2 owner_principal_id
├── runtime-adapter
└── workflow / plan / receipt / recovery
```

Harness 不需要 `scp.yml`，也不能扫描一个伪 Skill 作为自身前置条件。

### Skill+Harness

```text
domain-package/
├── principal.yml            # Harness Workload
├── scp.yml                  # 独立 Skill
├── llm-wiki-profile.yml
├── ingest-mapping.yml       # Harness-owned v0.2 Mapping
├── runtime-adapter
└── workflow contracts
```

`principal.yml` 与 `scp.yml` 是独立合同，不能由其中一份动态生成另一份。Registry 顶层 `skills` 只是从 `principals` 生成的兼容投影。

## 5. 从领域需求推导四类契约

按以下顺序推导，不先复制 YAML：

1. 列出需要长期保存和精确读回的 record/log/artifact。
2. 为每种产物确定 stable ID、路径变量、required refs、写模式和查询预算。
3. 用 Profile 声明物理能力。
4. 用 SCP 或 Principal 声明调用主体请求的 Domain、Trust、Query 和产物。
5. 用 Mapping 选择该写入管线允许产生的最小子集。

交叉校验：

```text
Mapping products ⊆ Principal/SCP products
Mapping products ⊆ Profile records/artifacts/logs
Mapping domain == Principal domain == Profile id
Mapping owner == 实际执行写入的 Principal
```

新 Workload Mapping 必须使用：

```yaml
mapping:
  id: my-domain-memory
  version: v0.2
  domain: my-domain
  owner_principal_id: my-domain-harness
  source_types: [approved_result]
  instruction_ref: path/to/domain/instructions
produces:
  - record_type: knowledge_revision
  - log_type: domain_memory_event
```

不得同时出现 `owner_skill_id` 与 `owner_principal_id`。Principal Manifest 是能力请求，不是密码学凭证，也不能覆盖 Host Policy。

## 6. Runtime 0.3 Registry 与 Principal Invocation

先注册 Harness：

```powershell
llm-wiki register-principal `
  --manifest <absolute-principal-yml> `
  --registry-path <absolute-principal-registry-json>
```

Skill 可以随后通过兼容入口注册，且必须保留 Workload：

```powershell
llm-wiki scan-scp `
  --scp-path-json '["<absolute-scp-yml>"]' `
  --write `
  --output <absolute-principal-registry-json>
```

Workload 每次知识操作使用一个 Invocation Envelope：

```json
{
  "protocol_version": "v0.1",
  "request_id": "stable-safe-request-id",
  "principal_id": "my-domain-harness",
  "operation": "find_records",
  "scope_root": "C:\\absolute\\domain-workspace",
  "payload": {
    "record_type": "knowledge_revision",
    "lookup_value": "record-001",
    "target_domain": "my-domain"
  }
}
```

```powershell
llm-wiki invoke `
  --request <absolute-request-json> `
  --registry-path <absolute-principal-registry-json> `
  --profile-path <absolute-profile-yml>
```

写入必须同时提供 `mapping_id`、`--mapping-path` 和 `--profile-path`。Runtime 会核验 packaged Profile 与 active Profile digest 相同。Harness 为了把 Mapping digest 绑定进 Plan/Receipt，也可以在 `resolve`、`find_records` 和 `load_context` 中显式携带 Mapping。

首版 allow-list：

```text
resolve
find_records
load_context
copy_source
write_record
register_artifact
append_log
```

外层 `status: ok` 表示 Principal-aware Invocation 已授权并执行；真实 Core 结果位于 `result`。调用方必须校验返回的 Principal identity、operation、domain 和适用的 Registry、Policy、Profile、Mapping digest。

## 7. 分模式实施顺序

### Skill-only

```text
Profile + SCP + Skill-owned Mapping
→ scan-scp
→ validate-mapping
→ 原 Skill preflight Query
→ 原业务
→ Human 确认
→ compatibility write
→ 下一次 Query
```

### Harness-only

```text
Profile + principal.yml + Harness-owned v0.2 Mapping
→ init-profile
→ register-principal
→ validate-mapping
→ invoke(resolve)
→ Harness Query / Review / Plan / Human Gate
→ invoke(copy/write/log)
→ exact read-back
→ terminal Receipt
```

### Skill+Harness

```text
先证明 Harness 在没有 Skill 时独立闭环
→ 再 scan-scp 注册 Skill
→ 分别以 Skill/Harness Query 同一记录
→ 证明 Skill 使用 Harness Mapping 写入被拒绝
→ 证明已完成 Receipt 不被重写
```

Skill 发起 Harness 工作流时，`requested_by` 只是 Harness artifact 中的 provenance；Runtime 对物理操作审计 `executed_by` Harness Principal，前者不向后者传递权限。

## 8. 失败、恢复与升级

- Query 失败可以按合同让原业务诚实降级，但必须报告“本次未使用长期知识”。
- 持久写入失败关闭；Workload Invocation 失败时不得回退到 `copy-source`、`write-record`、`append-log` 等 legacy 命令。
- `principal_not_found`、`principal_contract_stale`、`profile_mismatch` 和 `mapping_owner_mismatch` 不是空结果。
- Principal Contract、Registry、Policy、Profile 或 Mapping digest 改变后，未执行 Plan/Approval stale。
- Runtime 0.2 terminal complete Receipt 引用的记录可以在 0.3 通过当前 Principal-aware Query 只读召回，但不得重写历史 Plan/Receipt。
- `already_exists` 只有在现存 checksum 等于 approved checksum 时才是幂等成功。
- Runtime 成功而 Harness 状态不确定时，先 reconciliation，不盲目重放非幂等步骤。

## 9. Observatory Skill+Harness 完整参考

参考目录：`examples/ai-research-observatory/`。

四份 `contracts/*.yml` 是 Observatory commit `b9c9bc6a04f5a9efeea7d7b8840bec370f61d69c` 的逐字节快照。`snapshot-manifest.json` 绑定源路径和 SHA-256；它不是 Runtime 协议。

Harness 真实知识操作顺序：

```text
resolve
→ copy_source
→ write_record
→ append_log
→ find_records
→ load_context
```

完整验收顺序：

1. Registry 初始只包含 `ai-research-observatory-harness`。
2. Harness 写入并读回一条 `research_direction_revision`。
3. Receipt 绑定 Workload Principal 和四个授权 digest。
4. 扫描 `scp.yml` 后 Registry 同时包含 Skill 与 Harness。
5. Skill 以自己的身份查询同一记录。
6. Skill 借用 `ai-research-observatory-memory` 写入返回 `mapping_owner_mismatch`。
7. 记录 checksum 不变；失败后没有 legacy 写命令。

复制到新 Domain 时，必须重新推导所有 ID、产物、路径、Trust 和预算。不要只做字符串替换后宣布接入完成。

## 10. HR Skill-only 兼容对照

HR 示例的来源是 Runtime 0.1 Skill-only 集成，Runtime 0.2/0.3 继续兼容其 SCP、`owner_skill_id` 和 legacy/operator CLI。它证明既有 Skill 可以平滑运行，不证明以下能力：

- Workload `principal.yml`；
- Harness 未安装 Skill 时独立运行；
- v0.2 `owner_principal_id` Mapping；
- Principal-aware `llm-wiki invoke`；
- Skill/Harness 共存与 Mapping 隔离。

因此：

| 参考 | 模式 | 用途 |
| --- | --- | --- |
| HR | Skill-only compatibility | 维护既有 SCP/legacy 接入 |
| Observatory Harness | Harness-only capability | 新独立 Workload 接入 |
| Observatory 完整案例 | Skill+Harness | Runtime 0.3 权威参考 |

不得把 HR legacy 写命令当作新 Harness 的降级路径。

## 11. 测试与最终验收

### 静态合同

- Skill 与 Harness Principal ID 不同，Domain/Profile 相同。
- Mapping 为 v0.2，只由 Harness 拥有。
- Profile、Principal、SCP、Mapping 产物相容。
- 示例快照 bytes 与 manifest SHA-256 相同。
- 请求模板仅使用 Invocation allow-list 和准确 payload 字段。

### 临时 Workspace E2E

- 无 Skill 注册时 Harness 可 resolve、写入、查询。
- Skill 注册后不删除 Harness。
- 二者查询同一条记录。
- Skill 借用 Harness Mapping 写入被拒绝且 checksum 不变。
- 所有测试文件仅位于 pytest 临时目录。

### 回归

- Principal、Registry、Mapping、Authorization、Invocation、CLI 和 Skill package 测试通过。
- 旧 SCP、v0.1 Mapping 和 legacy CLI 行为保持兼容。
- `examples/**` 未加入 package data、应用 import 或默认配置解析。
- Runtime 全量测试通过且 `git diff --check` 无错误。

## 12. 非目标

首版不增加：

- MCP Server 或其他新 Interface；
- 向量检索、Embedding、通用语义搜索；
- Catalog、Shard、多 View 索引；
- Scheduler、daemon、watcher；
- 多用户认证、密码学 Principal 或 OS workload identity；
- 新 Principal kind/role；
- 自动 Promotion、无人审批写入；
- 跨 Domain 写入；
- 第二套存储、锁、事务或 Receipt 引擎；
- 对 Observatory 仓库的 CI 强依赖；
- 把示例变成 Runtime 运行依赖。
