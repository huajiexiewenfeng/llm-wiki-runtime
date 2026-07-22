# 通用记录检索与 Domain 身份解析设计

日期：2026-07-22
状态：待实现评审
涉及仓库：`llm-wiki-runtime`、`role-copilot-skills`

## 1. 背景

LLM Wiki 当前要求调用方在执行 `load-context-pack` 之前先知道记录路径。但用户通常只会用展示名称描述一个实体，而不知道它的路径或稳定 ID。暴露这一缺口的 HR 场景是：候选人记录路径使用不透明的 `candidate_id`，同时 Markdown 正文中含有 PDF 提取产生的控制字符。文件系统文本搜索没有找到结果，但对应记录和图谱节点实际上都存在。

这并不是 HR 独有的问题。任何 Domain 都可能需要把面向人的值解析为持久记录，例如：项目名称对应项目记录、包名称对应发布记录、课程标题对应学习记录、客户标签对应账户记录。

解决方案不能让 Runtime 理解 HR 业务语义，也不能让 HR Skill 依赖图谱导出、文件系统遍历或 Runtime 内部实现。

## 2. 架构原则

1. Runtime 负责确定性访问、校验、授权和通用记录匹配。
2. Domain 包负责记录含义、身份字段、展示字段、别名和歧义处理。
3. SCP 负责跨 Skill 数据契约和授权声明，但不实现记录搜索。
4. Graph 输出属于派生的展示数据，绝不是权威查询索引。
5. 原始来源文件继续排除在普通 context pack 和记录检索结果之外。
6. Runtime 不进行模糊业务推断，也不会在多个匹配项中静默选择一个。
7. 已安装的 Skill 目录是部署目标，不是源码仓库。

## 3. 目标

- 在不知道记录路径的情况下，把用户提供的标量值解析为一条或多条记录。
- 保持检索机制对所有 Domain 通用。
- 允许每个 Domain 以声明式方式定义记录身份和检索字段。
- 只返回 Profile 控制的元数据白名单和 scope 相对路径。
- 保持确定性的排序和授权行为。
- 防止格式异常的提取文本继续写入新的 Markdown 记录。
- 为 HR Skill 提供稳定的候选人解析流程，同时确保关闭 LLM Wiki 后仍可正常使用。

## 4. 非目标

- 对 Markdown 正文执行全文搜索。
- 模糊名称匹配、语音匹配、Embedding、排序或 LLM 推断。
- 使用 `graph.json` 作为记录索引。
- 在本阶段建设持久化数据库或搜索服务。
- 在 Runtime 代码、CLI 参数、模型、错误或测试中加入 HR 概念。
- 把候选人身份语义迁入 SCP v0.1。
- 自动合并重复记录。

## 5. 方案比较

### 5.1 由调用方传入字段名

调用方把 `display_name`、`aliases` 等检索字段传给 Runtime 命令。

这种方案简单，但会迫使每个 Skill 理解 Runtime 查询语法并重复维护字段白名单，也会让隐私策略依赖每次调用参数。因此不选择它作为主要方案。

### 5.2 在 Domain Profile 中声明检索规则

当前生效的 Domain Profile 声明每种记录类型如何被检索，以及允许返回哪些元数据。Runtime 只负责执行这份通用声明。

该方案保留了清晰的职责边界，不修改 Runtime 代码也能支持其他 Domain，并且可以集中管理隐私默认值。因此选择此方案。

### 5.3 查询 Graph 输出

调用方读取 `.llm-wiki/.meta/graph/<domain>/graph.json` 并搜索节点标签。

图谱为最新状态时，这种方案速度较快；但图谱导出是可选的派生产物，可能缺失或过期。它还会把核心查询能力与可视化功能绑定。因此不采用该方案。

## 6. Domain Profile 契约

当前生效的 Profile 增加一个可选的 `read_rules.record_lookup` 映射：

```yaml
read_rules:
  context_pack:
    include: [domains/hr/**]
    exclude: [sources/originals/**, .meta/**]
    max_files: 30
    max_chars_per_file: 4000

  record_lookup:
    candidate_profile:
      identity_field: candidate_id
      display_field: display_name
      match_fields: [display_name, aliases]
      return_fields:
        - candidate_id
        - display_name
        - aliases
        - current_resume_version_id
      max_results: 20
```

