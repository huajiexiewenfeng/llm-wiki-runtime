# LLM Wiki 离线图谱导出

`graph-export` 将 scope 内已经确定的节点和显式关系导出为可离线打开的 HTML 图谱。Runtime 只读取 scope 内的 profile 快照、声明式 graph adapter、记录、来源注册信息和日志；不会执行 Domain 代码，也不会推断跨 Domain 关系。

## 使用

```powershell
llm-wiki graph-export --cwd "C:\path\to\scope"
llm-wiki graph-export --cwd "C:\path\to\scope" --domain hr
```

命令沿用 `resolve-config` 的参数语义，也支持 `--profile` 和 `--scope`。成功时返回 `ok`；部分 Domain 成功时返回 `partial_failure`；scope 正被其他写命令占用时返回 `scope_busy`。

## 输出结构

```text
.llm-wiki/.meta/graph/
  index.html
  graph-manifest.json
  graph-export-report.json
  <domain>/
    graph.html
    graph.json
```

`index.html` 是多个 Domain 图谱的总入口。每个 Domain 拥有独立页面和数据，不生成跨 Domain 图。所有页面内嵌 CSS、JavaScript 和数据，通过 `file://` 即可离线使用，不会请求网络资源。

## 数据与隐私

- 节点只包含标签、类型、状态、标签集合、摘要、相对路径和 adapter 明确允许的 metadata。
- 默认 adapter 不导出额外 metadata；Domain adapter 必须通过 `metadata_allowlist` 显式允许字段。
- 边只来自 profile 注册、结构化引用、WikiLink 或 Markdown 链接，并且每条边都带 scope 相对 evidence。
- 原文正文、原始简历内容、绝对文件路径和未允许的 frontmatter 不进入 Domain HTML/JSON。
- 只有本地工具使用的 `graph-manifest.json` 保存一次绝对 `scope_root`；索引页、Domain 页面、报告和审计日志不保存绝对路径。
- `.meta/**` 被 context pack 强制排除，因此图谱聚合文件不会进入 prompt。

分享整个 graph 目录也会分享其中聚合后的、已允许的 metadata 和关系。分享前仍应按该 scope 的隐私级别进行检查。

## Adapter 快照

Runtime 从 `.llm-wiki/.meta/graph-adapters/<domain>.yml` 读取声明式 adapter 快照。快照缺失时使用内建默认：文件名作为标签、`record_type` 作为 subtype，不额外导出 metadata。导出不依赖宿主 Skill registry，因此卸载 Skill 后，已有 scope 仍可导出。

图谱对 `record` 节点按 subtype 分配独立颜色，并生成带颜色标识的 `Record` 筛选项。例如候选人、岗位和 JD 版本即使同属 `record`，也可以在图上直接区分和独立筛选。节点详情中的 `kind` 提供可读分类名，同时保留原始 subtype 便于审计。

## 失败与恢复

导出在 scope lock 内运行。每个 Domain 先在内存中完成收集、关系解析、布局、序列化和 HTML 校验，再通过同级 staging/backup 目录替换。单个 Domain 失败时保留上一次成功产物，并继续其他 Domain；下次运行会恢复遗留 backup，并清理受控 staging 目录。

`graph-export-report.json` 记录每个 Domain 的稳定错误码、计数和相对输出路径。变更日志只记录白名单字段，不写入原始异常文本。

## 排查

- `missing_config`：确认 `--cwd` 位于已初始化 scope 内，或显式传入 `--scope`。
- `scope_busy`：等待当前写命令完成后重试。
- `partial_failure`：查看 report 中失败 Domain 的稳定错误码；成功 Domain 已更新，失败 Domain 仍保留旧版本。
- 页面为空：先检查 Domain 是否包含已声明目录和可收集记录，再查看 report 的节点/边计数。
- 本地文件按钮不可用：页面必须保持在固定的 `.llm-wiki/.meta/graph/<domain>/graph.html` 位置，并通过 `file://` 打开。
