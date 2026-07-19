# llm-wiki-runtime v0.1 边界与 v0.1.1 加固设计

本文档用于给当前实施阶段定边界，防止 `llm-wiki-runtime` 从 memory runtime 过早膨胀成通用 Skill Augmentation Framework。

## 1. 当前目标

v0.1 的目标不是做完整框架，而是把 memory 做实：

```text
让 first-party domain skills 能低成本、安全、可降级地读写自己的长期知识库。
```

第一阶段只证明一件事：

```text
skill 接入 llm-wiki memory 后，回答和执行是否真的比裸 skill 更稳。
```

## 2. 当前命名

v0.1 保持现有命名，不提前切换到 v0.2 框架叙事。

```text
SCP
  Skill Context Protocol。
  只描述 skill 如何接入 memory context。

llm-wiki-runtime
  确定性 CLI 执行层。
  负责 scope、profile、路径安全、锁、索引、日志、context pack。

llm-wiki-core skill
  安装在 Codex / Claude Code 等 agent shell 中的主动编排 skill。
  负责 init / ingest / query / maintain 的自然语言入口和 runtime CLI 编排。
```

暂不把 SCP 改名为 Skill Capability Protocol。只有当 trace / eval 等第二类 runtime 被真实实现后，才重新讨论协议命名。

## 3. v0.1 必须完成的闭环

v0.1 只围绕四个主动能力交付：

```text
init
  发现或初始化 domain 的 wiki scope。

ingest
  将有价值的数据写入 domain wiki。

query
  从当前 domain 和被授权的 supporting domain 读取 deterministic context pack。

maintain
  检查配置、profile、registry、权限、索引、日志和降级状态。
```

最小运行闭环：

```text
domain skill 运行
  -> 判断哪些数据有价值
  -> llm-wiki-core 调 runtime CLI 写入
  -> 下次 query 时 runtime 返回 context pack
  -> domain skill 基于历史上下文继续工作
```

## 4. v0.1 优先验证场景

优先验证两个 domain：

```text
Learning
  价值：验证“记得上次学到哪”。
  优点：数据不敏感，反馈周期短，适合证明 memory 是否有用。

HR
  价值：验证候选人、简历、JD、筛选批次是否能长期复用。
  风险：数据敏感，必须严格启用 privacy、readable_by 和 data_only 边界。
```

AI Radar 在 v0.1 中主要作为 supporting domain 使用，用于验证外部半可信资料如何被安全引用。

DevOps 可作为第二批接入，用于验证项目本地 scope、构建记录和发布记录的复用价值。

## 5. v0.1 必须包含的安全边界

### 5.1 profile snapshot

`init-profile` 必须把 active profile 快照到当前 scope：

```text
.llm-wiki/.meta/profile.yml
```

后续 `write-record` 和 `load-context-pack` 默认读取 scope 内 snapshot，而不是依赖原 skill 包路径。

### 5.2 trust 与 data_only

外部来源 domain，例如 AI Radar，必须默认：

```yaml
trust:
  level: external_untrusted
  instruction_policy: data_only
```

`data_only` 不是绝对安全承诺，而是三层约束：

```text
runtime
  确定性扫描、sanitized 标记、risk_flags 输出。

core
  只放入 supporting context，不放进 system/developer 指令区，不让其触发工具调用。

domain skill
  只按 usage_policy 允许的业务用途消费。
```

### 5.3 readable_by 反向授权

`supports` 是消费方声明，不足以防止数据外泄。v0.1.1 必须补充提供方授权：

```yaml
domain_policies:
  hr:
    readable_by: []
  learning:
    readable_by: [first_party]
  ai-radar:
    readable_by: ["*"]
```

规则：

1. 敏感 domain 默认 `readable_by: []`。
2. registry 生成时双向校验 `supports` 与 `readable_by`。
3. `load-context-pack` 在 CLI 层再次校验，防止绕过 registry。
4. 未授权读取返回结构化 fallback，不阻断原 skill 主流程。

