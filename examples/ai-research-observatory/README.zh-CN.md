# AI Research Observatory：Runtime 0.3 Skill+Harness 参考

本目录是给 LLM 读取、复制和验证的参考包，不是运行时依赖。Runtime 不会从这里自动加载 Profile、Principal、SCP、Mapping 或请求文件，也不得把本目录加入 package data。

## 内容性质

- `contracts/*.yml`：来自 AI Research Observatory 固定 commit 的逐字节快照。
- `snapshot-manifest.json`：记录源仓库、commit、源路径和文件 SHA-256；不是 Runtime Contract。
- `requests/**/*.json`：结构有效的 Invocation 模板，替换占位值后才可执行。
- `expected-outcomes.md`：稳定状态与安全断言，不固定动态 digest。

不提供生成后的 Principal Registry、active Profile、Plan、Approval、Receipt、Workspace 或 `.llm-wiki` 内容。这些都必须在临时或专用 Workspace 中由真实流程产生。

## 两个独立 Principal

| Caller | Principal ID | Domain | 写所有权 |
| --- | --- | --- | --- |
| Skill | `ai-research-observatory` | `ai-research-observatory` | 无 Observatory Memory Mapping |
| Harness | `ai-research-observatory-harness` | `ai-research-observatory` | `ai-research-observatory-memory` |

Harness 能在未安装、未发现或未注册 Skill 时独立运行。两者可以查询同一条已接受记录，但 Skill 不得借用 Harness Mapping 写入。

## 使用顺序

1. 把 `contracts/` 复制到目标 Harness 的受版本控制资产目录。
2. 为新 Domain 重新推导 ID、Trust、产物、路径和预算；不能只改名字。
3. 初始化 Domain Workspace 的 active Profile。
4. 注册 Harness `principal.yml`，不要先扫描 Skill。
5. 校验 v0.2 Mapping，并执行 Harness `resolve`。
6. 完成 Harness 的 Review、Plan 和 Human Gate。
7. 依次通过 `llm-wiki invoke` 执行 copy、write、log、find 和 load。
8. 最后可选扫描 `scp.yml`，验证 Skill/Harness 共存与写入隔离。

## 占位值

执行请求前必须替换所有双下划线占位值：

| 占位值 | 含义 |
| --- | --- |
| `__ABSOLUTE_DOMAIN_WORKSPACE__` | 已初始化的绝对 Domain Workspace |
| `__ABSOLUTE_EVIDENCE_SNAPSHOT__` | 已冻结、已审查 Evidence Snapshot 的绝对路径 |
| `__ABSOLUTE_APPROVED_RECORD_CONTENT__` | 与批准 Plan digest 绑定的记录正文绝对路径 |

每个请求还必须使用本次执行唯一的 safe `request_id`。不要使用字符串求值拼接命令。

## 命令边界

注册 Harness：

```powershell
llm-wiki register-principal `
  --manifest <absolute-principal-yml> `
  --registry-path <absolute-principal-registry-json>
```

初始化 active Profile 后执行请求：

```powershell
llm-wiki invoke `
  --request <absolute-request-json> `
  --registry-path <absolute-principal-registry-json> `
  --profile-path <absolute-profile-yml> `
  --mapping-path <absolute-ingest-mapping-yml>
```

Harness 的读请求显式携带 Mapping，是为了把 Mapping digest 纳入授权 observation。Skill 查询使用 `ai-research-observatory` 身份并省略 Harness Mapping。

`skill/20-write-record-denied.request.json` 是负向验收，不是业务命令。预期结果为 `mapping_owner_mismatch`；目标记录 checksum 必须不变。不得在失败后调用 legacy `write-record`、`copy-source` 或 `append-log`。

## 参考快照更新

只有在 Observatory 的真实契约有意升级并且 Runtime E2E 已验证后才更新快照：

1. 记录新的完整 commit；
2. 逐字节复制四份资产；
3. 更新 manifest 中的源路径和 SHA-256；
4. 运行 reference example、Principal、Mapping、Invocation 和全量回归测试；
5. 在同一变更中解释协议差异。

不要让 CI 依赖相邻的 Observatory checkout；manifest 提供可审计溯源，Runtime 测试只消费仓库内快照。
