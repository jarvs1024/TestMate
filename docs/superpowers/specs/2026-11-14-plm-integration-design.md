# PLM 集成（账号绑定 + 内置 MCP）设计

> 状态：已实现（设计时为 14 个工具，现以 `/mcp/plm` 的 `tools/list` 为准）
> 日期：2026-11-14
> 参考实现：`/Users/jarvs/AiTestX`（浏览器扩展桥接版 MCP）
> 目标读者：实现者、评审者、运维

## 1. 背景与目标

在 PingCode 集成（[2026-11-12-pingcode-integration-design.md](2026-11-12-pingcode-integration-design.md)）已落地的
凭据框架上，接入 PLM（`https://plm.twsc.com.cn/`）的问题单与用例库能力：

1. 个人中心「平台认证」绑定各自的 PLM 账号；后端 CAS 登录并缓存 token / cookies，过期自动重登。
2. 新增内置 MCP 域 `/mcp/plm`，本期固定 14 个工具，读接口与 AiTestX 行为对齐。
3. 建单严格校验：必须关联项目、问题类型必须能预占合规 WSD 单号、必须有处理人、必填属性与下拉选项必须合规；
   保存后反查单号与处理人，任一失败即报错。
4. 附件沿用 AiTestX 的 jssdk 分片流程：`createFileUploadTask` → DES-CBC 解密 PUT → `saveFileUploadBusiness`。

## 2. 已核实的接口契约

均来自 AiTestX 浏览器扩展真实抓包（`content/plm-bridge.js`、`background/sw.js`）：

| 能力 | 请求 |
|---|---|
| 问题单列表 | `POST /yonbip-mm-plmrd/bill/list?serviceCode=plm_base_question_manage&terminalType=1`，body 经 zlib 压缩 + `enable-deflate: true` |
| 问题单详情 | `GET /yonbip-mm-plmrd/bill/detail?id=...&billnum=baseQuestion&sbillno=baseQuestionList&orgId=...` |
| 模板元数据 | `POST /mdf-node/meta`，取 `viewmeta.view.containers` 里 `optionwidget.enumArray` |
| 字典 | `GET /yonbip-mm-plmrd/pub/ref/getRefMeta`（成员还需 `GET /mdf-node/client/getInitFilterInfo`）→ `POST /yonbip-mm-plmrd/bill/ref/getRefData`（deflate） |
| 我名下项目 | `POST /bill/ref/getRefData?refCode=IMP-PLM-RDPM.plm-rdpm_project_20210410Ref`，`data={"owner": "<业务 userId>"}` |
| 预占单号 | `POST /questionCgr/allowCreateQuestion` → `POST /questionCgr/getLcDetail`（失败重试一次）→ `POST /questionCgr/getCode` |
| 建单 | `POST /bill/add`（取附件槽位）→ `POST /bill/save?cmdname=cmdSave&businessActName=问题管理-保存`，body 为 `{billnum, data: JSON.stringify(fields)}` |
| 评论 | `GET/POST /iuap-apcom-file/rest/v1/comment/yonbip-mm-plmrd+YonSuite/{id}/comments[/add]` |
| 附件列表 | 记录里 `mdf_<uuid>` 分组 → `GET /iuap-apcom-file/rest/v1/file/yonbip-mm-plmrd+mdf/{groupId}/files` |
| 附件上传 | `GET /jssdk/version`（KeyIvParameter）→ `POST /v2/file/createFileUploadTask` → DES-CBC 解密 PUT → `POST /v2/file/saveFileUploadBusiness` |
| 用例列表 | `POST /bill/list?type=test&serviceCode=imp_gds_doc`，固定 `billnum`/`filtersId`/`tplid` 与 `newest_flag eq 1` |
| 用例详情 | `GET /bill/detail?type=test&billnum=40deda4a-...`，步骤取 `Step02` / `ExpectedResult1`，预置条件取 `Precondition` |

Web 端把请求体 zlib 压缩（`CompressionStream('deflate')`）；服务端用 Python `zlib.compress` 等价实现。
附件地址 = DES-CBC/PKCS7 加密的 `{url, headers, method}`，key 取 `KeyIvParameter` 最后一个 `-` 前后各 8 字节。

