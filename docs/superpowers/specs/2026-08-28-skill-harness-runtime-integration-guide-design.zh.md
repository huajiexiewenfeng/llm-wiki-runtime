# Skill + Harness 接入 LLM Wiki Runtime 0.3 通用手册设计

- 状态：已批准
- 日期：2026-08-28
- Runtime 基线：`0.3.0`
- 完整参考：AI Research Observatory
- Skill-only 对照：HR

## 1. 目标

在 `llm-wiki-runtime` 中提供一套可由 LLM 直接读取和执行的接入材料。LLM 必须先审计目标项目的真实调用主体、持久数据和治理边界，再选择 Skill-only、Harness-only 或 Skill+Harness，最后按所选模式实施并完成临时 Workspace 验收。

交付由两部分组成：

1. `docs/guides/skill-harness-llm-wiki-runtime-integration.zh.md`：权威评估与实施手册。
2. `examples/ai-research-observatory/`：Runtime 0.3 Skill+Harness 的自包含参考快照、Invocation 模板和预期结果。

## 2. 决策树

```text
项目是否需要跨任务持久知识？
├─ 否：不接入 Runtime
└─ 是
   └─ 哪些主体直接调用 Runtime？
      ├─ 只有 Domain Skill：Skill-only
      ├─ 只有独立 CLI/Scheduler/Service/Harness：Harness-only
      └─ 同时存在 Skill 与独立 Harness：Skill+Harness
```

判定不能依赖文件名。存在 `SKILL.md` 不代表实际写入主体一定是 Skill；承担长期运行、Plan、Human Gate、Receipt、恢复或 Scheduler/CLI 执行的组件应建模为独立 `workload/domain_harness` Principal。

## 3. 模式不变量

### 3.1 Skill-only

- 使用 SCP 注册 Skill Principal。
- Mapping 归实际写入的 Skill Principal。
- 既有 Skill 可以继续通过 Runtime 0.3 的 legacy/operator compatibility interface 运行。
- HR 是该模式的兼容对照，不是新 Harness 模板。

### 3.2 Harness-only

- 使用 `principal.yml` 注册 `workload/domain_harness`。
- 不为兼容形式创建伪装 Skill。
- Mapping 使用 v0.2 `owner_principal_id` 并归 Harness。
- 所有知识操作使用 `llm-wiki invoke`。
- Invocation 失败不得回退到 legacy 写命令。

### 3.3 Skill+Harness

- Skill 与 Harness 使用不同 Principal ID。
- 二者可以共享 Domain、Profile、Workspace 和已接受记录。
- 二者分别以自己的 Principal 身份查询。
- 受治理 Promotion Mapping 归 Harness；Skill 不得借用它写入。
- Harness 在未安装或未注册 Skill 时必须独立运行。

## 4. 权威手册结构

手册按以下章节组织：

1. LLM 执行协议：先评估、后选型、再修改；禁止直接写 `.llm-wiki`。
2. 接入前盘点：Skill、CLI、Scheduler、Adapter、Workspace、审批、恢复和现有契约。
3. 模式决策树：输出 `detected_mode` 与选择证据。
4. 身份与职责：区分 Domain、Principal、Interface 和 Mapping Owner。
5. 三种模式的最小资产与禁止项。
6. 从领域需求推导 Profile、SCP、Principal 和 Mapping。
7. Runtime 0.3 Registry、Invocation、错误和无 legacy fallback 规则。
8. 分模式实施顺序与第一次真实闭环。
9. Observatory 完整案例。
10. HR Skill-only 兼容对照。
11. 测试、验收与快照漂移管理。
12. 非目标。

LLM 在修改目标项目前必须先输出：

```text
detected_mode
runtime_callers
principal_ids
domain
workspace_owner
mapping_owner
query_path
write_path
fallback_policy
existing_assets
missing_assets
selected_reference
```

## 5. Observatory 示例目录

