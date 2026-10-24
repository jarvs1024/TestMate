"""一次性迁移: 业务分类重排 (2026-10-24) —— 改分类 + 搬目录.

背景: 分类从"主题词" (Trace 诊断 / FW 比对 / 老化任务 …) 改成
      "测试全流程的阶段" (方案用例 / 环境运维 / 任务调度 / 流程管控 /
      质量诊断 / 知识资产 / 其他).

一次做完三件事 (都在同一个 commit 里, 索引不会出现中间态):
    1. GitLab 目录搬家: assets/{kind}/{旧slug}/{code} → assets/{kind}/{新slug}/{code}
    2. manifest.json 里的 category / git_path 跟着改
    3. DB 镜像 (Asset.category / Asset.git_path) 跟着改 + index.json 重新渲染

用法 (在 backend 容器里跑, 工作区和 DB 都在那儿):
    docker exec -w /app test-mate-backend-1 python scripts/migrate_categories.py
    # 先看看会改成啥 (不落盘):
    docker exec -w /app test-mate-backend-1 python scripts/migrate_categories.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys

from app.core import git_sync
from app.core.market_categories import normalize, slug_of
from app.core.market_catalog import (
    INDEX_PATH,
    asset_git_path,
    build_manifest,
    stage_index,
)
from app.db.session import AsyncSessionLocal
from app.models.asset import Asset
from sqlalchemy import select

# code → 新分类 (人工确认过的映射)
MAPPING: dict[str, str] = {
    "test-plan-assistant": "方案用例",      # 测试方案
    "testcase-template-gen": "方案用例",     # 用例模板
    "nvme-spec-cheatsheet": "知识资产",     # 规格速查
    "ssd-log-cheatsheet": "知识资产",       # log 速查
    "ssd-log-doctor": "质量诊断",            # log 诊断
    "ssd-test-debug": "质量诊断",           # 测试调试
    "burn-result-reader": "任务调度",       # 老化任务结果
    "code-review-pipeline": "任务调度",     # 检视流水线 = 调度
    "pr-agent-review": "流程管控",          # PR 变更单流转
    "review-agent-board": "流程管控",       # 审核看板
    "test-report-gen": "流程管控",          # 测试报告
    "weekly-report-assistant": "流程管控",  # 周报
    "testmate-machine-ops": "环境运维",     # 机台 = 环境
    "dingtalk-notify": "环境运维",          # 通知助手
}


def _git(*args: str) -> None:
    p = subprocess.run(
        ["git", *args], cwd=git_sync.WORKSPACE, capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {p.stderr or p.stdout}")


async def main(dry_run: bool) -> int:
    async with AsyncSessionLocal() as session:
        assets = list((await session.execute(select(Asset))).scalars().all())
        by_code = {a.code: a for a in assets}

        plan: list[tuple[Asset, str, str, str]] = []   # (asset, 新分类, 旧路径, 新路径)
        for code, new_cat in MAPPING.items():
            a = by_code.get(code)
            if a is None:
                print(f"  ⚠️ 资产不存在, 跳过: {code}")
                continue
            new_cat = normalize(new_cat)
            new_path = asset_git_path(a.kind, new_cat, code)
            if a.git_path == new_path and a.category == new_cat:
                continue
            plan.append((a, new_cat, a.git_path, new_path))

        if not plan:
            print("没有需要迁移的资产 ✓")
            return 0

        print(f"要迁移 {len(plan)} 个资产:")
        for a, new_cat, old_path, new_path in plan:
            print(f"  {a.code:24} {a.category:8} → {new_cat:6}  {old_path} → {new_path}")

        if dry_run:
            print("\n(dry-run, 什么都没改)")
            return 0

        # ---- 1. 目录搬家 (git mv, 历史保留) ----
        for a, new_cat, old_path, new_path in plan:
            if old_path == new_path:
                # ⚠️ 只是**改了显示名** (slug 冻结 → 目录不动) —— 这就是
                #    "分类改名不搬家" 的设计: 只改 manifest 里的 category 即可.
                print(f"  ↪ 只改名, 目录不动: {old_path} ({a.category} → {new_cat})")
                continue
            src = git_sync.WORKSPACE / old_path
            dst = git_sync.WORKSPACE / new_path
            if not src.is_dir():
                print(f"  ⚠️ 老目录不存在, 跳过搬家: {old_path}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            _git("mv", old_path, new_path)
            print(f"  ↪ 目录已搬: {old_path} → {new_path}")

        # ---- 2. manifest 里的 category / git_path 跟着改 ----
        for a, new_cat, old_path, new_path in plan:
            mf = git_sync.WORKSPACE / new_path / "manifest.json"
            if not mf.is_file():
                continue
            try:
                manifest = json.loads(mf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            manifest["category"] = new_cat
            manifest["git_path"] = new_path
            mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # ---- 3. DB 镜像 ----
        for a, new_cat, old_path, new_path in plan:
            a.category = new_cat
            a.git_path = new_path
        await session.commit()

        # ---- 4. index.json 重新渲染 (DB 是真相源) ----
        await stage_index(session)
        _git("add", "-A", "assets", INDEX_PATH)
        _git(
            "-c", "user.name=testmate", "-c", "user.email=testmate@local",
            "commit", "-m",
            "chore(market): 业务分类调整 "
            "—— 分类目录随之搬家",
        )
        rc, so, se = git_sync._run_git(["push", "origin", git_sync.git_branch()], cwd=git_sync.WORKSPACE)
        if rc != 0:
            print(f"❌ 推送失败: {se or so}")
            return 1
        print(f"\n✅ 迁移完成并已推送 (HEAD {git_sync._run_git(['rev-parse','HEAD'], cwd=git_sync.WORKSPACE)[1].strip()[:12]})")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