这里的配置属于 HR Domain，仅用于展示一个消费者如何声明规则。Runtime 实现和仓库测试只使用中性的记录类型，并且只理解通用配置键。

### 6.1 校验规则

- 检索规则中的记录类型必须同时存在于 `write_rules.records`。
- `identity_field`、`display_field`、全部 `match_fields` 和全部 `return_fields` 必须符合现有的保守 frontmatter 字段名语法。
- `match_fields` 至少包含一个字段，且字段名不得重复。
- `return_fields` 必须包含 `identity_field` 和 `display_field`。
- `max_results` 必须是 1 到 100 之间的整数，默认值为 20。
- 出现未知配置键时，Profile 校验失败。
- 不包含 `record_lookup` 的旧 Profile 仍然有效，并保持现有行为不变。

## 7. Runtime 命令

新增一个与现有命名风格一致的平铺 CLI 命令：

```powershell
llm-wiki find-records `
  --scope-root "C:\path\to\scope" `
  --record-type candidate_profile `
  --lookup-value-json '"Example Candidate"' `
  --caller-domain hr `
  --target-domain hr
```

该命令也接受与 `load-context-pack` 相同的可选授权参数：

- `--domain-policies-json`
- `--caller-groups-json`

`--lookup-value-json` 解码后必须是非 null 的标量字符串、整数、有限浮点数或布尔值。这样既能避免字符串与数字之间的歧义，也能复用 Runtime 现有的 JSON CLI 约定。null 会被拒绝，因为它不是可用的记录身份，并且可能意外匹配大量信息不完整的记录。

### 7.1 输出

唯一匹配结果：

```json
{
  "status": "found",
  "record_type": "candidate_profile",
  "lookup_value": "Example Candidate",
  "matches": [
    {
      "path": "domains/hr/candidates/candidate-example-001/profile.md",
      "checksum": "sha256:...",
      "identity": "candidate-example-001",
      "display": "Example Candidate",
      "fields": {
        "candidate_id": "candidate-example-001",
        "display_name": "Example Candidate",
        "aliases": []
      }
    }
  ],
  "context_refs": [
    {
      "path": "domains/hr/candidates/candidate-example-001/profile.md",
      "checksum": "sha256:..."
    }
  ],
  "warnings": []
}
```

其他成功的业务状态包括：

- `not_found`：没有匹配记录，`matches` 为空。
- `multiple_matches`：存在多条匹配记录，Runtime 最多返回 `max_results` 条，绝不自行选择其中一条。

每个成功响应都包含 `truncated`。只有匹配记录数量超过 `max_results` 时，该值才为 `true`。这些状态不属于 Runtime 执行失败，退出码均为 0。配置、授权和 I/O 错误继续沿用 Runtime 现有的错误分类和非零退出行为。

### 7.2 匹配语义

1. 从 `scope_root` 加载当前生效的 Profile 快照。
2. 使用与 context pack 相同的策略，对调用方和目标 Domain 进行授权。
3. 找到请求记录类型对应的检索声明。
4. 只枚举 `read_rules.context_pack.include` 和 `exclude` 允许的文件。
5. 只解析文件开头的 frontmatter，不搜索也不返回 Markdown 正文。
6. 要求 frontmatter 中的 `record_type` 与请求的记录类型完全相同。
7. 使用 OR 语义，把检索值与每个已声明的 `match_fields` 字段进行比较。
8. 标量字段按标量相等匹配；字符串比较前执行 Unicode NFC 规范化。
9. 列表字段中，只要任一标量成员等于检索值即视为匹配。
10. 字符串比较区分大小写，不执行子串或模糊匹配。
11. 按 scope 相对 POSIX 路径排序匹配结果。
12. 只返回 `return_fields`、相对路径、checksum，以及派生的 `identity` 和 `display`。

已存储 frontmatter 的首尾空白具有实际意义。调用方可以依据 Domain 语义在调用 Runtime 前规范化用户输入；Runtime 不会静默修改已存储的身份值。

### 7.3 Frontmatter 扫描

记录发现只读取文件开头一段有上限的内容，默认每个文件最多读取 64 KiB，以满足 frontmatter 解析需要。缺少结束分隔符、frontmatter 无效或 frontmatter 超限时，跳过该记录，并返回稳定的告警码和相对路径。单条异常记录不能导致全部检索结果不可用。

扫描器不得依赖 `rg`、文件名约定、图谱导出或 source registry。

## 8. Runtime API

引入职责明确的通用单元：

```python
@dataclass(frozen=True)
class RecordLookupRule:
    record_type: str
    identity_field: str
    display_field: str
    match_fields: tuple[str, ...]
    return_fields: tuple[str, ...]
    max_results: int = 20


