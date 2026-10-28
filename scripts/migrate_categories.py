#!/usr/bin/env python3
"""分类整改迁移 —— 从「按流程阶段」改成「按协作角色」(2026-10-26).

背景:
    旧分类回答的是"这件事在测试流程的**哪一步**":
        方案用例 / 环境运维 / 任务调度 / 流程管控 / 质量诊断 / 知识资产 / 其他
    新分类回答的是"这个资产**替我干什么**":
        质量保障 (兜底) / 效率工具 (提效) / 流程规范 (守流程) / 管理协同 (管协同) / 其他

    为什么换: 流程阶段会随项目变, 角色分工不会; 而且"上传的人"更需要知道
    "我该往哪一类放" —— "它替我兜什么底" 比 "它在流程第几步" 好判断得多.

⚠️ **旧分类不能整块搬** —— 旧分类内部要**拆开**分到不同新分类:
    环境运维 → 效率工具(机台操作) + 管理协同(钉钉通知)
    流程管控 → 流程规范(PR 评审)  + 管理协同(报表/看板)
    任务调度 → 质量保障(老化结果解读) + 流程规范(PR 流水线)
    方案用例 → 效率工具(方案/用例生成)
    知识资产 → 效率工具(速查表)
    质量诊断 → 质量保障

所以这里必须**逐个资产**判定 (见 TARGET_CATEGORY), 不能只按旧分类查表.

文案部分:
    分类换口径的同时, 顺手订正**说错话**的地方 (见 COPY_PATCHES):
      · 互相指错 —— burn-result-reader 让用户去找一个声明"不管这事"的连接器
      · 同一件事两种说法 —— 两个 SSD 技能的 use_when 几乎一字不差
      · 步骤与配置对不上 —— 进程型 (npx) 连接器却写"url 填 …"
      · 定量夸大 —— 声称"40+ 条日志特征", 包里并没有

⚠️ **四处必须一起改, 少一处就自相矛盾**:
    ① GitLab 工作区的目录 (assets/{kind}/{slug}/{code}) —— slug 是目录名, 分类变了目录跟着变
    ② 每个资产的 manifest.json (category + git_path + 文案)
    ③ index.json (分类与文案都在索引里)
    ④ DB 里的 assets.category / assets.git_path / 文案字段
    只改 DB 的话: 同步器下一次就从远端把老分类拉回来 (DB 只是镜像, GitLab 才是真源).

用法:
    # 先看方案 (只读, 不改任何东西)
    python3 scripts/migrate_categories.py --plan

    # 真做 (会 commit + push 到 GitLab)
    python3 scripts/migrate_categories.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend_gateway"
NATIVE_ENV = REPO_ROOT / "deploy" / "native" / "runtime" / "config" / "backend.env"


def load_env() -> None:
    """加载 native 部署的后端环境变量 (env 里已有的优先).

    ⚠️ 必须在 import app.* **之前** —— app.core.config / git_sync 都在导入期读 env.
    """
    if NATIVE_ENV.exists():
        for line in NATIVE_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)
    sys.path.insert(0, str(BACKEND))


# ===== 逐个资产的新分类 =====
#
# 判定依据 (一句话): 这个资产**替使用者干什么**?
#   质量保障 —— 帮你**得出结论 / 定位问题 / 判定结果** (兜住功能、性能、可靠性)
#   效率工具 —— 帮你**做得更快** (自动化、造数、查表、生成)
#   流程规范 —— 帮你**守住流程** (门禁、评审、标准化动作的约束与执行)
#   管理协同 —— 帮你**把事推进 / 让情况被看见** (进度、风险、沟通)
TARGET_CATEGORY: dict[str, str] = {
    # ---- 质量保障: 定位问题 / 判定结果 ----
    "ssd-log-doctor": "质量保障",          # 贴日志定位 assert 与超时点 → 定位问题
    "burn-result-reader": "质量保障",      # 判真失效 vs 环境噪声 → 判定结果
    # ---- 效率工具: 自动化 / 查表 / 生成 ----
    "testmate-machine-ops": "效率工具",    # 机台操作自动化 → 提效
    "test-plan-assistant": "效率工具",     # 生成测试方案 → 提效
    "testcase-template-gen": "效率工具",   # 生成用例模板 → 提效
    "nvme-spec-cheatsheet": "效率工具",    # 查规范不用翻文档 → 提效
    "ssd-log-cheatsheet": "效率工具",      # 日志关键字速查 → 提效
    # ---- 流程规范: 门禁与标准化动作 ----
    "code-review-pipeline": "流程规范",    # PR 审核流水线 = 门禁
    "pr-agent-review": "流程规范",          # PR 评审 = 门禁
    # ---- 效率工具: 自动化 / 查表 / 生成 ----
    "test-report-gen": "效率工具",          # 自动出报告 = 提效手段
    # ---- 管理协同: 进度 / 风险 / 沟通 ----
    "weekly-report-assistant": "管理协同", # 周报 = 进度管理
    "review-agent-board": "管理协同",      # 评审看板 = 进度可见
    "dingtalk-notify": "管理协同",          # 钉钉通知 = 团队内外沟通
}

# 没登记的资产 (以后新传进来的) → 按旧分类给个默认落点, 并且**大声报出来**
FALLBACK_BY_OLD: dict[str, str] = {
    "质量诊断": "质量保障",
    "知识资产": "效率工具",
    "方案用例": "效率工具",
    "环境运维": "效率工具",
    "任务调度": "效率工具",
    "流程管控": "管理协同",
    "其他": "其他",
}

# ===== 下架 =====
#
# 这两个连接器的目标服务**不在 TestMate 的部署范围内**, 照原来的步骤装完是连不上的:
#   pr-agent-review      → pr-agent 服务端已下线 (5050 端口不监听, native 部署里也没有它)
#   testmate-machine-ops → 对应的 MCP 服务端包没发布到 npm (registry 404)
#
# 决定: **下架, 但保留文件** (publish_status=unpublished, 不是 unpublish_pending) ——
#   · 文件仍在 GitLab, 哪天服务补上了, 一条"重新上架"就能回来;
#   · "下架" ≠ "消失": 作者和管理员仍看得到, 只是不在普通用户的货架上.
#   ⚠️ 别用 unpublish_pending —— 那个通过后是**彻底删除**, 与意图相反.
UNPUBLISH: set[str] = {
    "pr-agent-review",
    "testmate-machine-ops",
}

# ===== 文案订正 =====
#
# 只改**说错话 / 自相矛盾**的地方, 不做无谓润色 —— 每个补丁都对应一个能指出来的错:
#
#   ① 互相指错
#      burn-result-reader 的 not_for 让用户"去用 TestMate 机台运维连接器"派发老化,
#      而机台运维自己的 not_for 写着"长时老化任务的派发, 不在本连接器职责内" ——
#      两边互相甩锅, 用户照着走两边落空.
#
#   ② 同一件事两种说法
#      ssd-log-doctor 与 ssd-log-cheatsheet 的 use_when 几乎一字不差, 用户根本分不清
#      该装哪个. 明确分工: 医生=给结论, 速查=给查表路径.
#
#   ③ 步骤与配置对不上
#      dingtalk-notify / testmate-machine-ops 是**进程型** (npx) 连接器, 配置里根本没有
#      url 字段, 但 install_steps 却写"url 填 …" —— 照抄会把人带沟里.
#
#   ④ 定量夸大
#      ssd-log-cheatsheet 声称"最常见的 40+ 条日志特征""决策树", 包里并没有这些内容.
#
#   ⑤ 前置条件没写
#      4 个连接器的目标服务都不是 TestMate 部署的一部分 (详见各处 desc),
#      照着原来的步骤装完是连不上的 —— 把前置条件写清楚.
COPY_PATCHES: dict[str, dict[str, object]] = {
    # ---- ① 互相指错 ----
    "burn-result-reader": {
        "not_for": "需要自己读原始老化日志, 或要派发/调度老化任务 —— 本技能只做结果判读",
    },
    # ---- ② 同一件事两种说法 ----
    "ssd-log-doctor": {
        "description": "按症状给判断步骤: I/O timeout 先看有无 reset controller, assert 看是否伴随 PCIe SPORT Error。\n\n"
                       "只给判断路径, 不替你解析数据。",
        "use_when": "拿到一段 dmesg / FW log, 需要下结论: 是控制器复位、链路误码, 还是固件 assert",
    },
    "ssd-log-cheatsheet": {
        "description": "把 SSD 测试里常见的日志特征整理成对照表, 覆盖 I/O timeout、assert、SMART 告警、thermal throttle 等。\n\n"
                       "给模型一份「看到关键字 → 先查什么 → 怎么排除」的线索表, 比让它自由发挥稳定。",
        "use_when": "拿到一段 dmesg / syslog / FW log, 需要快速判断问题域, 决定下一步查哪条线",
    },
    # ---- 病句 / 含糊 ----
    "test-plan-assistant": {
        "not_for": "已有成熟方案需要直接复用, 或方案已定稿 —— 本技能只负责起稿",
    },
    "test-report-gen": {
        "not_for": "需要分析原始测试数据本身, 而不只是把它整理成报告",
    },
    # ---- ③⑤ 连接器: 步骤与前置条件 ----
    "dingtalk-notify": {
        "install_steps": [
            "在宿主 MCP 配置中新增 server: dingtalk-notify",
            "command 填 npx, args 填 -y dingtalk-notify",
            "按需配置钉钉机器人 webhook 与加签密钥",
            "重启 Agent 会话",
        ],
    },
    "testmate-machine-ops": {
        "description": "经 TestMate 网关访问机台字典与 SSH 通道, 提供机台状态查询与受限的运维动作。\n\n"
                       "⚠️ 对应的 MCP 服务端包尚未发布到 npm, 需自建或等发布后再用。",
        "install_steps": [
            "在宿主 MCP 配置中新增 server: testmate-machine-ops",
            "command 填 npx, args 填 -y testmate-machine-ops (包尚未发布, 需先自建或发布)",
            "指向 TestMate 网关 /api/v1/machines",
            "重启 Agent 会话",
        ],
    },
    "review-agent-board": {
        "description": "连接 ReviewAgent 的 telemetry API, 提供 MR / 建议 / 规则三个维度的聚合数据。\n\n"
                       "⚠️ ReviewAgent 官方只提供 HTTP telemetry 接口 (/api/v1/telemetry/*), 没有 MCP 路由 —— "
                       "需要一个 MCP 适配层, 或改用 TestMate 网关的 /api/v1/review-agent/* 代理。",
        "install_steps": [
            "在宿主 MCP 配置中新增 server: review-agent-board",
            "url 填你的 ReviewAgent MCP 适配层地址 (官方服务不含 /mcp 路由)",
            "重启 Agent 会话",
        ],
    },
    "pr-agent-review": {
        "summary": "pr-agent 检视数据查询 (需自备 pr-agent 服务)",
        "description": "查询 pr-agent 侧的 runs / suggestions / stats, 历史上用于与 ReviewAgent 做数据对照。\n\n"
                       "⚠️ pr-agent 服务端不在 TestMate 的部署范围内, 需自备并暴露 MCP 端点才能用。",
        "use_when": "已自备 pr-agent 服务, 需要与 ReviewAgent 做数据比对, 或排查历史检视记录",
        "not_for": "没有 pr-agent 服务就别装 —— 主用看板请看 ReviewAgent 评审看板",
        "install_steps": [
            "在宿主 MCP 配置中新增 server: pr-agent-review",
            "url 填自备 pr-agent 的 MCP 端点 (默认示例 http://host.docker.internal:5050/mcp)",
        ],
    },
}


def git(ws: Path, *args: str) -> tuple[int, str, str]:
    p = subprocess.run(["git", *args], cwd=str(ws), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


async def main(apply: bool) -> int:
    load_env()

    from app.core import git_sync, market_categories
    from app.core.market_catalog import asset_git_path, stage_index
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from sqlalchemy import select

    ws = git_sync.WORKSPACE
    print(f"工作区: {ws}")
    rc, so, se = git(ws, "status", "--porcelain")
    if rc != 0:
        print(f"❌ 读不到 git 状态: {se.strip()}")
        return 1
    if so.strip():
        print("❌ 工作区不干净, 先处理掉再迁移:")
        for line in so.strip().splitlines()[:20]:
            print("   ", line)
        return 1
    rc, so, _ = git(ws, "rev-parse", "--abbrev-ref", "HEAD")
    branch = so.strip() or "main"

    async with AsyncSessionLocal() as session:
        assets = list((await session.execute(select(Asset).order_by(Asset.code))).scalars().all())

        # ===== 1. 算方案 =====
        plan: list[dict] = []
        unmapped: list[str] = []
        for a in assets:
            target = TARGET_CATEGORY.get(a.code)
            if not target:
                target = FALLBACK_BY_OLD.get(a.category or "", "其他")
                unmapped.append(a.code)
            if target not in market_categories.names():
                print(f"❌ 目标分类 '{target}' 不在分类表里: {a.code}")
                return 1
            new_path = asset_git_path(a.kind, target, a.code)
            # 文案补丁: 只算**真的有差异**的字段 (少改一处就少一处不一致的风险)
            copy_changes = {
                k: v for k, v in COPY_PATCHES.get(a.code, {}).items()
                if getattr(a, k, None) != v
            }
            # 下架: 状态也要变 —— 分类对了但还在架上, 等于没下
            unpublish = a.code in UNPUBLISH and (a.publish_status or "published") != "unpublished"
            if (new_path == a.git_path and (a.category or "") == target
                    and not copy_changes and not unpublish):
                continue
            plan.append({
                "code": a.code, "kind": a.kind,
                "old_cat": a.category or "", "new_cat": target,
                "old_path": a.git_path, "new_path": new_path,
                "copy": copy_changes,
                "unpublish": unpublish,
            })

        print(f"\n分类表 (新): {', '.join(market_categories.names())}")
        print(f"分支: {branch} · 涉及 {len(plan)}/{len(assets)} 个资产")
        print()
        for p in plan:
            print(f"  {p['code']:<24} {p['kind']:<7} {p['old_cat']:<6} → {p['new_cat']:<6}")
            if p["old_path"] != p["new_path"]:
                print(f"  {'':<24} {p['old_path']}")
                print(f"  {'':<24} → {p['new_path']}")
            for k, v in p["copy"].items():
                print(f"  {'':<24} 文案 {k}: {json.dumps(v, ensure_ascii=False)[:90]}")
            if p["unpublish"]:
                print(f"  {'':<24} ⬇ 下架 (publish_status: published → unpublished, 保留文件)")
        if unmapped:
            print(f"\n⚠️ 这些资产不在显式映射表里 (按旧分类兜底): {', '.join(unmapped)}")
        if not plan:
            print("\n✅ 没有需要迁移的资产 (已经是新分类了)")
            return 0
        if not apply:
            print("\n(这是 --plan 预览, 加 --apply 真做)")
            return 0

        # ===== 2. 搬目录 + 改 manifest =====
        print("\n=== 搬目录 + 改 manifest ===")
        for p in plan:
            old_dir = ws / p["old_path"]
            new_dir = ws / p["new_path"]
            # ⚠️ 目录没变 (只改文案) 时不能 git mv —— 源和目标同一个, 会报 "same name"
            if p["old_path"] != p["new_path"]:
                if not old_dir.is_dir():
                    print(f"❌ 源目录不存在: {p['old_path']}")
                    return 1
                new_dir.parent.mkdir(parents=True, exist_ok=True)
                rc, so, se = git(ws, "mv", p["old_path"], p["new_path"])
                if rc != 0:
                    print(f"❌ git mv 失败: {p['old_path']} → {p['new_path']}: {se.strip()}")
                    return 1
            # manifest: 分类 + git_path + 文案 都要改
            # (git_path 是目录的镜像, 必须与实际目录一致)
            mf = new_dir / "manifest.json"
            if not mf.is_file():
                print(f"❌ manifest 不存在: {mf}")
                return 1
            data = json.loads(mf.read_text(encoding="utf-8"))
            data["category"] = p["new_cat"]
            data["git_path"] = p["new_path"]
            for k, v in p["copy"].items():
                data[k] = v
            # 下架: 状态写进 manifest —— **GitLab 是真源**, 少了它, 下一次同步
            # 会把 DB 里的状态覆盖回去 (同步器以远端 manifest 为准).
            if p["unpublish"]:
                data["publish_status"] = "unpublished"
                data["featured"] = False
            mf.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            git(ws, "add", "--", p["new_path"])
            if p["old_path"] != p["new_path"]:
                print(f"  ✓ {p['old_path']} → {p['new_path']}")
            else:
                print(f"  ✓ {p['new_path']} (目录未变)")

        # ===== 3. 改 DB =====
        print("\n=== 改 DB ===")
        by_code = {p["code"]: p for p in plan}
        for a in assets:
            p = by_code.get(a.code)
            if not p:
                continue
            a.category = p["new_cat"]
            a.git_path = p["new_path"]
            # 文案也要同步进 DB —— index.json 是从 DB 重建的, 这里不改, 索引里还是老话
            for k, v in p["copy"].items():
                setattr(a, k, v)
            if p["unpublish"]:
                a.publish_status = "unpublished"
                a.featured = 0
            print(f"  ✓ {a.code}: category={a.category} git_path={a.git_path}"
                  + (f" 文案={list(p['copy'])}" if p["copy"] else "")
                  + (" [已下架]" if p["unpublish"] else ""))
        await session.commit()

        # ===== 4. 重建 index.json =====
        print("\n=== 重建 index.json ===")
        await stage_index(session)
        print("  ✓ index.json 已重写")

        # ===== 5. 清掉搬空了的旧目录 =====
        print("\n=== 清理空目录 ===")
        for p in plan:
            old_dir = ws / p["old_path"]
            if old_dir.is_dir() and not any(old_dir.iterdir()):
                old_dir.rmdir()
                print(f"  ✓ 删空目录 {p['old_path']}")

        # ===== 6. commit + push =====
        # ⚠️ pathspec 里**必须同时带上旧路径和新路径**:
        #    git commit -- <pathspec> 只提交这些路径的当前状态, 不在 pathspec 里的
        #    暂存内容会被**忽略** —— 旧目录的"删除"记录就是 git mv 暂存出来的,
        #    漏了它, 远端会同时留着新旧两份目录.
        paths = sorted({p["new_path"] for p in plan} | {p["old_path"] for p in plan} | {"index.json"})
        print(f"\n=== commit + push ({len(paths)} 条路径) ===")
        result = git_sync.sync_paths_blocking(
            paths=paths,
            message="refactor(market): 分类整改 —— 改成按协作角色划分 (质量保障/效率工具/流程规范/管理协同)",
            author=("market-migrate", "market-migrate@testmate.internal"),
        )
        print(f"  commit={result.commit_sha[:12]} pushed={result.pushed} no_change={result.no_change}")
        if not result.pushed and not result.no_change:
            print("❌ 推送失败 —— 本地那条 commit 已撤销, 远端没变")
            print("   ⚠️ 但 DB 和工作区已经改了: DB 回滚需手工执行, 工作区用 git status 核对")
            return 1

    # ===== 7. 回读核对 =====
    print("\n=== 回读核对 ===")
    ok = True
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(select(Asset).order_by(Asset.code))).scalars().all())
        for a in rows:
            want = TARGET_CATEGORY.get(a.code) or FALLBACK_BY_OLD.get(a.category or "", "其他")
            if a.category != want or a.git_path != asset_git_path(a.kind, want, a.code):
                print(f"  ✗ {a.code}: category={a.category} git_path={a.git_path} (期望 {want})")
                ok = False
            # 文案也要回读 —— 少改一处, 前后端就会说两套话
            for k, v in COPY_PATCHES.get(a.code, {}).items():
                if getattr(a, k, None) != v:
                    print(f"  ✗ {a.code}: {k} 没对上 (期望 {json.dumps(v, ensure_ascii=False)[:60]})")
                    ok = False
            # 下架状态也要回读 —— manifest / DB / 索引三处都得是 unpublished
            if a.code in UNPUBLISH and (a.publish_status or "") != "unpublished":
                print(f"  ✗ {a.code}: publish_status={a.publish_status} (期望 unpublished)")
                ok = False
    idx = json.loads((ws / "index.json").read_text(encoding="utf-8"))
    for e in idx.get("assets", []):
        want = TARGET_CATEGORY.get(e.get("code", ""))
        if want and e.get("category") != want:
            print(f"  ✗ index.json {e.get('code')}: category={e.get('category')} (期望 {want})")
            ok = False
        gp = e.get("git_path")
        if gp and not (ws / gp).is_dir():
            print(f"  ✗ index.json {e.get('code')}: git_path 指向的目录不存在: {gp}")
            ok = False
        for k, v in COPY_PATCHES.get(e.get("code", ""), {}).items():
            if e.get(k) != v:
                print(f"  ✗ index.json {e.get('code')}: {k} 没对上")
                ok = False
        if e.get("code") in UNPUBLISH and e.get("publish_status") != "unpublished":
            print(f"  ✗ index.json {e.get('code')}: publish_status={e.get('publish_status')} (期望 unpublished)")
            ok = False
    # manifest 也要回读 —— 它才是 GitLab 里的真源
    for code, patch in COPY_PATCHES.items():
        ent = next((e for e in idx.get("assets", []) if e.get("code") == code), None)
        if not ent:
            continue
        mf = ws / ent["git_path"] / "manifest.json"
        if not mf.is_file():
            print(f"  ✗ {code}: manifest 缺失 {mf}")
            ok = False
            continue
        mdata = json.loads(mf.read_text(encoding="utf-8"))
        for k, v in patch.items():
            if mdata.get(k) != v:
                print(f"  ✗ {code}: manifest.{k} 没对上")
                ok = False
        if code in UNPUBLISH and mdata.get("publish_status") != "unpublished":
            print(f"  ✗ {code}: manifest.publish_status={mdata.get('publish_status')} (期望 unpublished)")
            ok = False
    print(f"  DB / index.json / manifest: {'✅ 一致' if ok else '❌ 有出入'}")

    rc, so, se = git(ws, "status", "--porcelain")
    if so.strip():
        print(f"  ⚠️ 工作区还有未提交改动:\n{so.strip()}")
    else:
        print("  ✅ 工作区干净")

    print("\n✅ 迁移完成" if ok else "\n⚠️ 迁移完成, 但回读发现出入 (见上)")
    return 0 if ok else 1


async def _dispose_engine() -> None:
    """在**当前**事件循环里把连接池关掉.

    ⚠️ 别在 `asyncio.run()` 之后再 `asyncio.run(engine.dispose())` ——
       引擎的连接是在**第一个**循环上建的, 换到新循环去关, aiomysql 的连接回收
       会在已关闭的循环上跑, 打印一串 "Event loop is closed" 的堆栈.
       那是噪音, 不是出错 —— 但看着像出错, 会让人以为迁移失败了.
    """
    try:
        from app.db.session import engine

        await engine.dispose()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真做 (默认只预览)")
    args = ap.parse_args()

    async def _run() -> int:
        rc = await main(apply=args.apply)
        await _dispose_engine()
        return rc

    sys.exit(asyncio.run(_run()))
