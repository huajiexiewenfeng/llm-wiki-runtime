# LLM Wiki 通用 Skills 与 HR 历史 JD 入库设计

日期：2026-07-18
状态：已完成评审修订，可进入执行计划

## 1. 目标

本设计分成两个阶段。Phase 1 完成一个可由非技术用户通过自然语言验证的最小闭环：

1. `llm-wiki-runtime` 发布可发现的 `init`、`ingest`、`query`、`maintain` 通用 Skills。
2. 用户通过 `llm-wiki-init` 初始化 HR 本地知识库。
3. 用户通过 `llm-wiki-ingest` 从一个旧 Codex 招聘任务中导入历史 JD。
4. 用户通过 `llm-wiki-query` 查询刚导入的 JD。

Phase 1 只迁移 JD，不迁移简历、候选人档案、筛选评分、面试记录或完整招聘会话。

Phase 2 再实现人物聚合、person resolution、自动 person query 和 context views。第 8 节只记录 Phase 2 的目标边界，不属于 Phase 1 的实现与验收范围。

## 2. 核心边界

继续遵循：

> domain owns meaning, core owns access

- `llm-wiki-runtime` 负责确定性能力：安全读写、锁、索引、来源登记、artifact、append-only log、context pack 和权限校验。
- `llm-wiki-core` 负责通用编排：意图路由、domain 发现、source adapter、预览、确认、调用 runtime CLI 和降级提示。
- HR domain 负责业务语义：什么是 JD、岗位字段如何提取、两个 JD 是否可能属于同一岗位、哪些记录允许写入 HR Wiki。
- Codex 宿主负责提供可用的任务读取能力。通用 Skill 不把 Codex 专用能力写进 runtime CLI。

`llm-wiki-ingest` 可以处理历史任务，但不得自行发明 HR 字段或静默决定岗位合并关系。

### 2.1 静态 SCP 与动态 Runtime Binding

`scp.yml` 是随 Skill 发布的静态能力契约，只声明 Skill 的 domain、profile、query 需求和 ingest 产物。初始化不得修改 SCP。

初始化状态属于当前用户、机器和 scope，由 runtime 保存：

runtime 用户配置的默认路径：

```text
Windows: %APPDATA%/llm-wiki-runtime/config.yml
macOS:   ~/Library/Application Support/llm-wiki-runtime/config.yml
Linux:   ~/.config/llm-wiki-runtime/config.yml
```

scope 状态位于：

```text
<scope>/.llm-wiki.yml
<scope>/.llm-wiki/.meta/profile.yml
```

- runtime 用户配置保存 home 和 profile decline 等状态。
- scope 配置保存 `enabled`、`storage_mode`、`scope_id` 和 `primary_profile`。
- profile snapshot 保存当前 scope 实际执行的 domain 规则。

Domain Skill 每次运行时从自己的 SCP 得到 `domain/profile`，再通过 core 调用 `resolve-config` 拉取当前 binding。已启用则自动增强；缺失时首次确认；禁用或错误时无阻塞降级。不得用一次性通知或修改 Skill 文件代替运行时解析。

## 3. 通用 Skill 结构

`llm-wiki-runtime` 发布一个父路由和四个独立子 Skill：

```text
skills/
  llm-wiki-core/
    SKILL.md
    llm-wiki-init/
      SKILL.md
    llm-wiki-ingest/
      SKILL.md
      references/
        codex-thread-source.md
    llm-wiki-query/
      SKILL.md
    llm-wiki-maintain/
      SKILL.md
    references/
      scp-v0.1.md
    templates/
      scp.yml
```

父 Skill 只选择一个子 Skill，不直接执行 init、ingest、query 或 maintain。

### 3.1 llm-wiki-init

触发场景包括“初始化 HR 知识库”“启用 learning wiki”“设置 wiki 根目录”。

职责：

1. 确定 domain。
2. 发现该 domain 提供的 `llm-wiki-profile.yml`。
3. 调用 `resolve-config`。
4. 在首次启用时展示一条符合 domain 隐私策略的确认提示。
5. 用户同意后调用 `init-home` 和 `init-profile`。
6. 用户拒绝后调用 `init-profile --decline`，保存拒绝状态。

### 3.2 llm-wiki-ingest

