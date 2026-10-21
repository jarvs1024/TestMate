"""拉取同步器 — GitLab → TestMate (反向同步).

之前只有 TestMate → GitLab 的推送. 共享仓库下, 别的成员在 GitLab 页面直接改文件,
本实例完全不知道 —— 这就是"本地数据和库上数据不一致"的根源.

本模块定期:
  1. git fetch origin main
  2. 对比 origin/main 上各资产的 manifest.json 与本地工作区的
  3. 逐资产判定并把胜出方落地到工作区 + 回灌 DB 镜像
  4. 冲突写审计

冲突判定 (用户决策: 高 semver 胜 + 冲突审计):
  - version 不同 → 高 semver 胜
  - version 相同 → 比较 commit 时间, 后推的胜
  - 两种情况都写 asset_audits('conflict_resolved'), 前端可提示

权威是**单资产的 manifest.json**, 不是 index.json —— index.json 是派生物.
这样冲突粒度天然是单个资产, 而不是整个索引的文本冲突.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core import git_sync
from app.core.market_catalog import INDEX_PATH, apply_index_to_db
from app.db.session import AsyncSessionLocal
from app.models.asset import Asset, AssetAudit

logger = logging.getLogger(__name__)

MANIFEST_SUFFIX = "/manifest.json"


class Puller:
    """拉取同步器的运行时状态 (供前端状态条读取)."""

    def __init__(self) -> None:
        self.has_remote_updates: bool = False
        self.conflict_count: int = 0
        self.last_sync_at: datetime | None = None
        self.last_error: str = ""
        self._running = False

    def status(self) -> dict[str, Any]:
        return {
            "has_remote_updates": self.has_remote_updates,
            "conflict_count": self.conflict_count,
            "last_sync_at": self.last_sync_at,
            "last_error": self.last_error,
        }


_puller = Puller()


def get_puller() -> Puller:
    return _puller


def _asset_code_from_manifest_path(path: str) -> str | None:
    """assets/{kind}/{cat}/{code}/manifest.json → {code}"""
    parts = path.strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "assets" and parts[-1] == "manifest.json":
        return parts[3]
    return None


def _parse_manifest(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else None
    except json.JSONDecodeError:
        return None


def _local_manifest(code: str) -> dict | None:
    """本地工作区里某资产的 manifest."""
    files = git_sync.list_files_at_ref("HEAD")
    for p in files:
        if p.endswith(MANIFEST_SUFFIX) and _asset_code_from_manifest_path(p) == code:
            return _parse_manifest(git_sync.read_text_at_ref(p, "HEAD"))
    return None


def _remote_manifests(ref: str) -> dict[str, dict]:
    """远端 ref 上的所有资产 manifest, 按 code 索引."""
    out: dict[str, dict] = {}
    for p in git_sync.list_files_at_ref(ref):
        if not p.endswith(MANIFEST_SUFFIX):
            continue
        code = _asset_code_from_manifest_path(p)
        if not code:
            continue
        m = _parse_manifest(git_sync.read_text_at_ref(p, ref))
        if m:
            out[code] = m
    return out


def _resolve_winner(
    code: str, local: dict | None, remote: dict | None
) -> tuple[str, str]:
    """返回 (胜者, 说明): 胜者 ∈ {local, remote, same}."""
    if local is None and remote is None:
        return "same", "两边都没有"
    if local is None:
        return "remote", "远端新增"
    if remote is None:
        return "local", "仅本地存在"
    lv = local.get("version") or "0"
    rv = remote.get("version") or "0"
    if lv == rv:
        # 同版本 → 后推的胜 (比较 manifest 内容不同才需要处理)
        if json.dumps(local, sort_keys=True, ensure_ascii=False) == json.dumps(
            remote, sort_keys=True, ensure_ascii=False
        ):
            return "same", "内容一致"
        return "remote", "同版本但内容不同, 取远端"
    if git_sync.semver_gt(lv, rv):
        return "local", f"本地版本 {lv} 高于远端 {rv}"
    return "remote", f"远端版本 {rv} 高于本地 {lv}"


async def sync_once() -> dict[str, Any]:
    """跑一轮同步. 返回本次的处理摘要."""
    if _puller._running:
        return {"skipped": "上一轮还没跑完"}
    _puller._running = True
    try:
        # ⚠️ 安全闸: 本地工作区有未提交的资产改动时**必须跳过本轮**.
        #    否则会出现: 用户刚上传完(文件已落盘, 还没 commit) → 本轮同步判定
        #    "本地没有这个资产" → 用远端版本 checkout 覆盖 → 刚上传的文件被冲掉.
        st = git_sync.workspace_status()
        pending_local = [
            ln for ln in (st.get("dirty_files") or [])
            if ln.strip().endswith("/") is False and "assets/" in ln
        ]
        if pending_local:
            logger.info(
                "sync_puller 跳过本轮 (本地有未提交资产改动 %s 项)", len(pending_local)
            )
            return {"skipped": "本地有未提交的资产改动, 本轮跳过"}

        with git_sync._FileLock(git_sync.LOCK_FILE):
            rc, so, se = git_sync._run_git(
                ["fetch", "origin", git_sync.GIT_BRANCH],
                cwd=git_sync.WORKSPACE, timeout=120,
            )
            if rc != 0:
                _puller.last_error = f"fetch 失败: {se.strip()[:200]}"
                return {"error": _puller.last_error}

            ref = f"origin/{git_sync.GIT_BRANCH}"
            remote = _remote_manifests(ref)
            local = _local_manifests()

            # ⚠️ 安全闸 2: 本地有**未推送**的 commit 时跳过整轮.
            #    否则拉取会把远端版本 checkout 到工作区, 覆盖掉本地未推送的工作.
            rc, so, se = git_sync._run_git(
                ["rev-list", "--count", f"{ref}..HEAD"], cwd=git_sync.WORKSPACE
            )
            ahead = so.strip() if rc == 0 else "0"
            if ahead and ahead != "0":
                logger.info("sync_puller 跳过本轮 (本地有 %s 个未推送 commit)", ahead)
                return {"skipped": f"本地有 {ahead} 个未推送 commit, 本轮跳过"}

            to_checkout: list[str] = []
            conflicts: list[dict] = []
            changed = 0

            for code, rman in remote.items():
                lman = local.get(code)
                winner, why = _resolve_winner(code, lman, rman)
                if winner == "remote":
                    # 把远端版本的该资产目录整个拉下来
                    paths = [
                        p for p in git_sync.list_files_at_ref(ref)
                        if _asset_code_from_manifest_path(p) == code
                    ]
                    to_checkout.extend(paths)
                    changed += 1
                    if lman is not None:
                        conflicts.append(
                            {
                                "code": code,
                                "reason": why,
                                "local_version": lman.get("version"),
                                "remote_version": rman.get("version"),
                            }
                        )
                elif winner == "same" and lman is None:
                    to_checkout.extend(
                        p for p in git_sync.list_files_at_ref(ref)
                        if _asset_code_from_manifest_path(p) == code
                    )
                    changed += 1

            # 远端删掉的资产 → 本地也删 (下架的极端情况: 直接删文件)
            remote_paths = set(git_sync.list_files_at_ref(ref))
            local_paths = set(git_sync.list_files_at_ref("HEAD"))
            removed = [
                p for p in (local_paths - remote_paths)
                if p.startswith("assets/")
            ]

            if to_checkout:
                git_sync.checkout_from_ref(ref, sorted(set(to_checkout)))
            if removed:
                rc2, so2, se2 = git_sync._run_git(
                    ["rm", "-r", "--quiet", "--", *removed], cwd=git_sync.WORKSPACE
                )
                if rc2 != 0:
                    logger.warning("删除远端已移除的文件失败: %s", se2.strip()[:200])

        # ---- 回灌 DB 镜像 + 写冲突审计 ----
        async with AsyncSessionLocal() as session:
            added, updated = await apply_index_to_db(session)
            for c in conflicts:
                session.add(
                    AssetAudit(
                        asset_id=None,
                        code=c["code"],
                        action="conflict_resolved",
                        comment=c["reason"],
                        detail=c,
                    )
                )
            if conflicts:
                await session.commit()

        _puller.has_remote_updates = changed > 0
        _puller.conflict_count = len(conflicts)
        _puller.last_sync_at = datetime.utcnow()
        _puller.last_error = ""
        logger.info(
            "sync_puller 完成: changed=%s conflicts=%s added=%s updated=%s",
            changed, len(conflicts), added, updated,
        )
        return {
            "changed": changed,
            "conflicts": conflicts,
            "added": added,
            "updated": updated,
            "removed": len(removed),
        }
    except Exception as e:  # noqa: BLE001 — 同步异常不能影响推送链路
        _puller.last_error = f"{type(e).__name__}: {e}"
        logger.warning("sync_puller 异常 (已忽略): %s", e)
        return {"error": _puller.last_error}
    finally:
        _puller._running = False


def _local_manifests() -> dict[str, dict]:
    """本地 HEAD 上的所有资产 manifest, 按 code 索引."""
    out: dict[str, dict] = {}
    for p in git_sync.list_files_at_ref("HEAD"):
        if not p.endswith(MANIFEST_SUFFIX):
            continue
        code = _asset_code_from_manifest_path(p)
        if not code:
            continue
        m = _parse_manifest(git_sync.read_text_at_ref(p, "HEAD"))
        if m:
            out[code] = m
    return out


async def _loop(interval: int) -> None:
    logger.info("sync_puller 启动, 间隔 %ss", interval)
    while True:
        try:
            await sync_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("sync_puller 循环异常: %s", e)
        await asyncio.sleep(max(5, interval))


_puller_task: asyncio.Task | None = None


async def start_puller(interval: int = 30) -> None:
    """启动后台拉取同步器 (应用启动时调一次)."""
    global _puller_task
    if _puller_task is None or _puller_task.done():
        _puller_task = asyncio.create_task(_loop(interval))


async def stop_puller() -> None:
    global _puller_task
    if _puller_task is not None and not _puller_task.done():
        _puller_task.cancel()
        try:
            await _puller_task
        except asyncio.CancelledError:
            pass
    _puller_task = None
