# 资产市场 —— 真实包端到端验证报告

> 日期: 2026-10-23 · 分支: `feature/ai-asset-marketplace`
> 结论: **29 个市场端点全部被真实业务场景覆盖, 97 项检查全过, 修复 9 个真 bug**

## 1. 为什么之前的验证不够

之前的 e2e 脚本造的是**占位级包** —— 一个 `SKILL.md` 加一行 `reference/errcodes.md`。
这测不出:

- 多文件目录结构能不能正确落盘 (`references/` `scripts/` `assets/`)
- 隐藏目录的处理 (`.qoder-plugin/`)
- 安装产物和包内容是否**逐字一致**
- **plugin 包从未被端到端上传过** —— 15 个种子资产里的 3 个 plugin 是直接写 DB + git,
  绕过了上传 / 审核 / 安装的完整流程

## 2. 这次用的两个真实包

`scripts/make_real_packages.py` 构造, 结构完整、内容真实:

### `ssd-log-triage` (skill)

```
ssd-log-triage/
  SKILL.md                        完整 frontmatter (name/description/allowed-tools/metadata)
  README.md
  references/nvme-error-codes.md  NVMe 状态码对照表 (0x85 介质错误 = 换盘信号 …)
  references/log-patterns.md      日志模式判读
  scripts/scan_nvme_log.py        真能跑的日志扫描器 (按错误类别聚合计数并给结论)
  assets/report-template.md       分诊报告模板
```

### `qoder-trace-kit` (plugin)

```
qoder-trace-kit/
  .qoder-plugin/plugin.json       插件清单 (name/displayName/version/commands/agents/skills/hooks)
  README.md
  commands/trace-collect.md       /trace:collect 斜杠命令
  commands/trace-analyze.md       /trace:analyze 斜杠命令
  agents/trace-reviewer.md        审查 agent
  skills/trace-basics/SKILL.md    子技能
  hooks/hooks.json                采集后置校验 hook
  hooks/after-trace.sh            真能跑的 shell 校验脚本
```

## 3. 端点覆盖表 (29/29)

`scripts/e2e_real_packages.js`, 97 项检查。两种包各走完整生命周期。

| 端点 | 验证项 |
|---|---|
| `GET /assets` | 列表: kind 过滤 / `status=all` / client_id 可见性 / 卸载后隐藏 |
| `GET /assets/categories` | 分类计数 |
| `GET /assets/jobs` | 任务列表 |
| `GET /assets/jobs/{id}` | 等 job 走到终态 (staged → pushed / failed) |
| `POST /assets/jobs/{id}/retry` | **制造推送失败 → 恢复远端 → 重试成功** |
| `GET /assets/audits` | 审计留痕 |
| `GET /assets/sync-status` | 待同步 / 失败计数 |
| `GET /assets/notifications` | 通知回执 |
| `GET /assets/config` | 市场生效配置 |
| `GET /assets/me/installed` | 我的安装 |
| `GET /assets/me/updates` | 更新前后**双向**断言 |
| `GET /assets/{code}` | 详情 |
| `GET /assets/{code}/doc` | 展示文档正文 (skill→SKILL.md / plugin→README.md) |
| `GET /assets/{code}/files` | 文件树 (含子目录与隐藏目录) |
| `GET /assets/{code}/bundle` | 前端通道用的整包内容 |
| `GET /assets/{code}/versions/{v}/download` | 历史版本包下载 (sha256 与原包一致) |
| `GET /assets/{code}/install-target` | 安装目标路径 / 能不能装 / 为什么不能 |
| `POST /assets/preview-package` | 上传前体检 + 类型标志识别 |
| `POST /assets/upload` | 上传 (202) |
| `PUT /assets/{code}` | 更新版本 |
| `POST /assets/{code}/review` | 驳回 + 通过 |
| `POST /assets/{code}/submit` | 重新提交 |
| `POST /assets/{code}/publish` | 上架 / 重新上架 |
| `POST /assets/{code}/unpublish` | 下架 |
| `POST /assets/{code}/install` | 服务端通道落盘 / 前端通道记录 / 版本不符被拒 |
| `DELETE /assets/{code}/install` | 卸载 (清目录) |
| `DELETE /assets/{code}` | 彻底删除 (清 DB + 索引 + 安装目录) |
| `POST /assets/sync` | DB 记录丢失 → 从 index.json 回灌 |
| `GET /assets/probe/gitlab` | GitLab 连通探测 |

## 4. 这轮修掉的 9 个 bug

全部是**真实包跑出来**的, 不是推测。

