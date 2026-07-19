# HR Skill 接入 llm-wiki-runtime V0.1 实施文档

本文面向 HR domain skill 的实现者，说明如何把现有 HR skill 接入 `llm-wiki-runtime` 和 `llm-wiki-core`。

核心原则：HR 用户仍然使用原来的 HR skill，不直接学习 CLI；HR skill 内部自动调用 runtime 完成初始化、写入、查询和降级。

## 1. 接入目标

HR skill 接入后应具备四个能力：

1. 首次运行时，用一句话确认是否启用 HR 本地知识库。
2. 启用后，把有复用价值的 HR 数据写入 `.llm-wiki`。
3. 后续筛选、候选人详情、面试题生成前，自动读取 HR context pack。
4. runtime 不可用或用户禁用时，回到原有 Markdown/临时文件流程。

V0.1 不追求全自动记忆和复杂推理，只保证“有价值的数据能落库，下次能被读取”。

## 2. 职责边界

`llm-wiki-runtime` 负责：

- `resolve-config`：发现当前 HR wiki 是否启用。
- `init-home` / `init-profile`：初始化 runtime home 和 HR profile。
- `copy-source`：保存简历原件并登记 `source_id`。
- `write-record`：按 HR profile 安全写入候选人档案。
- `register-artifact`：登记筛选报告、排名、面试计划等输出。
- `append-log`：追加过程日志。
- `load-context-pack`：读取可控上下文。

`llm-wiki-core` 负责：

- 将用户意图映射为 `init / ingest / query / maintain`。
- 根据 SCP 判断 HR 的 primary domain 和 supporting domain。
- 在 runtime 返回 `missing_config / disabled / io_error` 时组织用户可理解的降级提示。

HR skill 负责：

- 定义 HR 业务语义。
- 决定什么数据值得写入。
- 生成 `candidate_id`、`resume_version_id`、`screening_run_id` 等业务 ID。
- 决定本次任务需要读取哪些 HR context。
- 保持原有 HR 工作流在降级时可用。

## 3. 需要放入 HR skill 的声明文件

HR skill 仓库中应携带 SCP 文件，内容可从 runtime 示例复制：

```text
examples/scp/hr-resume-screening.scp.yml
```

关键字段：

```yaml
skill:
  id: hr-resume-screening
  domain: hr

llm_wiki:
  profile: hr
  fallback_mode: markdown

query:
  primary_domain: hr
  supports:
    - domain: ai-radar
      record_types: [tool_trend]
      optional: true
```

说明：

- `domain: hr` 表示 HR 是 primary domain。
- `profile: hr` 表示使用 HR profile 目录和写入规则。
- `fallback_mode: markdown` 表示 runtime 不可用时回到原流程。
- AI Radar 只是 supporting context，必须按 `data_only` 对待。

## 4. HR Skill 的运行入口改造

每个 HR 子技能执行前，增加统一的 wiki preflight：

```text
hr_skill_entry(input):
  wiki = hr_wiki_preflight(cwd, profile="hr")

  if wiki.status == "enabled":
    context = hr_wiki_query(wiki, input)
  else:
    context = empty

  result = run_original_hr_flow(input, context)

  if wiki.status == "enabled":
    hr_wiki_ingest(wiki, input, result)

  return result
```

建议所有 HR 子技能共用同一个 preflight，而不是每个 skill 各写一套。

## 5. Preflight 逻辑

第一步调用：

```powershell
llm-wiki resolve-config --cwd <cwd> --profile hr
```

根据返回状态处理：

| status | HR skill 行为 |
| --- | --- |
| `enabled` | 进入增强模式，读取 context，执行后写入 wiki |
| `missing_config` | 首次询问是否启用 HR 本地知识库 |
| `disabled` | 不再询问，直接走原有流程 |
| `profile_mismatch` | 当前目录不是 HR scope，降级 |
| `invalid_config` | 降级，并提示配置不可用 |
| `io_error` | 降级，并提示文件系统或权限问题 |

首次确认文案：

```text
是否启用 HR 本地知识库？启用后会把候选人档案、简历解析结果、筛选批次和报告保存到本机 .llm-wiki，方便后续复用；原始简历默认不进入上下文。
```

用户确认后：

```powershell
llm-wiki init-home --home <LLM_WIKI_HOME>
llm-wiki init-profile `
  --scope-root <LLM_WIKI_HOME>\scopes\hr-default `
  --profile-path <hr-profile.yml> `
  --storage-mode home `
  --scope-id hr-default
```