触发场景包括“把这个文件录入 HR Wiki”“导入旧任务中的历史 JD”“保存这次有价值的结论”。

职责：

1. 确定 source type 和 primary domain。
2. 读取 domain 的 profile 和 ingest mapping。
3. 使用宿主可用的 source adapter 获取内容。
4. 生成结构化预览，不直接写入。
5. 对去重、合并和敏感数据范围取得用户确认。
6. 依次调用 `copy-source`、`write-record`、`register-artifact` 或 `append-log`。
7. 返回实际写入结果和建议的下一条 query。

### 3.3 llm-wiki-query

触发场景包括“查询 HR 里的历史 JD”“我以前招过哪些 Java 岗位”。

职责：

1. 通过显式参数、调用方 SCP、当前 scope 和意图识别确定 primary domain。
2. 调用 `resolve-config` 和 `load-context-pack`。
3. 只在 SCP 与 host policy 允许时加载 supporting domain。
4. 保留来源引用和 `data_only` 隔离标记。

### 3.4 llm-wiki-maintain

触发场景包括“检查 HR Wiki”“为什么查不到刚导入的 JD”“维护知识库”。

V0.1 职责：

1. 检查配置解析、profile snapshot、registry 和 context pack。
2. 检查 SCP/profile 的 record、artifact 和 log 声明是否一致。
3. 报告可执行的修复建议；不做未经用户确认的语义合并或内容重写。

## 4. Domain 接入文件与合同关系

通用 Skills 不内置 HR 语义。`role-copilot-skills/hr-agent-copilot` 的接入结构如下；`NEW` 表示 Phase 1 待创建，未标注的文件已经存在：

```text
hr-agent-copilot/
  SKILL.md
  README.md
  README.zh.md
  scripts/
    extract_resumes.py
  tests/
    test_llm_wiki_integration_contract.py
  hr-resume-screening-copilot/
    SKILL.md
    scp.yml                         # Phase 1 修改
  hr-candidate-detail-report-copilot/
    SKILL.md
    scp.yml
  hr-interview-question-generator-copilot/
    SKILL.md
    scp.yml
  llm-wiki-profile.yml              # NEW
  ingest-mapping.yml                # NEW
  references/
    llm-wiki-integration.md
    llm-wiki-ingest.md              # NEW
```

- `llm-wiki-profile.yml`（NEW）：定义目录、record/log write rules、read rules、artifact 和隐私策略。
- `ingest-mapping.yml`：机器可读地声明 source type、字段映射、owner skill 和语义说明入口。
- `references/llm-wiki-ingest.md`：说明 HR 字段提取、去重建议、事实与判断的分离规则。

通用 Skill 在已安装 Skill roots 中发现 `llm-wiki-profile.yml`。同一 domain 发现多个不一致 profile 时必须让用户选择，并由 maintain 报告冲突。

三个合同的分工固定为：

```text
scp.yml            声明允许产出什么
ingest-mapping.yml 声明从某种 source 怎么生成这些产物
profile.yml        声明这些产物写到哪里以及写入模式
```

HR JD mapping 使用 `owner_skill_id: hr-resume-screening-copilot`。该 Skill 的 SCP 在 Phase 1 增加 `job_profile`、`jd_version` 和 `hr_jd_import` 产物，因为它已经拥有 JD 理解语义。`llm-wiki-ingest` 是通用执行者，不冒充产物所有者。

maintain 必须校验：

```text
mapping.produces
  subset of owner SCP ingest.produces
  subset of profile records/logs/artifacts
```

## 5. Codex 历史任务 Source Adapter

Codex 环境优先使用宿主提供的 `list_threads` 和 `read_thread`：

1. 用户提供旧任务标题或关键词。
2. `list_threads` 返回匹配任务。
3. 唯一匹配时仍展示标题、日期和任务 ID；多个匹配时必须让用户选择。
4. `read_thread` 分页读取用户确认的任务。
5. HR ingest mapping 只选择包含 JD 的消息和必要上下文，并返回原始消息的 `thread_id` 与 `selections[]`；每个 selection 包含 `turn_id`、`item_id`、`start`、`end` 和原始消息 checksum。也可以选择完整 JD 消息，但不得先改写再作为证据。
6. 用户在预览 Gate 确认选中的原文范围。
7. 确定性代码根据确认范围生成 JD-only evidence snapshot。

