# AI 资产市场 — 功能总览

> 团队共享的插件 / 技能 / 连接器市场。资产真实存放在 GitLab 仓库
> `root/testmate-market`，TestMate 只是它的一个网关。

## 一、核心机制

| 机制 | 说明 |
|---|---|
| **真相源** | GitLab 仓库。每个资产一个目录（`assets/{kind}/{category}/{code}/`），含 `manifest.json`（权威）+ `files/`（内容）+ `package/`（原始包）。本地工作区只是 working copy |
| **双层串行化** | `asyncio.Lock`（进程内）+ `flock`（跨进程/跨实例）。git 的 `index.lock` 是仓库级的，并发 commit 必有一个失败 |
| **落盘即提交** | 上传 → 解包落盘 → 建 job(staged) → 后台 commit+push → job(pushed)。用户立刻看到资产，状态显示"待同步" |
| **单消费者队列** | 所有 git 操作串行，避免把 `index.lock` 错误暴露给用户；失败按指数退避重试 |
| **审核状态机** | `pending`(待审核) → `published`(在架) / `rejected`(已驳回)；`published` → `unpublish_pending`(申请下架，等管理员) → **彻底删除**（通过）/ 恢复在架（驳回或作者撤销）。状态写进 `manifest.json` + `index.json`，别的实例立刻看到 |
| **下架是申请制** | 下架不可逆（确认后资产连文件带索引带记录一起没），市场又是共享的 —— 所以拆两步：作者申请（要手打 code 确认）→ 管理员拍板。**审核下架只有管理员能做**（通过就等于删了别人的资产） |
| **高 semver 胜** | 远端与本地同版本时比提交时间；不同版本比 semver |
| **可见性规则** | 列表默认显示：**在架的 ∪ 待下架审核的（还在架）∪ 我提交的**。管理员可见全部（他是市场运营者，状态由卡片徽标说明） |
| **送达回执** | 每次钉钉通知落一行回执（状态/重试次数/错误原因），失败自动退避重试 |

## 二、HTTP 接口（31 个）

### 读
| 端点 | 用途 |
|---|---|
| `GET /assets` | 列表：类型 / 分类 / 搜索 / 排序 / 上架状态过滤 + 可见性规则 |
| `GET /assets/categories` | 分类与各类型计数 |
| `GET /assets/{code}` | 资产详情 |
| `GET /assets/{code}/doc` | 文档正文（`SKILL.md` / `README.md` + frontmatter） |
| `GET /assets/{code}/files` | 文件树（证明内容真的落盘） |
| `GET /assets/{code}/bundle` | 打包明文文件（前端安装通道用，前端不接触归档格式） |
| `GET /assets/{code}/versions/{v}/download` | 原始包下载 |
| `GET /assets/{code}/install-target` | 安装目标目录 + **能不能装** + 为什么不能 |
| `GET /assets/me/installed` | 我安装的 |
| `GET /assets/me/updates` | 我装了但有新版 |
| `GET /assets/jobs` · `GET /assets/jobs/{id}` | 同步任务 |
| `GET /assets/audits` | 操作审计（谁在什么时候动了什么） |
| `GET /assets/sync-status` | 同步状态汇总（待同步/失败/有更新/待审核/已驳回） |
| `GET /assets/notifications` | 钉钉通知送达回执 |
| `GET /assets/config` | 当前生效配置（工作区/远端/安装目录…） |
| `GET /assets/probe/gitlab` | 仓库探针 |
| `GET /marketplace.json` | Qoder 原生市场清单（免登录，Qoder 拉取用） |

### 写
| 端点 | 用途 |
|---|---|
| `POST /assets/preview-package` | **上传前体检**：能不能解开、有没有展示文档、能不能装、有没有敏感文件 |
| `POST /assets/upload` | 上传（压缩包或文本文件） |
| `PUT /assets/{code}` | 更新版本 |
| `POST /assets/{code}/install` | 安装（server 写盘 / frontend 浏览器写盘） |
| `DELETE /assets/{code}/install` | 卸载 |
| `POST /assets/{code}/unpublish` | **申请下架**（必须带 `confirm_code`=资产 code；提交后进「待下架审核」，资产仍在架） |
| `POST /assets/{code}/unpublish-review` | **管理员审核下架申请**（approve = 彻底删除 / reject = 恢复在架；仅管理员） |
| `POST /assets/{code}/unpublish-cancel` | 作者撤销下架申请（恢复在架，不用等管理员） |
| `POST /assets/{code}/publish` | 重新上架（已下架的软下架资产） |
| `POST /assets/{code}/review` | **管理员审核**（approve / reject，驳回必须填理由） |
| `POST /assets/{code}/submit` | 作者重新提交审核 |
| `DELETE /assets/{code}` | **彻底删除**（文件+索引+DB 记录，审计留痕）—— ⚠️ **仅管理员**，前端不暴露 |
| `POST /assets/sync` | 手动从 GitLab 拉取对齐 |
| `POST /assets/jobs/{id}/retry` | 失败任务重试 |

