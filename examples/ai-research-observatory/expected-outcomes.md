# Observatory Runtime 0.3 示例预期结果

这些结果描述稳定状态和安全不变量，不固定 Registry、Profile、Mapping 或内容 digest。实际运行必须核验 Runtime 返回的 canonical digest，而不是复制文档中的值。

| Request | Expected outer status | Required invariant |
| --- | --- | --- |
| Harness resolve | `ok` | 返回 Workload Principal 和 Registry、Policy、Profile、Mapping 四个授权 digest |
| Harness copy/write/log | `ok` | Mapping Owner 是 Harness；失败时不执行 legacy fallback |
| Harness find/load | `ok` | 以 Harness Principal 查询，正文保持 `data_only` |
| Skill find | `ok` | Skill 使用自己的身份查询同一条已接受记录 |
| Skill write with Harness Mapping | `mapping_owner_mismatch` | 目标记录 checksum 不变 |

`principal_not_found`、`principal_contract_stale`、`profile_mismatch` 和 `mapping_owner_mismatch` 都不是空查询结果。调用方必须保留真实状态；持久写入失败关闭。
