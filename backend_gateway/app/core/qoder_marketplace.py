"""生成 Qoder 原生 marketplace 清单.

Qoder 的市场清单格式 (实测自 ~/.qoder-cn/plugins/marketplaces/qoder-plugins/marketplace.json):
    {
      "name": "<marketplace 名>",       ← 决定 Qoder 缓存目录名
      "owner": {"name": "..."},
      "plugins": [
        {
          "name": "...", "description": "...", "version": "...",
          "author": {"name": "..."},
          "source": {"source": "archive", "url": "<zip 直链>", "sha256": "..."}
        }
      ]
    }

用户在 Qoder 里把本服务加为市场源后:
  - Qoder 自带安装器负责下载 / 校验 sha256 / 解压
  - 装到 ~/.qoder-cn/plugins/cache/<name>/<plugin>/<version>/
  - autoUpdate=true 时 Qoder 自己定期检查更新

只收录 kind=plugin 且 publish_status=published 的资产 —— 连接器与技能不走这条通道.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from app.core import git_sync, pkg
from app.db.session import AsyncSessionLocal
from app.models.asset import Asset

logger = logging.getLogger(__name__)


async def _package_bytes(asset: Asset) -> tuple[bytes, str] | None:
    """取该资产的可下载包 + 其 sha256.

    优先用上传时存的原始包 (字节稳定); 老资产没存包则即时确定性打包.
    """
    base = git_sync.resolve_in_workspace(asset.git_path) or (git_sync.WORKSPACE / "__invalid__")
    pkg_dir = base / "package"
    if pkg_dir.is_dir():
        # 优先匹配当前版本的包, 否则取目录里第一个
        cands = sorted(p for p in pkg_dir.iterdir() if p.is_file())
        exact = [p for p in cands if p.name.startswith(f"{asset.version}.")]
        chosen = exact[0] if exact else (cands[0] if cands else None)
        if chosen is not None:
            data = chosen.read_bytes()
            return data, pkg.sha256_bytes(data)
    root = pkg.files_root(base)
    if root.is_dir():
        data = pkg.build_zip(root)
        return data, pkg.sha256_bytes(data)
    return None


async def build_marketplace(base_url: str, name: str = "testmate",
                            owner: str = "SSD 测试组") -> dict[str, Any]:
    """生成 marketplace.json 内容."""
    base = (base_url or "").rstrip("/")
    plugins: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Asset).where(
                    Asset.kind == "plugin",
                    Asset.publish_status == "published",
                )
            )
        ).scalars().all()

    for a in rows:
        got = await _package_bytes(a)
        if got is None:
            logger.warning("marketplace 跳过 (无可下载包): %s", a.code)
            continue
        _data, sha = got
        plugins.append(
            {
                "name": a.code,
                "description": a.summary or a.name,
                "version": a.version,
                "author": {"name": a.author or "unknown"},
                "source": {
                    "source": "archive",
                    "url": f"{base}/api/v1/assets/{a.code}/versions/{a.version}/download",
                    "sha256": sha,
                },
            }
        )

    plugins.sort(key=lambda p: p["name"])
    return {"name": name, "owner": {"name": owner}, "plugins": plugins}


def render(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2)