```text
examples/ai-research-observatory/
├── README.zh-CN.md
├── snapshot-manifest.json
├── contracts/
│   ├── principal.yml
│   ├── scp.yml
│   ├── llm-wiki-profile.yml
│   └── ingest-mapping.yml
├── requests/
│   ├── harness/
│   │   ├── 00-resolve.request.json
│   │   ├── 10-copy-source.request.json
│   │   ├── 20-write-record.request.json
│   │   ├── 30-append-log.request.json
│   │   ├── 40-find-records.request.json
│   │   └── 50-load-context.request.json
│   └── skill/
│       ├── 10-find-records.request.json
│       └── 20-write-record-denied.request.json
└── expected-outcomes.md
```

- `contracts/*.yml` 是 Observatory commit `b9c9bc6a04f5a9efeea7d7b8840bec370f61d69c` 的逐字节真实快照。
- `snapshot-manifest.json` 记录源仓库、commit、源路径和 SHA-256，但不是 Runtime 协议或运行依赖。
- `requests/**/*.json` 是结构有效、需要替换明确字符串占位值的 Invocation 模板。
- README 解释注册、初始化、命令 flags、占位值和调用顺序。
- `expected-outcomes.md` 记录稳定状态与断言，不保存易漂移的 Registry 或 digest 输出。
- 不提交生成后的 Registry、active Profile、Plan、Approval、Receipt、Workspace 或 `.llm-wiki` 内容。

## 6. HR 对照规则

接入模式与 Runtime 版本是两个维度：

| 案例 | 身份拓扑 | 调用边界 | 定位 |
| --- | --- | --- | --- |
| HR | Skill-only | 源自 0.1 的 SCP/legacy 模式，由 0.3 兼容 | Skill-only 对照 |
| Observatory Harness | Harness-only 能力 | 0.3 `principal.yml` + `invoke` | 独立 Workload 参考 |
| Observatory 完整形态 | Skill+Harness | 两个 Principal；Harness 写、双方查 | 0.3 完整案例 |

HR 的 `owner_skill_id` 不得复制给新 Harness；legacy CLI 保留也不表示 Workload 可以在 Invocation 失败后回退。

## 7. 最小测试与验收

1. 快照清单的源 commit、路径和 SHA-256 与示例文件一致。
2. Skill ID 与 Harness ID 不同，Domain/Profile 相同。
3. Mapping 为 v0.2，仅有 `owner_principal_id`，Owner 为 Harness。
4. Profile、Principal、SCP 与 Mapping 的产物集合相容。
5. 仅注册 Harness 即可在临时 Workspace 中 resolve、写入和查询。
6. Harness 完成 `copy_source → write_record → append_log → find_records → load_context`。
7. 后扫描 SCP 时保留 Harness 并增加 Skill Principal。
8. Skill 和 Harness 分别查询同一记录。
9. Skill 借用 Harness Mapping 写入返回 `mapping_owner_mismatch`，目标 checksum 不变。
10. pending Plan 在绑定 digest 改变后 stale；terminal complete 0.2 Receipt 只读召回且不重写。
11. Invocation 失败不触发 legacy 写命令。
12. 测试只使用临时 Workspace，不依赖相邻 Observatory checkout。

## 8. 文档入口

更新：

- `README.md`
- `README.zh-CN.md`
- `docs/guides/domain-skill-integration-quickstart.zh.md`
- `docs/guides/hr-llm-wiki-integration.zh.md`
- `docs/guides/hr-skill-llm-wiki-runtime-implementation.zh.md`
- `docs/methodology/professional-skill-dual-loop-engineering.zh.md`

现有 5 分钟手册收窄为 Skill-only 快速入口，并在开头路由到新权威手册。HR 文档增加版本与兼容边界横幅。

## 9. 非目标

首版不增加 MCP、向量检索、Catalog/Shard、多 View、多用户认证、密码学 Principal、Scheduler、daemon、新 Principal kind/role、自动 Promotion、跨 Domain 写入或第二套存储/事务系统。示例不成为 Runtime 运行依赖，也不增加对 Observatory 仓库的 CI 强依赖。