## 6. v0.1.1 允许预留的接口

这些不是 v0.2 功能，只是低成本门框。现在不预留，后续升级会返工。

### 6.1 record metadata

所有 record 推荐预留：

```yaml
schema_version: v0.1
record_id: ""
created_at: ""
updated_at: ""
source_refs: []
trace_id: null
meta: {}
```

含义：

| 字段 | v0.1 用途 | v0.2 预留 |
| --- | --- | --- |
| `schema_version` | 记录当前 schema | 迁移判断 |
| `record_id` | 稳定引用 | trace/eval 引用 |
| `source_refs` | 来源可追踪 | trust 链 |
| `trace_id` | 默认为空 | 未来 trace-runtime join key |
| `meta` | 保留扩展 | 非业务元数据 |

### 6.2 CLI JSON 返回

所有公开 CLI 保持 JSON 输出，并允许包含：

```json
{
  "status": "ok",
  "warnings": [],
  "next_actions": [],
  "context_refs": []
}
```

`next_actions` 只是给 agent shell 的操作提示，不代表 runtime 自动执行后续动作。

`context_refs` 在 v0.1 中用于说明 context pack 引用了哪些文件、checksum 或版本；未来可作为 trace 输入。

### 6.3 context pack 元数据

`load-context-pack` 返回时应包含：

```json
{
  "included_count": 12,
  "excluded_count": 3,
  "items": [
    {
      "path": "domains/learning/plans/current.md",
      "checksum": "sha256:...",
      "schema_version": "v0.1",
      "trust_level": "user_owned",
      "instruction_policy": "trusted_content"
    }
  ]
}
```

排序必须确定性。调用方传入过滤条件时，只能缩小 profile read rules，不能扩大权限。

### 6.4 存储格式约束

v0.1 起就采用 sync-friendly 格式：

```text
一文件一记录。
append-only log 按时间分段。
registry / index / 聚合缓存视为可再生。
```

这不是要做同步功能，而是避免后续接 Git、Syncthing 或网盘同步时重构存储格式。

## 7. v0.2 Parking Lot

以下内容不进入 v0.1 或 v0.1.1 实施计划：

```text
trace-runtime
eval-runtime
validated_pattern
promote
autonomy 分级
compact
migrate
golden trace 回归
Skill Augmentation Framework 对外叙事
SCP 改名为 Skill Capability Protocol
```

这些不是被否定，而是等待 v0.1 的真实使用证据。

## 8. v0.2 启动门槛

只有满足以下条件，才启动 v0.2 设计和实现：

1. 至少一个 first-party skill 连续真实使用 v0.1 memory runtime 1-2 周。
2. 使用记录证明 context pack 能稳定改善回答或执行效果。
3. 用户确实能感知“它记得上次的上下文”，而不是每次都从零开始。
4. `init / ingest / query / maintain` 主路径稳定，fallback 不打扰主流程。
5. v0.1 的 record 模型已经足够稳定，不再频繁改 schema。

在此之前，v0.2 文档只作为 vision 和 parking lot，不作为实施入口。

## 9. 验收标准

v0.1 / v0.1.1 阶段满足：

1. HR、Learning 至少一个 domain 能完成 init / ingest / query / maintain 闭环。
2. AI Radar 可作为 `data_only` supporting domain 被安全读取。
3. HR 默认不能被任何其他 domain 跨域读取，除非 host policy 显式授权。
4. 所有 CLI 返回结构化 JSON，并保留 `warnings` 与 `next_actions`。
5. context pack 返回 included/excluded 统计和 context refs。
6. record metadata 预留 `schema_version`、`record_id`、`source_refs`、`trace_id`、`meta`。
7. `.meta` 作为保留目录存在，但不实现 trace-runtime。
8. v0.2 parking lot 中的能力不进入当前实施计划。

## 10. 决策原则

```text
v0.1 做 memory。
v0.1.1 留接口。
v0.2 等真实数据证明后再启动。
```

这条原则优先级高于任何框架叙事。