## 三、设置项（`marketplace` 15 项 + `notification` 9 项）

| key | 说明 |
|---|---|
| `marketplace.git.remote` / `.branch` | GitLab 仓库地址与分支（**运行时可改，立即生效**） |
| `marketplace.git.web_url` | 网页地址 → 市场页"在 GitLab 查看"链接 |
| `marketplace.git.max_push_attempts` | 推送失败自动重试次数 |
| `marketplace.install.skill_dir` / `.plugin_dir` | 本机安装目录（宿主路径） |
| `marketplace.install.enabled` | 是否允许服务端写盘安装 |
| `marketplace.publisher_usernames` / `.publisher_ids` | 发布白名单（用户名 / 用户 ID 两个口径） |
| `marketplace.review.enabled` | 上架是否需要管理员审核 |
| `marketplace.review.admin_self_approve` | 管理员自己上传是否免审 |
| `marketplace.sync.interval_seconds` | 从 GitLab 拉取对齐的周期 |
| `marketplace.max_package_mb` | 上传包体积上限 |
| `marketplace.marketplace_name` | 对外 `marketplace.json` 的 name（决定 Qoder 缓存目录名） |
| `marketplace.public_base_url` | 对外可达基地址 |
| `dingtalk.market_webhook` / `.market_secret` / `.market_keyword` | 钉钉机器人地址 / 加签密钥 / **关键词**（机器人默认开启关键词校验，消息里必须含该词） |
| `dingtalk.notify_on_publish` / `.update` / `.unpublish` | 六个事件的通知开关 —— **上架 / 更新 / 下架 默认打开**（市场动作，大家要知道），**删除 / 待审核 / 驳回 默认关闭**（不刷屏），要发自己在设置页打开 |

## 四、前端（`frontend_web/src/views/Market/`）

| 组件 | 职责 |
|---|---|
| `index.vue` | 市场页：类型 Tab、分类筛选、搜索、状态徽标、返回广场、同步状态条、未过审提示条 |
| `AssetCard.vue` | 资产卡：图标/名称/版本/摘要/标签/权限角标 + **状态徽标**（待审核/已驳回/待下架审核/已下架/待同步） |
| `AssetDetailDrawer.vue` | 详情：文档正文（消毒后渲染）、权限声明、安装步骤、GitLab 链接、审核/申请下架/撤销申请/下架审核操作（**没有「彻底删除」按钮**） |
| `AssetUploadDialog.vue` | 上传：选包即体检、压缩包、权限声明、安装步骤 |
| `AssetInstallDialog.vue` | 安装向导：双通道（服务端 / 浏览器写盘）、可装性预判、复制安装命令 |
| `AssetAuditDrawer.vue` | 操作记录：操作审计（含同步冲突）+ 通知回执两个页签 |

设置页（`views/Settings/index.vue`）：`🔔 通知` 区（钉钉全配置 + 测试发送 + 最近通知）与 `🤖 智能体 → 🧩 资产市场` 区（15 项市场配置 + 仓库连接测试）。

## 五、怎么测

```bash
# 后端单测（136 个）
cd backend_gateway && python -m pytest tests/ -v      # 见 tests/README.md

# 前端单测（27 个）
cd frontend_web && npx vitest run

# 端到端（真实 Chrome，4 个脚本）
cd scripts
node e2e_market_scenarios.js   # 真实业务场景：多角色完整生命周期（27 断言）
node e2e_market.js             # 市场页功能（38 断言）
node e2e_review_flow.js        # 上架审核闭环（15 断言）
node e2e_market_settings.js    # 市场设置与 GitLab 链接（8 断言）
node e2e_dingtalk_settings.js  # 钉钉通知配置与送达（14 断言）
```

> 端到端脚本用 puppeteer-core 驱动**本机真实 Chrome**，不走内置 Browser ——
> 内置 Browser（Electron）在页面加载瞬间会挂起 renderer，XHR 事件不投递、
> 定时器不触发，页面会永远停在 loading，那是验证工具的假象不是被测页面的问题。