若宿主没有任务读取接口，降级为要求用户提供 Markdown 或 JSON 会话导出文件。降级时不得声称已经读取旧任务。

## 6. 隐私与来源策略

旧招聘任务可能同时包含 JD、简历、候选人信息和筛选判断。第一期采用数据最小化：

- 完整任务只用于本次内存内识别，不复制到 Wiki。
- evidence snapshot 只保留确认后的 JD 原文、任务 ID、消息时间和消息来源标识。
- 不保存简历文本、候选人姓名、联系方式、评分和面试判断。
- snapshot 通过 `copy-source` 进入 `sources/originals/hr/jobs/**`。
- source registry 将其标记为 `source_type: codex_thread_jd_excerpt`、`excerpted: true`，并记录 `thread_id`、受控 `selections[]` 和确认时间。`selections[]` 逐条保存 `turn_id`、`item_id`、字符范围与原始消息 checksum，因此一次导入可以安全引用多条消息而不丢失 provenance。
- `copy-source` 增加可选 `metadata-json` 输入并原样登记受控 provenance 字段；相同 checksum 与 logical path 已登记时返回 `already_exists`，不得向 registry 追加重复项。
- `copy-source` 在写入前计算源文件 checksum；目标 logical path 已存在且 checksum 不同时拒绝覆盖，已存在且 checksum 相同时只补齐缺失登记或返回 `already_exists`。
- `sources/originals/**` 默认不进入 context pack。
- 如果一条消息混合 JD 与候选人内容，预览中标记为需要确认；Phase 1 默认不自动写入，只有用户确认精确摘录后才继续。
- 写入前运行确定性的敏感模式扫描并展示风险提示。该扫描只是兜底，不能替代用户确认，也不构成无敏感信息的硬保证。

## 7. HR JD 数据模型

JD catalog 是共享来源和检索入口，不是 HR Skill 默认上下文的聚合根。未关联候选人的历史 JD 可以先进入 catalog；某个人参与该岗位流程后，由其人物 case 引用对应 `job_id` 和 `jd_version_id`。

```text
.llm-wiki/
  domains/hr/jobs/
    {job_id}/
      profile.md
      versions/
        {jd_version_id}.md
  sources/originals/hr/jobs/
    {job_id}/
      {jd_version_id}.md
  logs/
    hr-jd-import.jsonl
```

### 7.1 job_profile

- 路径：`domains/hr/jobs/{job_id}/profile.md`
- 模式：`update_allowed`
- 表示岗位的长期身份。
- 字段包括岗位名称、级别、业务方向、地点、状态、已知版本和最近导入时间。
- 更新必须进入 runtime change log。

### 7.2 jd_version

- 路径：`domains/hr/jobs/{job_id}/versions/{jd_version_id}.md`
- 模式：`create_only`
- 表示一版具体 JD。
- 字段包括职责、必须条件、加分条件、淘汰条件、结构化时的未知项和 source 引用。
- 已写入版本不可覆盖。
- 对同一路径的重试不覆盖已有内容，而是返回 `already_exists` 和已有 checksum；这仍然满足 `create_only` 的不可变约束。

### 7.3 身份规则

- `job_id` 表示同一个招聘岗位，由首次导入或用户确认合并时建立。
- `jd_version_id` 只根据用户确认后的 JD 原文生成，LLM 提取或结构化结果不得参与身份计算。
- 确定性规范化顺序为：Unicode NFC、换行统一为 LF、全文首尾 trim；其余字符保持不变。
- 多个原文范围按 thread/message 顺序排列，并使用固定分隔符连接后再计算 SHA-256。
- 相同摘要重复导入时返回 already exists，不重复写入。
- 标题、级别、业务方向或地点不确定时，默认创建独立岗位建议，不静默合并。
- Skill 可以给出去重建议，但用户确认是跨版本合并的唯一授权来源。

### 7.4 导入日志

`hr-jd-import.jsonl` 使用 append-only 记录：

- Codex task ID 和标题。
- 导入时间。
- 发现、确认、跳过、重复和失败的 JD 数量。
- 生成的 `job_id`、`jd_version_id` 和 `source_id`。
- 本次隐私过滤结果。