## 3. 范围与非目标

### 本期范围
- `/mcp/plm` 15 个工具 + `plm:read` / `plm:write` scope
- 内置连接器卡片 `testmate-plm`（扩展库展示，配置随部署地址自适应）
- 严格建单校验 + WSD 单号预占 + 重复单号中止 + 保存后反查
- 附件随建单上传（最多 3 个、单个 ≤10MB、合计 ≤20MB，共享同一 `businessId`）

### 非目标
- 用例库写入（用例只读）
- 问题单状态流转 / 编辑 / 关闭
- 附件独立上传工具（本期随建单一起上传）

## 4. 工具清单

命名规则与 PingCode 一致：`plm_<领域>_<动作>_<对象>`，领域分 `common`（通用）、`issue`（问题单）、`case`（用例库）。

| 工具 | scope | 说明 |
|---|---|---|
| `plm_common_whoami` | read | 绑定状态与最近登录结果 |
| `plm_common_list_projects` | read | 我名下可关联项目 |
| `plm_common_search_members` | read | 人员字典（处理人） |
| `plm_issue_get_create_meta` | read | 必填字段、下拉选项 id、项目列表与提示 |
| `plm_issue_search` | read | 问题单列表检索 |
| `plm_issue_get` | read | 详情 + 描述 + 内联截图 + 附件 |
| `plm_issue_list_comments` | read | 评论 |
| `plm_issue_list_attachments` | read | 附件与字段内嵌截图 |
| `plm_issue_download_attachment` | read | 附件下载（图片内联 base64） |
| `plm_case_catalog_tree` | read | 用例目录树（可按 `catalog_id` / `keyword` 定位节点） |
| `plm_case_search` | read | 用例库检索，支持 `catalog_id` / `catalog_name` 按目录过滤 |
| `plm_case_get` | read | 用例详情（步骤/预期） |
| `plm_issue_preview` | write | 建单预校验，不提交 |
| `plm_issue_create` | write | 严格建单，`confirm=true`，10 分钟幂等 |
| `plm_issue_add_comment` | write | 追加评论，`confirm=true` |

目录过滤：`plm_case_search` 先按 `catalog_id` / `catalog_name` 解析目录节点，再把该目录子树全部节点 id 作为
`condition.simpleVOs` 的 `doc_classfiy_id in [...]` 过滤。PLM 的 `ids` + `path` 目录过滤在分页时会出现
页窗错位（同一条重复、另一条遗漏），不复用。

## 5. 严格建单流程

1. `confirm` 必须为 `true`；`client_request_id` 命中 Redis 幂等键时直接返回上次结果（TTL 600s）。
2. 实时拉取模板选项、问题类型字典与我名下项目，合并内置兜底选项。
3. 项目必须命中 `project_id` 或 `project_code`，否则拒绝（`invalid_arguments`）。
4. 必填字段与选项校验（`schema.validate_create`，由 handler 统一拒绝以便返回中文说明）：
   - 必填：`name`、`questionCgrId`、`raisePerson`、`quesBelongArea`、`QuesmoduleSel`、`projectJD`、
     `questionTdArea`、`questionPriority`、`quesSever`、`attribute2`（与 PLM 提单属性 * 一致）；
   - `genyinfenxi` / `attribute1` 省略时补 `NA`；
   - 所有下拉值必须命中选项 id，传中文名会被拒绝；
   - 拒绝信息列出中文属性名与合法选项（如 `严重程度(quesSever=9) 合法: 1=致命, 2=严重, ...`），
     `plm_issue_preview` 同时返回 `missing_fields` / `invalid_fields` 明细。