1. **装错版本静默成功** —— 请求的 version 与资产当前版本不一致时, 落盘用 DB 的版本、
   记录写请求的版本: 用户以为装了新版, 实际装的是旧版, 「可更新」也不再提示, **全程无报错**。
   现在版本不符直接 409。
2. **多版本安装记录被覆盖** —— 安装记录按 `(code, client_id)` 唯一, 装第二版就把第一版覆盖,
   旧版本目录从此没人知道在哪儿, 永远清不掉。改成按 `(code, version, client_id)`。
3. **卸载只删最后一个版本的目录** —— `removed_path` 在循环里被反复覆盖。
4. **彻底删除资产后不清理用户磁盘** —— 资产没了就没法再卸载, 残留永远清不掉。
5. **安装锁文件落在 code 目录里** —— 卸载后只剩带锁文件的空壳。锁移到安装根目录。
6. **`_install_map` 用版本号字符串跟时间戳比大小** —— `datetime > str` 直接 TypeError,
   `/me/updates` 500。⚠️ 这个坑一直藏着: 以前一码一记录, `cur is None` 把比较短路了。
7. **列表可见性没过滤安装记录 status** —— 卸载过的仍算「我已安装的」,
   卸载后下架的资产继续赖在列表上。
8. **同秒装两版时取错版本** (修 2 之后暴露) —— MySQL DATETIME 是**秒级**精度, 两条记录的
   `installed_at` 完全相同, 只比时间戳会取到先装的那版 → 明明装了新版却被误报「可更新」。
   加自增 id 做次级键, 取后装的那版。
9. **install_count 随版本虚高** (修 2 之后暴露) —— 卡片上显示的 `⬇ install_count` 本意是
   「多少台机器装过」, 改成按版本分行后每装一版都 +1。改回按**客户端**计。

## 5. 测试结果

| 层次 | 结果 |
|---|---|
| 后端单元测试 | **163 / 163** (真 MySQL 测试库 + 临时 git 工作区) |
| 前端单元测试 | **27 / 27** (vitest + jsdom) |
| 真实包端到端 | **97 / 97** ← 本轮新增 |
| 市场回归 | 38 / 38 |
| 审核流程回归 | 14 / 14 |
| 场景端到端 | 27 / 27 |
| 设置页回归 | 8 / 8 |
| 钉钉链路回归 | 10 / 10 (真实送达) |

跑完环境零残留: 安装目录清空、DB 只剩 15 个正式资产与 1 个 admin、git 工作区干净、
设置项全部还原。

## 6. 怎么跑

```bash
# 造真实包 + 跑完整生命周期
cd scripts && NODE_PATH=/tmp/tm-e2e/node_modules node e2e_real_packages.js

# 只造包
python3 scripts/make_real_packages.py --out-dir .e2e-out
```

⚠️ 脚本会改生产设置 (审核开关 / 发布白名单 / 钉钉通知开关), **改前存原值、结束还原**;
会静音钉钉通知, 避免往真实群刷屏。脚本可重复运行 (开头预清理同名残留资产)。

## 7. 安装方式（2026-10-23 调整）

安装**只有一条路**: 详情抽屉里点「下载」, zip 落到浏览器的默认下载目录,
用户自己解压.

| 做法 | 说明 |
|---|---|
| 下载 | 下 `<code>-<version>.zip`, 解压到 `~/.qoder-cn/skills/<code>/` (plugin 是 `~/.qoder-cn/plugins/cache/qoder-marketplace/<code>/<version>/`) |

- 详情抽屉的动作区现在只有: **下载** / 更新版本 / 下架 / 彻底删除
- 「安装到本地」「重新安装」「卸载」**全部去掉**, 安装对话框也一并删掉
- 浏览器写盘 (File System Access) 与服务端写盘**都已下线**
- 设置页的三个安装目录项 (`marketplace.install.skill_dir` / `.plugin_dir` / `.enabled`)
  已移除, DB 里的残留行在启动时一并清掉
- 后端不写盘: `resolve_host_path` / `_install_files` / `_remove_install_dirs` 全部删除,
  install 端点只保留**安装记录** (哪个客户端、什么版本、装没装)
- 可见性简化成「在架 ∪ 我提交的」—— 以前"已装用户仍能看到下架资产"是为了让用户
  能去更新/卸载, 现在这两件事都没了, 那条规则也没意义了

### 7.1 下载计数保留 (语义正名为 download_count)

「安装次数」是**猜不出来的** —— 后端只知道用户点了下载, 不知道人家到底解压没有.
但**下载次数是准确的**: 下载端点自己就知道有人下了. 所以恢复一个语义正确的计数:

- `download_count` 列 (迁移 0011), 在下载端点里**原子自增** (先读后写会丢计数)
- 卡片上显示「⬇ N」, index.json 里也带上 (跨实例同步)
- hot 排序: 精选 → 下载次数 → 最近更新
- 「✓已安装」「↑可更新」两个徽标**不恢复** —— 那才是虚假语义

## 8. 这轮又挖出来的 bug

### 8.1 同步器把待审核资产改成已上架 ⚠️

同步器 (`sync_puller`) 每 30 秒从远端拉一次, 以**远端 manifest.json** 的
`publish_status` 为权威回灌 DB. 但:

- **上传时**写的 manifest.json 来自 `build_manifest()`, **根本没有 publish_status 字段**
  (只有上下架走 `_set_publish_state` 时才写这个字段)
- 同步器读到 `None` 时**猜成 "published"** → 把 DB 里的 `pending` 覆盖掉

**后果: 任何待审核的资产, 下一个同步周期就会被自动改成已上架 —— 审核形同虚设.**
而且只在冲突判定触发时发作, 表现为"端到端偶发失败", 极难复现.

两处都修了:

1. **根本修法** —— 上传时把最终 `publish_status` 写进 manifest.json (权威来源统一)
2. **防御** —— 同步器遇到远端 manifest 缺这个字段时**不猜**, 以本地为准
   (`_remote_publish_status()` 提成纯函数, 可单测)

复验: e2e 新增 ③b「等一个同步周期(35 秒)后仍是待审核」✓

### 8.2 e2e 脚本崩了会留下残留资产

`e2e_market_scenarios.js` 中途失败时资产没删 → 下次跑上传直接 **409**,
后面整条流程状态全乱. 已在脚本开头加**预清理**, 让它可重复运行.

另外 `e2e_market.js` 的通知开关恢复原本不在 `finally` 里 —— 中途失败会把
"静音通知"这个**生产配置**留在关的状态. 已移进 `finally` (并把 `browser.close()`
也挪进去, 否则异常时浏览器进程泄漏); Z2 改成跟**原值**比而不是硬编码 `true`.

## 9. 多用户场景的权限边界

市场是**多人共享**的仓库, 这一节全是多用户下才暴露的问题。

### 9.1 越权: 白名单用户能改别人的资产 ⚠️

改资产的写操作 (更新版本 / 下架 / 彻底删除) 以前只查"是不是发布者"(白名单),
于是**任何在白名单里的用户都能改别人上传的资产** —— 白名单的含义是
"可以往市场上放东西", 不是"可以改别人放的东西".

而且前端的 `can-edit` 是**硬编码 true** —— 任何登录用户打开别人的资产都能看到
「更新版本 / 下架 / 彻底删除」按钮, 后端也不拦 —— UI 和后端一起放行, 是完整的越权链路.

现在:

- 后端加 `_assert_can_modify()`: 只有**作者本人**或**管理员**能改
  (publish / unpublish / delete / update 四个端点)
- 前端 `can-edit` 改成按作者判断, 与后端一致
- 管理员仍可操作任何人的资产 (运营需要, 比如清理不合规的资产)

### 9.2 作者归属可伪造

`author` 字段以前来自前端表单 —— 任何人都能把资产挂到别人名下, 于是
"谁能改这个资产"的判断也就跟着落到别人头上了.

现在 `author` **强制取上传者的用户名**, 不再接受前端指定.
(上传表单本来就没有这个字段, 是 API 层留的口子)

### 9.3 审核瓶颈: 只有 admin 能审

团队里 admin 一个人审不过来, 是唯一的瓶颈. 新增设置项
`marketplace.review.reviewer_usernames` (逗号分隔的用户名):

- 审核人**只能审**, 不能改别人上传的资产 (那是作者的事)
- 审核人在列表的「待审核」筛选里看得到**所有**待审资产 (普通用户只看自己的)
- 详情里带 `can_review` 标记, 前端据此显示「通过审核 / 驳回」按钮

### 9.4 409 提示带作者

code 撞了的时候, 提示里带上**是谁的**资产 —— 多用户下"这个名字被谁占了"很重要.

## 10. 已知未覆盖

- **mcp 类型的上传链路** —— 后端明确不支持一键安装, 安装端点返回 409 已有单测覆盖,
  但没走完整的上传 → 审核 → 上架链路 (mcp 资产靠 seed 写入).
- **内容逐字比对的口径** —— 服务端写盘下线后, "包内容 == 安装产物" 改成
  "包内容 == bundle 接口返回的内容" (上传 → 解包 → 落工作区 → 传给前端写盘),
  前端写盘那一步由单元测试覆盖.
