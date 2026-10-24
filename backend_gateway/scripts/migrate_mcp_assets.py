"""一次性迁移: 连接器 (mcp) 从"包型"改成"配置型" (2026-10-24).

以前连接器也是打包的: files/.mcp.json + README.md + package/*.zip.
现在连接器**只有一段 MCP 配置**, 写在 manifest.json 里 —— 仓库里一个连接器
只有一个 manifest.json, 上架/更新都只填 JSON, 不碰包.

这个脚本把存量的连接器迁过去:
    1. 读 files/.mcp.json → 写进 manifest.mcp_config
    2. 删掉 files/ 、package/ 、README.md (配置已经在 manifest 里了)
    3. 同步 DB 镜像 (Asset.mcp_config) + 重新渲染 index.json
    4. 提交 + 推送

用法 (在 backend 容器里跑):
    docker exec -w /app -e PYTHONPATH=/app test-mate-backend-1 python scripts/migrate_mcp_assets.py
    # 先看看会改什么:
    docker exec -w /app -e PYTHONPATH=/app test-mate-backend-1 python scripts/migrate_mcp_assets.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from app.core import git_sync
from app.core.market_catalog import INDEX_PATH, stage_index
from app.db.session import AsyncSessionLocal
from app.models.asset import Asset
from sqlalchemy import select


def _git(*args: str) -> None:
    import subprocess

    p = subprocess.run(
        ["git", *args], cwd=git_sync.WORKSPACE, capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {p.stderr or p.stdout}")


async def main(dry_run: bool) -> int:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(Asset).where(Asset.kind == "mcp"))
        ).scalars().all()
        if not rows:
            print("没有连接器资产, 不用迁 ✓")
            return 0

        plan: list[tuple[Asset, dict]] = []
        for a in rows:
            cfg = a.mcp_config
            src = ""
            if not cfg:
                # 从老位置的 files/.mcp.json 里捞
                cand = git_sync.WORKSPACE / a.git_path / "files" / ".mcp.json"
                if cand.is_file():
                    try:
                        cfg = json.loads(cand.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as e:
                        print(f"  ⚠️ {a.code} 的 .mcp.json 解析失败, 跳过: {e}")
                        continue
                    src = str(cand.relative_to(git_sync.WORKSPACE))
            if not cfg:
                print(f"  ⚠️ {a.code} 找不到 MCP 配置, 跳过")
                continue
            plan.append((a, cfg))

        print(f"要迁移 {len(plan)} 个连接器:")
        for a, cfg in plan:
            servers = list((cfg or {}).get("mcpServers", {}).keys())
            print(f"  {a.code:24} {a.git_path}  servers={servers}")

        if dry_run:
            print("\n(dry-run, 什么都没改)")
            return 0

        for a, cfg in plan:
            base = git_sync.WORKSPACE / a.git_path
            mf = base / "manifest.json"
            if not mf.is_file():
                print(f"  ⚠️ {a.code} 缺 manifest.json, 跳过")
                continue
            manifest = json.loads(mf.read_text(encoding="utf-8"))
            manifest["mcp_config"] = cfg
            manifest["package_sha256"] = ""
            manifest["package_name"] = ""
            manifest["files"] = []
            manifest["doc_file"] = ""
            mf.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # 配置已经在 manifest 里了 —— 老的三样一并清掉
            shutil.rmtree(base / "files", ignore_errors=True)
            shutil.rmtree(base / "package", ignore_errors=True)
            (base / "README.md").unlink(missing_ok=True)
            a.mcp_config = cfg
            print(f"  ↪ {a.code}: 配置已写进 manifest, 老 files/package/README 已清")

        await session.commit()

        # index.json 重新渲染 (DB 是真相源)
        await stage_index(session)
        _git("add", "-A", "assets", INDEX_PATH)
        _git(
            "-c", "user.name=testmate", "-c", "user.email=testmate@local",
            "commit", "-m",
            "chore(market): 连接器改成配置型 —— MCP 配置写进 manifest, 不再打包",
        )
        rc, so, se = git_sync._run_git(
            ["push", "origin", git_sync.git_branch()], cwd=git_sync.WORKSPACE
        )
        if rc != 0:
            print(f"❌ 推送失败: {se or so}")
            return 1
        head = git_sync._run_git(["rev-parse", "HEAD"], cwd=git_sync.WORKSPACE)[1]
        print(f"\n✅ 迁移完成并已推送 (HEAD {head.strip()[:12]})")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