5. 问题描述（`description_template`，默认 `standard`）：
   - `standard`：复用 PingCode/AiTestX 同一份 10 段模板渲染 `description_fields`
     （问题描述 / 测试环境 / 版本信息 / 测试仪器 / 软件工具 / 被测设备 / 测试用例信息 / 定位履历 /
     初步分析结论 / 测试日志），未填字段渲染为 `-`；
   - 渲染后按 PLM 富文本归一化：10 等分栅格（标签 `colspan=2`、内容 `colspan=8`、段标题 `colspan=10`）、
     字号 12px + `line-height:1.65`、换行转 `<br>`，与 AiTestX `applyTableGridForEqualCols` /
     `plmNormalizeDescHtml` 对齐；
   - `custom`：直接使用 `description` 原文；省略时按标题生成段落；
   - 其它取值拒绝（`invalid_arguments`），`plm_issue_preview` 的 payload 返回
     `description_template`、`description_text` 与渲染后的 `values.description`。
6. 预占单号：`allowCreateQuestion`（失败可继续）→ `getLcDetail`（取 `schId`，失败 0.5s 后重试一次）→
   `getCode`，单号必须匹配 `^WSD\d{8,}$`。
7. 单号查重：列表中已存在同 `code` 时中止（`plm_duplicate_code`），避免重复提单。
8. 附件（可选）：先 `bill/add` 取槽位，再上传；任一失败即中止，不保存半成品。
9. `bill/save` 提交完整字段（项目关联对象、流程模板、状态、处理人、附件槽位等）。
10. 保存后反查：按单号查列表，且 `raisePerson` 必须一致；否则 `plm_verify_failed`。
11. 结果返回单号、id、可打开链接、项目、处理人、状态、附件数与是否验证通过。

## 6. 错误码

| code | 场景 |
|---|---|
| `integration_not_configured` | 未绑定 PLM 账号 |
| `integration_reauth_required` | 登录态失效 / 连续登录失败冷却 |
| `integration_unavailable` | PLM 不可达 |
| `invalid_arguments` | 项目未命中、必填缺失、选项非法、附件超限 |
| `confirmation_required` | 写操作缺少 `confirm=true` |
| `plm_duplicate_code` | WSD 单号已存在 |
| `plm_verify_failed` | 保存后反查不到单据或处理人未写入 |
| `plm_error` | 其它 PLM 业务错误（单号生成失败等） |
| `not_found` | 问题单 / 用例 / 目录节点不存在 |
| `catalog_not_found` | 按名称检索时目录不存在 |
| `ambiguous_catalog` | 目录名重名，需改用 `catalog_id` |
| `download_failed` | 附件下载失败 |

## 7. 代码结构

| 路径 | 作用 |
|---|---|
| `backend_gateway/app/integrations/plm/client.py` | CAS 登录、zlib 请求、PUT / 下载、错误映射 |
| `backend_gateway/app/integrations/plm/session_manager.py` | 登录态缓存、单飞、失败冷却、重登重试 |
| `backend_gateway/app/mcp/plm/normalize.py` | 记录到稳定输出的纯函数 |
| `backend_gateway/app/mcp/plm/schema.py` | 建单字段、选项与严格校验 |
| `backend_gateway/app/mcp/plm/templates.py` | 标准 10 段描述模板 + PLM 栅格/字号归一化 |
| `backend_gateway/app/mcp/plm/adapter.py` | 14 个 handler 与接口实现 |
| `backend_gateway/app/mcp/plm/tools.py` / `server.py` | ToolSpec 与 FastMCP 注册 |
| `backend_gateway/tests/test_plm_mcp.py` | schema/scope、只读适配、严格建单、幂等、附件 |

## 8. 安全

- 密码仅用于 CAS 登录；落库前经 AES-256-GCM 加密，接口不回传明文。
- 会话 token / cookies 加密落库，缓存重建时校验 `orgId`。
- 写操作统一 `confirm=true`；建单幂等键按用户隔离。
- 下载地址必须与 PLM 同源；原始字段输出前剔除 token/cookie/authorization。

## 9. 验收

- 单测：`tests/test_plm_mcp.py` 覆盖 14 工具 schema、写 scope、建单各拒绝分支、重复单号、验证失败、
  幂等与附件上传。
- 联调：部署 8081 后绑定账号，双系统只读冒烟；提单验证仅在 `TIANFU` 项目执行，并回读单号与处理人。
