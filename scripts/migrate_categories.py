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

⚠️ **四处必须一起改, 少一处就自相矛盾**:
    ① GitLab 工作区的目录 (assets/{kind}/{slug}/{code}) —— slug 是目录名, 分类变了目录跟着变
    ② 每个资产的 manifest.json (category + git_path)
    ③ index.json (分类是索引里的一项)
    ④ DB 里的 assets.category / assets.git_path
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
    # ---- 管理协同: 进度 / 风险 / 沟通 ----
    "test-report-gen": "管理协同",         # 测试报告 = 结果可见
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
            if new_path == a.git_path and (a.category or "") == target:
                continue
            plan.append({
                "code": a.code, "kind": a.kind,
                "old_cat": a.category or "", "new_cat": target,
                "old_path": a.git_path, "new_path": new_path,
            })

        print(f"\n分类表 (新): {', '.join(market_categories.names())}")
        print(f"分支: {branch} · 涉及 {len(plan)}/{len(assets)} 个资产")
        print()
        for p in plan:
            print(f"  {p['code']:<24} {p['kind']:<7} {p['old_cat']:<6} → {p['new_cat']:<6}")
            print(f"  {'':<24} {p['old_path']}")
            print(f"  {'':<24} → {p['new_path']}")
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
            if not old_dir.is_dir():
                print(f"❌ 源目录不存在: {p['old_path']}")
                return 1
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            rc, so, se = git(ws, "mv", p["old_path"], p["new_path"])
            if rc != 0:
                print(f"❌ git mv 失败: {p['old_path']} → {p['new_path']}: {se.strip()}")
                return 1
            # manifest: 分类 + git_path 都要改 (git_path 是目录的镜像, 两者必须一致)
            mf = new_dir / "manifest.json"
            data = json.loads(mf.read_text(encoding="utf-8"))
            data["category"] = p["new_cat"]
            data["git_path"] = p["new_path"]
            mf.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            git(ws, "add", "--", p["new_path"])
            print(f"  ✓ {p['old_path']} → {p['new_path']}")

        # ===== 3. 改 DB =====
        print("\n=== 改 DB ===")
        by_code = {p["code"]: p for p in plan}
        for a in assets:
            p = by_code.get(a.code)
            if not p:
                continue
            a.category = p["new_cat"]
            a.git_path = p["new_path"]
            print(f"  ✓ {a.code}: category={a.category} git_path={a.git_path}")
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
    print(f"  DB 与 index.json: {'✅ 一致' if ok else '❌ 有出入'}")

    rc, so, se = git(ws, "status", "--porcelain")
    if so.strip():
        print(f"  ⚠️ 工作区还有未提交改动:\n{so.strip()}")
    else:
        print("  ✅ 工作区干净")

    print("\n✅ 迁移完成" if ok else "\n⚠️ 迁移完成, 但回读发现出入 (见上)")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真做 (默认只预览)")
    args = ap.parse_args()
    rc = asyncio.run(main(apply=args.apply))
    # ⚠️ 关掉引擎再退出 —— 否则 aiomysql 的连接回收会在事件循环关闭后跑,
    #    打印一串 "Event loop is closed" 的无意义堆栈 (看着像出错, 其实是噪音)
    try:
        load_env()
        from app.db.session import engine

        asyncio.run(engine.dispose())
    except Exception:  # noqa: BLE001
        pass
    sys.exit(rc)