HR profile 必须声明日志合同：

```yaml
logs:
  types:
    hr_jd_import:
      path: logs/hr-jd-import.jsonl
      mode: append_only
```

每次 HR JD 导入使用确定性的 `event_id = hr-jd-import:{source_id}:{job_id}:{jd_version_id}`。profile-aware `append-log` 在同一日志中发现相同 `event_id` 时返回 `already_exists`，不得重复追加；没有 `event_id` 的旧日志调用保持原有 append-only 行为。

runtime 的 `append-log` 必须按 `log_type` 查询 active profile 并校验路径，不能继续让调用方任意传入逻辑日志路径。现有直接路径接口如需保留，只作为兼容入口，并不得被通用 Skill 使用。

## 8. Phase 2 目标：HR 人物聚合与上下文

本节描述后续目标，不属于 Phase 1 实施清单。person resolution、人物索引和 context views 的协议/schema 将在独立设计中确定，Phase 1 不修改 SCP v0.1 或 profile parser 来实现这些能力。

HR Wiki 以人物为主要导航和上下文入口。现有 `candidate_id` 定义为人的长期身份，不等于某份简历或某次应聘。

```text
domains/hr/candidates/
  {candidate_id}/
    profile.md
    timeline.jsonl
    resumes/
      {resume_version_id}.md
    cases/
      {case_id}/
        context.md
        screenings/
          {screening_run_id}.md
        interviews/
          {interview_round_id}.md
        decision.md
```

- `profile.md` 保存有来源的长期人才事实。
- `resumes/` 保存该人物的简历版本和解析结果。
- `case` 表示这个人与某个 JD 的一次招聘关系。
- `context.md` 引用共享的 `job_id`、`jd_version_id` 和 source，不复制 JD 权威原文。
- 筛选、面试、拒绝、Offer、撤回和入职都属于具体 case，不作为人物全局标签。

例如“张三被 Java 高级岗拒绝”可以写入该 case；“张三是已淘汰人才”不得写入人物档案。

### 8.1 三个现有 HR Skill 的记忆

| Skill | 默认读取 | 按需读取 | 写入 |
| --- | --- | --- | --- |
| `hr-resume-screening-copilot` | 人物档案、当前简历、当前 JD | 同一 case 的历史筛选、明确相关的过往 case | 人物事实、筛选批次、筛选报告和推荐结果 |
| `hr-candidate-detail-report-copilot` | 人物档案、当前 case、筛选证据 | 当前 case 的面试记录和相关履历版本 | candidate detail report artifact |
| `hr-interview-question-generator-copilot` | 人物档案、当前 JD、筛选待验证项 | 当前 case 的前序面试轮次 | interview plan artifact |

模型生成的评分、排名、推荐和面试题属于带时间、来源和模型版本的 artifact，不得覆盖人物事实。`recommended/not_recommended` 不等于 `hired/rejected`。

现有三个 Skill 不负责写入实际面试反馈、Offer、拒绝和入职状态。完整生命周期需要后续的 HR feedback/status ingest mapping 或独立 domain skill；通用 core 不推断这些状态。

### 8.2 自动 Person Query 目标

HR Wiki 已启用时，三个 HR Skill 默认执行 person query，不要求用户额外说“查询 Wiki”：

```text
HR Skill -> SCP(domain=hr) -> core resolve-config -> resolve person
         -> 选择最小 context views -> load-context-pack -> 执行业务任务
```

目标人物匹配顺序：

1. 显式 `candidate_id`。
2. `resume_version_id` 或 source checksum。
3. 姓名与受控的辅助身份信息。
4. 只有姓名且存在重名时返回 `ambiguous_person`，等待用户选择。

找不到人物时使用当前输入继续；任务完成后可以按 ingest 规则建议新增人物，不阻塞原 HR 工作。

### 8.3 Context Views 目标

Phase 2 将定义 `person_core`、`current_resume`、`current_case`、`screening_history`、`interview_history` 和 `decision_timeline` 等最小上下文视图。profile 中的 view 到路径模板映射、SCP 中 required/optional view 声明、人物索引和 identity lookup keys 必须在该阶段一起设计并升级 schema。