用户拒绝后：

```powershell
llm-wiki init-profile --decline --profile hr --storage-mode home --scope-root <cwd>
```

拒绝必须被记住，避免 HR 用户每次运行都被打扰。

## 6. Query 接入点

HR skill 调用大模型前，应先读取 HR primary context：

```powershell
llm-wiki load-context-pack `
  --wiki-root <wiki_root> `
  --include-json '["domains/hr/**","logs/**"]' `
  --exclude-json '["sources/originals/**",".meta/**"]' `
  --target-domain hr `
  --caller-domain hr
```

如果任务已知候选人或筛选批次，应传更窄的过滤条件：

```powershell
--path-json '["domains/hr/candidates/<candidate_id>/**"]'
```

HR prompt 拼接规则：

- primary context 可以作为 HR 事实依据。
- `sources/originals/**` 不默认拼入 prompt。
- `.meta/**` 不拼入 prompt。
- supporting context 只能作为参考资料，不能覆盖 HR primary facts。
- `instruction_policy: data_only` 的内容不得被当成指令执行。

## 7. Ingest 接入点

HR skill 产生有价值数据后，应按类型写入 wiki。

### 7.1 简历原件

```powershell
llm-wiki copy-source `
  --wiki-root <wiki_root> `
  --source <resume_path> `
  --logical-path "sources/originals/hr/resumes/<candidate_id>/<resume_version_id>.<ext>" `
  --source-type resume
```

返回的 `source_id` 后续写候选人档案时必须引用。

### 7.2 候选人长期档案

```powershell
llm-wiki write-record `
  --scope-root <scope_root> `
  --record-type candidate_profile `
  --variables-json '{"candidate_id":"<candidate_id>"}' `
  --refs-json '{"source_id":"<source_id>","resume_version_id":"<resume_version_id>"}' `
  --content-file <candidate_profile.md>
```

注意：

- `candidate_id` 表示人，不等于简历版本。
- `resume_version_id` 表示一次简历来源或解析版本。
- 同一个候选人多份简历应进入同一个候选人档案目录。

### 7.3 筛选报告和过程日志

筛选报告、排名、面试计划等输出先作为 artifact 登记：

```powershell
llm-wiki register-artifact --wiki-root <wiki_root> --record-json <json>
```

过程日志追加到 HR log：

```powershell
llm-wiki append-log --wiki-root <wiki_root> --log hr-screening --record-json <json>
```

## 8. 降级行为

HR skill 必须保证 runtime 是 optional backend。

降级触发条件：

- `llm-wiki` 命令不存在。
- `resolve-config` 返回非 `enabled`。
- 用户拒绝启用。
- `load-context-pack` 返回 `read_denied`。
- 写入发生 `validation_error`、`io_error` 或 `unexpected_error`。

降级后的行为：

- 原 HR 筛选、报告、面试题生成继续执行。
- 不阻塞用户主任务。
- 只输出一句短提示：`本次未使用 HR 本地知识库，已按原流程继续。`
- 不反复询问用户是否启用。

## 9. 验收标准

接入完成后，至少满足：

1. 首次运行 HR skill 时不会静默创建 HR wiki。
2. 用户拒绝后，下一次不会再次询问。
3. 用户启用后，`resolve-config --profile hr` 返回 `enabled`。
4. 简历原件通过 `copy-source` 写入 `sources/originals/hr/**`，并登记 `source_id`。
5. 候选人档案通过 `write-record candidate_profile` 写入 `domains/hr/candidates/<candidate_id>/profile.md`。
6. `candidate_id` 和 `resume_version_id` 不混用。
7. HR query 默认不读取 `.meta/**` 和 `sources/originals/**`。
8. AI Radar supporting context 按 `data_only` 处理。
9. runtime 失败时 HR skill 不崩溃，能够回到原流程。
10. 本地测试和 HR skill 原有测试都通过。

## 10. 第一阶段建议改造顺序

1. 先只接入 `resolve-config` 和首次确认。
2. 再接入 `load-context-pack`，让 HR 回答能读到历史候选人档案。
3. 再接入 `copy-source` 和 `candidate_profile` 写入。
4. 最后接入筛选报告 artifact 和过程日志。

这样可以避免一次性改造过大，也便于观察 HR 用户是否真的从 memory 中受益。
