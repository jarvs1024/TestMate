"""扩展通知的**统一构造** —— 别在 8 个端点里各拼一遍.

为什么要有这个模块 (2026-10-25 整改):
    加一个字段 (比如「适用项目」project) 要改 8 处 notify_extensions 调用,
    漏一处就**静默丢信息** —— mcp_config 当年就丢过一次, 表现成"连接器没有配置",
    极难排查.

现在字段拼装只有这一处, 端点只负责"发哪个事件、说什么".
"""
from __future__ import annotations

from typing import Any

from app.core.dingtalk import notify_extensions


def _get(asset: Any, key: str, default: str = "") -> str:
    """从 Asset 对象 / manifest 字典 里取字段 (两者字段名一致)."""
    if isinstance(asset, dict):
        value = asset.get(key, default)
    else:
        value = getattr(asset, key, default)
    return str(value or default)


async def notify_asset(
    event: str,
    asset: Any,
    *,
    actor: str,
    detail: str = "",
    link: str = "",
    author: str | None = None,
    title_override: str = "",
    summary: str | None = None,
    release_notes: str = "",
) -> bool:
    """按资产统一发一条扩展通知.

    asset 可以是:
      · Asset 对象 (DB 里的镜像)
      · manifest / out 字典 (落盘阶段资产还没提交到 DB)

    ⚠️ 通知时机 (2026-11-05): **扩展群公告** (publish/update/unpublish/reject/delete)
      不在这里即时发 —— 这些通知声称"资产已经变了", 端点把 notify 配置挂到
      AssetJob.payload["notify"], worker 在 **git 同步成功之后**才调这个函数
      (见 asset_jobs._send_deferred_notify). push 失败时扩展群收不到假公告.
      例外: **审核群任务提醒** (review / unpublish_request) 要审的东西在数据库里,
      不用等 git, 仍在端点即时发.

    ⚠️ detail 是**这次操作发生了什么** (如"新资产已上架") —— 不是资产的简介.
       把简介塞进来, 群里读起来像重复了一遍卡片副标题, 看不出发生了什么.
    ⚠️ title_override 只改标题文案, 事件 key 不变 (开关映射靠 key).
    ⚠️ summary / release_notes (2026-10-30 加) —— 通知正文里"这玩意儿是干嘛的"那一行:
       传了 summary (资产的简介) 或 release_notes (这次改了啥) 就**取代** detail.
    ⚠️ summary 传 None = 从资产里取; 显式传 "" = **不用简介**, 退回 detail
       (驳回/下架说的是"发生了什么", 把简介塞进去就跑题了).
    """
    return await notify_extensions(
        event,
        name=_get(asset, "name"),
        version=_get(asset, "version"),
        actor=actor,
        detail=detail,
        link=link,
        code=_get(asset, "code"),
        kind=_get(asset, "kind"),
        category=_get(asset, "category"),
        project=_get(asset, "project"),
        author=author if author is not None else _get(asset, "author"),
        title_override=title_override,
        summary=summary if summary is not None else _get(asset, "summary"),
        release_notes=release_notes,
    )