在 Phase 2 schema 完成前，这些字段不得写入 SCP v0.1 或 profile 并假设 runtime 会生效。core 最终根据 `candidate_id`、`case_id` 和 `jd_version_id` 生成 path filters，不把整个人才库或整个人物目录无差别塞进 prompt。

默认排除原始简历、联系方式、无关 case、其他候选人数据和没有来源的历史模型猜测。

上下文冲突优先级：

```text
本次用户提供的最新材料
> Wiki 中有来源的事实
> 有明确作者和时间的面试反馈
> 历史模型评分与推断
```

### 8.4 入库判断

| 数据 | 处理 |
| --- | --- |
| 简历事实、JD 原文、实际面试反馈 | 有 source 引用后进入对应人物/case 或共享来源 |
| 人物、岗位和 case 的身份合并 | 用户确认后写入 |
| 模型评分、排名、风险和问题清单 | 作为 artifact，不写入人物事实 |
| 拒绝、Offer、撤回和入职 | 只有用户确认或业务系统证据时写入 case event |
| 模型猜测、闲聊、临时推演 | 不入库 |
| 原始简历和联系方式 | 受控保存，默认不进入 context pack |

## 9. 用户交互流程

### 9.1 Init

```text
用户：初始化 HR 知识库
core -> init -> domain=hr -> resolve-config -> 首次确认 -> init-home/init-profile
```

### 9.2 历史 JD Ingest

```text
用户：把旧任务“Java 高级开发招聘筛选”中的历史 JD 导入 HR Wiki
core -> ingest -> 搜索任务 -> 用户选任务 -> 读取任务 -> JD-only 提取
     -> 展示预览 -> 用户确认岗位/版本关系 -> runtime 写入 -> 返回结果
```

预览至少展示：

- 识别到的 JD 数量。
- 每份 JD 的标题、级别、业务方向和来源消息。
- 建议的 `job_id` 与 `jd_version_id`。
- 可能重复或可能属于同一岗位的项目。
- 被隐私过滤排除的内容类别，不展示被排除的敏感正文。

### 9.3 Query 验收

```text
用户：查询刚才导入的历史 JD
core -> query -> domain=hr -> load-context-pack -> 返回岗位与版本列表及来源引用
```

## 10. 错误与降级

| 场景 | 行为 |
| --- | --- |
| 未找到旧任务 | 展示相近结果，不写入 |
| 多个同名任务 | 等待用户选择，不写入 |
| 缺少任务读取能力 | 要求 Markdown/JSON 导出文件 |
| 无法确认岗位关系 | 默认分开并等待确认 |
| profile 或 mapping 缺失 | 返回 `domain_mapping_required`，不做结构化写入 |
| runtime 写入失败 | 保留预览和失败清单，不声称已入库 |
| 部分写入成功 | 返回逐项结果；重试必须保持幂等 |
| 相同 JD 已存在 | 返回 `already_exists` 和现有引用，不重复写入 |

对于 JD 历史迁移，fallback 不允许绕过 runtime 直接写 `.llm-wiki`。

Phase 1 使用统一状态词表：

```text
ok
enabled
missing_config
disabled
profile_mismatch
domain_mapping_required
already_exists
validation_error
read_denied
runtime_unavailable
io_error
unexpected_error
```

`ambiguous_person` 属于 Phase 2，随 person resolution 协议一起登记，不进入 Phase 1 实现。

## 11. 测试设计

### 11.1 llm-wiki-runtime

- 父 Skill 只路由一个子 Skill。
- 四个子 Skill 的触发描述互不竞争。
- ingest 在确认前不得调用写命令。
- Codex source adapter 能处理唯一匹配、多匹配、分页、无接口降级。
- source adapter 只能从用户确认的原文范围生成 evidence snapshot。
- 混合 JD 与候选人信息时默认不写；确认后保存 `excerpted`、thread/turn/item/字符范围和 checksum provenance。
- 敏感模式扫描能阻止明显的联系方式进入未确认 snapshot，但测试不得把它描述成完整隐私保证。
- 重复 JD 的 `jd_version_id` 稳定且不重复写入。
- JD 原文规范化严格执行 NFC、LF 和首尾 trim，LLM 结构化结果变化不影响版本 ID。
- runtime 部分失败时返回逐项状态和可重试信息。
- init 不修改任何 domain skill 的 `scp.yml`。
- `resolve-config(profile=hr)` 能从动态 binding 返回 enabled/disabled/missing/error 状态。
- mapping 产物必须同时被 owner SCP 和 active profile 允许。
- `copy-source` 重试不得在 source registry 中产生重复登记。
- `append-log(log_type=hr_jd_import)` 必须通过 active profile 的 append-only 日志合同校验。
- 相同 HR JD `event_id` 的重试不得在 `hr-jd-import.jsonl` 中产生重复事件。
- 父 + 嵌套子 Skill 的发现采用与已验证 HR package 相同的结构，并增加安装态回归测试。

