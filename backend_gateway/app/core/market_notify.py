"""市场通知的**统一构造** —— 别在 8 个端点里各拼一遍.

为什么要有这个模块 (2026-10-25 整改):
    加一个字段 (比如「适用项目」project) 要改 8 处 notify_market 调用,
    漏一处就**静默丢信息** —— mcp_config 当年就丢过一次, 表现成"连接器没有配置",
    极难排查.

现在字段拼装只有这一处, 端点只负责"发哪个事件、说什么".
"""
from __future__ import annotations

from typing import Any

from app.core.dingtalk import notify_market


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
    summary: str = "",
    release_notes: str = "",
) -> bool:
    """按资产统一发一条市场通知.

    asset 可以是:
      · Asset 对象 (DB 里的镜像)
      · manifest / out 字典 (落盘阶段资产还没提交到 DB)

    ⚠️ 通知在 **enqueue() 之后**立即发 —— push 失败时市场群照样收到"上架"公告.
      这是已知取舍 (通知比 GitLab 推送更重要: 团队要知道"有人在做什么"),
      真要严格一致得等 job 终态再发, 代价是延迟变长.

    ⚠️ detail 是**这次操作发生了什么** (如"新资产已上架") —— 不是资产的简介.
       把简介塞进来, 群里读起来像重复了一遍卡片副标题, 看不出发生了什么.
    ⚠️ title_override 只改标题文案, 事件 key 不变 (开关映射靠 key).
    ⚠️ summary / release_notes (2026-10-30 加) —— 通知正文里"这玩意儿是干嘛的"那一行:
       传了 summary (资产的简介) 或 release_notes (这次改了啥) 就**取代** detail.
    """
    return await notify_market(
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
        summary=summary or _get(asset, "summary"),
        release_notes=release_notes,
    )
