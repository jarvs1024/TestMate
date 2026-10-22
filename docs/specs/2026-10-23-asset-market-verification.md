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

## 7. 已知未覆盖

- **前端 File System Access 通道的真实写盘** —— 无头浏览器里拿不到目录选择器,
  只验证了「前端已写盘 → 后端记录安装」这一半 (`channel=frontend` 记录成功)。
  完整落盘需人工在有头浏览器里点一次。
- **连接器 (mcp) 类型的上传** —— 后端明确不支持一键安装, 安装端点返回 409 已有单测覆盖,
  但没走完整的上传 → 审核 → 上架链路 (mcp 资产靠 seed 写入)。