def find_records(
    scope_root: Path,
    record_type: str,
    lookup_value: FrontmatterScalar,
    *,
    caller_domain: str | None = None,
    target_domain: str | None = None,
    domain_policies: dict | None = None,
    caller_groups: list[str] | None = None,
) -> dict:
    ...
```

Profile 解析层负责声明校验。独立的记录检索模块负责 frontmatter 枚举与匹配。CLI 编排逻辑不得加入 `graph_collect.py`，也不得复用 Graph 模型。

## 9. 授权与隐私

- 检索使用当前 Profile 的读取白名单，并强制排除 `.meta/**`。
- `sources/originals/**` 继续按照 Profile 策略排除。
- 跨 Domain 检索沿用 context pack 的 `readable-by` 和调用方分组校验。
- 结果字段由 Profile 明确列入白名单；Runtime 默认绝不返回全部 frontmatter。
- 告警只包含稳定的原因码和相对路径，不包含原始 frontmatter 或异常文本。
- 可以使用命令、状态、记录类型、结果数量和耗时审计检索事件。检索值和返回的个人元数据不得写入审计日志。

## 10. 记录文本卫生

### 10.1 Runtime 边界

`write-record` 必须在获取 scope lock 或修改任何文件之前校验 Markdown 记录内容。制表符、换行符和回车符允许存在；其他 C0 控制字符和 DEL 必须拒绝，其中包括 NUL，并返回稳定的校验错误。

Runtime 不静默删除这些字符，因为静默修改会在 Domain 不知情的情况下改变有来源依据的内容。`copy-source` 继续按字节保真，不受影响。

### 10.2 Domain 入库边界

Domain 的提取代码可以在生成 Markdown 记录前清理提取文本。HR PDF 提取会删除禁止的控制字符、保留普通 Unicode 文本，并在提取元数据中记录告警数量。

这项责任在 Runtime 层面并不属于 HR 特例：每个 Domain 都必须向 `write-record` 提供有效文本，Runtime 则统一强制执行该不变量。

### 10.3 现有数据

对于已经含有禁止控制字符的 HR 记录，通过 Runtime 控制的写入执行一次性本地迁移。迁移过程：

- 在仓库外创建本地备份；
- 只删除禁止的控制字符；
- 保留 frontmatter、正常文本、来源引用和原有行结构；
- 记录正常的更新 checksum 和 change-log 事件；
- 绝不提交或上传候选人记录。

## 11. HR Domain 行为

HR 候选人解析使用独立于 Runtime 实现细节的 Domain 语义：

1. 已知 `candidate_id` 时，加载该候选人的精确且已授权记录。
2. 只有人名或已确认别名时，使用候选人 Profile 声明的检索语义进行解析。
3. 只有一个结果时，通过 `load-context-pack` 加载该精确记录。
4. 有多个结果时，只使用批准的非联系方式字段，提出一个简短的消歧问题。
5. 没有结果时，先检查用户提供或已配置的简历输入，再声称候选人材料不存在。
6. 不得根据 Graph 节点、文件名、公司名称或近似字符串推断身份。
7. 已确认别名可以通过正常的候选人 Profile 更新流程，写入 Domain 自有的 `aliases` frontmatter 列表。

HR 子 Skill 在没有 LLM Wiki 时仍须可用。Runtime 被禁用或不可用时，继续使用现有简历和 JD 输入，并只说明一次本次未应用 Wiki 上下文。

## 12. SCP 边界

本阶段不修改 SCP v0.1。

`query.primary_domain`、信任策略和 supporting-domain 授权继续属于 SCP 职责。记录检索声明留在 Domain Profile 中，因为它描述的是单个 Domain 内部的记录，而不是 Skill 之间交换的产品。

如果未来跨 Skill 实体交接需要命名 Domain 身份，后续 SCP 版本可以引用它。这项扩展不在本设计范围内。

## 13. 源码仓库与安装纪律

实现涉及两个源码仓库：

- `llm-wiki-runtime`：通用 Profile schema、检索 API/CLI、内容校验、核心查询 Skill 文档和通用测试。
- `role-copilot-skills`：HR Profile 声明、HR 解析流程、PDF 提取清理和 HR 契约测试。

当前已安装的 HR 包含有 LLM Wiki 集成文件，但这些文件不在已检出的 `role-copilot-skills` 主分支中。修改 HR 行为前，必须先建立干净的 source-of-truth worktree，把已安装的集成文件安全地协调回源码仓库，同时不得复制任何本地候选人数据，然后再从该源码重新安装。不能只修改已安装目录并把它作为唯一持久变更。

两个仓库分别创建本地提交。除非用户明确要求，否则任何实现步骤都不推送到 GitHub。

## 14. 兼容性与发布顺序

1. 不含 `read_rules.record_lookup` 的 Profile 继续按现有方式解析和运行。
2. 现有 `load-context-pack` 行为和输出保持不变。
3. Graph 导出保持独立和可选。
4. 首先实现 Runtime 检索及其测试。
5. 增加通用核心查询流程，在加载上下文前使用检索能力。
6. 增加 HR Profile 语义和 HR 工作流测试。
7. 在本地清理现有 HR 记录。
8. 从源码仓库重新安装 HR Skill。
9. 在不存在 Graph 输出的条件下执行端到端候选人名称查询，证明核心流程不依赖 Graph。

## 15. 测试策略

### 15.1 Runtime 测试

Runtime 测试夹具使用 `project_record`、`package_record` 等中性记录类型，不包含 HR 术语。

必须覆盖：

- 精确标量匹配；
- 列表成员别名匹配；
- Unicode NFC 等价字符串匹配；
- 区分大小写的不匹配；
- 零条、一条和多条匹配；
- 稳定的路径排序；
- 结果字段白名单；
- 结果数量限制和截断标记；
- 缺少检索声明；
- 无效的检索 Profile 字段；
- 无效和超限 frontmatter 的告警；
- 旧数据正文含有 NUL 时，不影响仅基于 frontmatter 的检索；
- 后续 `write-record` 拒绝禁止控制字符，并且不修改目标文件；
- 制表符、换行符和回车符仍然有效；
- Graph 目录缺失或过期不影响检索；
- 读取被拒绝时不返回任何记录元数据；
- 输出和审计事件不包含检索值及私密元数据。

### 15.2 HR Skill 测试

- 用户只提供 `display_name` 时能够解析候选人；
- 已确认别名解析到同一候选人；
- 展示名称重复时必须消歧；
- `not_found` 时，在声称缺少候选人材料前触发简历输入回退；
- 已知 `candidate_id` 时跳过名称解析；
- 子 Skill 不搜索 `graph.json`、不运行 `rg`、不依赖候选人目录名称；
- Runtime 被禁用时 HR 仍然可用；
- PDF 提取删除禁止控制字符并报告数量；
- 测试夹具不包含任何真实候选人数据。

### 15.3 端到端验收

仓库测试只使用合成记录：

1. 使用支持检索的 Profile 初始化一个通用 scope。
2. 写入两条展示值相同的记录，以及一条包含别名的记录。
3. 验证 `multiple_matches`、别名检索 `found`，以及根据返回路径加载上下文。
4. 删除 Graph 输出后重复执行，仍然成功。
5. 尝试写入包含 NUL 的记录，并确认文件没有变化。

本地 HR 验收可以使用私有 scope，但不得把任何输出写入两个源码仓库。

## 16. 验收标准

- Domain 无需修改 Runtime 代码即可声明检索语义。
- Runtime 代码和测试不包含 HR 专有标识或分支。
- HR Skill 不依赖 Graph 路径、候选人目录遍历或 shell 搜索。
- 输入候选人姓名后，可以确定性地得到零条、一条或多条记录。
- 多条匹配绝不会被静默合并为一条。
- 检索只返回白名单字段和已授权的上下文引用。
- 后续 Markdown 记录不能包含禁止的控制字符。
- 现有 HR 数据只在本地清理，不进入 Git。
- Runtime 和 HR 两个仓库分别通过完整测试套件。
- 缺少 Graph 导出时，候选人检索仍然成功。