### 11.2 role-copilot-skills

- HR profile 声明 `job_profile` 和 `jd_version` write rules。
- HR ingest mapping 只允许写 HR domain。
- `job_profile` 为 `update_allowed`，`jd_version` 为 `create_only`。
- 重复导入同一 `jd_version_id` 时，`jd_version` 返回 `already_exists`；若 `job_profile` 已引用该版本则不重写，`hr_jd_import` 依靠确定性 `event_id` 去重。
- `hr-resume-screening-copilot/scp.yml` 声明 `job_profile`、`jd_version` 和 `hr_jd_import`。
- `ingest-mapping.yml` 的 owner 为 `hr-resume-screening-copilot`，其产物是该 SCP 声明的子集。
- HR profile 声明 `hr_jd_import` append-only 日志合同。
- mapping 明确区分 JD 事实、模型推断和未知信息。
- mapping 明确排除简历、候选人和筛选评分。

人物 context views、person resolution 和筛选状态边界的自动化测试属于 Phase 2，不进入本期通过条件。

### 11.3 人工验收

用户在新 Codex 任务中依次输入：

1. `初始化 HR 知识库`
2. `把旧任务“<任务标题>”中的历史 JD 导入 HR Wiki`
3. `查询刚才导入的历史 JD`

验收结果：

- init 明确命中 `llm-wiki-init`。
- ingest 明确命中 `llm-wiki-ingest` 并在写入前展示预览。
- Wiki 中存在 JD-only source、`job_profile`、不可变 `jd_version` 和导入日志。
- query 能返回刚导入的岗位与版本，并带来源引用。
- Wiki 中不存在本轮未授权迁移的简历或候选人正文。

## 12. 非目标

本期不做：

- 批量扫描所有招聘任务。
- 迁移简历、候选人档案、历史评分和面试反馈。
- 自动合并相似岗位。
- 在 runtime CLI 中实现 Codex 专用 API。
- V0.2 memory、trace、eval 或模型动态拉取。
- 在缺少 domain mapping 时由 core 猜测业务结构。
- 在第一期实现实际面试反馈、Offer、拒绝和入职状态录入。
- 把所有人物历史或整个 HR domain 无差别装入上下文。
- 在 Phase 1 实现人物索引、identity lookup keys、person resolution 或 context views schema。
- 在 Phase 1 升级三个 HR Skill 的 person-query SCP 字段。

## 13. 实施顺序

### 13.1 Phase 1：JD 最小闭环

1. 在 `llm-wiki-runtime` 拆分父路由与四个通用子 Skill。
2. 定义 mapping/SCP/profile 三层校验和统一状态词表。
3. 扩展 source registry，支持 excerpt/provenance 元数据。
4. 实现确定性的 JD 原文规范化与版本 ID。
5. 为 profile/runtime 增加按 `log_type` 校验的 append-only 日志合同。
6. 完成 Codex source adapter 指南与 fixture 测试。
7. 在 `role-copilot-skills` 增加 HR profile、JD ingest mapping 和语义说明，并扩展 owner SCP。
8. 将 `llm-wiki-core` 完整包安装到当前 Codex Skill root。
9. 使用一个指定旧招聘任务完成 init、ingest、query 人工验收。

### 13.2 Phase 2：人物增强

Phase 2 另写设计与计划，统一解决：

- 通用 entity index 与 domain-owned identity lookup keys。
- person resolution 和 `ambiguous_person`。
- profile context views schema 与路径模板展开。
- SCP required/optional views schema。
- 三个 HR Skill 的默认 person query、最小上下文和回写策略。
