# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库；`balance` 阶段同时返回本次组级发布计划 `release`。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。执行时会为已对平的组登记发布版本，返回体中的 `releases` 列出本批引用的版本。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。整批签发仍要求全部组通过且无隔离行；部分组暂缓时，可签发的组已通过发布包交付，整批保持可暂缓状态。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据、组级发布计划和复核信息的 JSON。

`GET /api/runs/<id>/bundle` 下载本次批次的组级发布包 `group-release-bundle/1`：`released` 逐包收录已签发组，`deferred` 单列暂缓组的原因和计数，`totals`、`checks` 为逐项对账结果。

## 组级发布包

`GET /api/releases` 返回全部发布版本摘要，按 `case`、`version` 排序；`GET /api/runs/<id>/releases` 只返回该批次引用的版本。`GET /api/releases/<id>` 下载单个发布包 `group-release/1`。

发布包字段：

| 字段 | 含义 |
|---|---|
| `id` | 发布版本键，由组、规则版本和采信内容共同决定 |
| `case` | 业务分组 |
| `version` | 该组的第几个内容版本，从 1 起递增 |
| `run_id` | 首次登记该版本的批次 |
| `records` | 该组全部已采信记录，逐字段保留 |
| `counts` | 该组输入、采信、隔离、重复回放和阻塞行数 |
| `verified` | 只含已采信记录、记录归属该组、记录键不重复、无阻塞隔离 |
| `manifest.content_sha256` | 采信内容和计算结论的签名，用于跨批次去重 |

同一组同一份采信内容再次执行时复用原版本，不新增版本行；内容变化才产生下一个 `version`。旧批次和旧版本始终可按 `id` 回读。逐项对账不相合的批次不登记任何发布版本。

暂缓组不会出现在 `/api/releases` 中，其分组、原因和计数保留在批次 `report.release.deferred` 与证据文件的 `release` 段。
