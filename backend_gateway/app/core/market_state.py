"""资产生命周期状态机 —— 五态迁移的**唯一真源**.

为什么要有这张表 (2026-10-25 整改):
    以前每个端点各自 if 判断"现在是什么状态、能不能这么做", 于是每条路径
    都漏了一条边界:
      · 作者对自己的**待审核**资产调 /publish → 绕过审核直接上架
      · 审核人对**已上架**资产调 review/reject → 在架资产被下线
      · 审核人对**待下架**资产调 review/approve → 作者的下架申请被静默吞掉

现在所有状态判断都走这里 —— **纯逻辑, 可穷举, 可单测**:
    端点只负责"我要做这个动作", 由 assert_transition 决定允不允许.

五态:
    pending            已提交, 等管理员审核 (不对普通用户可见)
    published          在架
    rejected           审核未通过 (发布者改了可重新提交)
    unpublished        审核通过后又下架 (文件保留, 在用用户仍可见)
    unpublish_pending  申请下架, 等管理员确认 (确认后资产被**彻底删除**)
"""
from __future__ import annotations

PENDING = "pending"
PUBLISHED = "published"
REJECTED = "rejected"
UNPUBLISHED = "unpublished"
UNPUBLISH_PENDING = "unpublish_pending"

ALL_STATES: tuple[str, ...] = (
    PENDING, PUBLISHED, REJECTED, UNPUBLISHED, UNPUBLISH_PENDING,
)

# 在架 = 用户能在市场里正常看到 (unpublish_pending 也算在架:
# 管理员确认前它还在被用, 不能从列表里消失, 只是标个待审徽标)
ON_SHELF_STATES: tuple[str, ...] = (PUBLISHED, UNPUBLISH_PENDING)

# 动作 → 允许的起始状态 → 目标状态
#   (动作名, 允许的起始状态, 目标状态, 谁可以做)
#   谁来做: "author" = 作者或管理员; "reviewer" = 管理员或审核人;
#           "admin" = 仅管理员
_ACTIONS: dict[str, tuple[tuple[str, ...], str, str]] = {
    # ---- 上架审核 ----
    "submit": ((REJECTED,), PENDING, "author"),          # 驳回后改了重新提交
    "approve": ((PENDING,), PUBLISHED, "reviewer"),       # 审核通过 → 上架
    "reject": ((PENDING,), REJECTED, "reviewer"),         # 审核驳回
    # ---- 下架 (申请制) ----
    "unpublish_request": ((PUBLISHED,), UNPUBLISH_PENDING, "author"),
    "unpublish_cancel": ((UNPUBLISH_PENDING,), PUBLISHED, "author"),
    "unpublish_approve": ((UNPUBLISH_PENDING,), "", "admin"),   # 通过 = 彻底删除
    # ---- 重新上架 ----
    "publish": ((UNPUBLISHED,), PUBLISHED, "author"),
}

# 动作 → 用户说给用户听的话 (出错时直接回前端)
_ACTION_LABEL: dict[str, str] = {
    "submit": "重新提交审核",
    "approve": "通过审核",
    "reject": "驳回审核",
    "unpublish_request": "申请下架",
    "unpublish_cancel": "撤销下架申请",
    "unpublish_approve": "通过下架申请",
    "publish": "重新上架",
}

# 审计动作 → 审计列表里显示的话 (「这条记录干了啥」).
#
# ⚠️ 跟上面的 _ACTION_LABEL **刻意分开** —— 那张表是状态机报错时用的
#    ("不能通过下架申请"), 这张表是描述一次操作 ("通过下架申请, 资产已删除").
#    同一个动作两句话, 不矛盾.
#
# ⚠️ 这张表是**唯一真源** (2026-10-25): 前端原来自己维护了一份, 结果
#    · 漏了 create / update / approve / reject / submit → 列表里显示原始 action id;
#    · 多了一个 unpublish_reject —— 状态机里**没有**这个迁移, 永远是死选项;
#    · 同一个动作 (unpublish_approve) 在状态机 / 前端 / git commit 文本里
#      三套说法, 迟早漂移.
#    现在由审计接口直接把 action_label 吐给前端, 前端不再自己翻译.
AUDIT_ACTION_LABEL: dict[str, str] = {
    "create": "新建资产",
    "update": "发布新版本",
    "publish": "重新上架",
    "unpublish_request": "申请下架",
    "unpublish_cancel": "撤销下架申请",
    "unpublish_approve": "通过下架申请 (资产已删除)",
    "approve": "审核通过",
    "reject": "审核驳回",
    "submit": "提交审核",
    "delete": "管理员删除",
    "conflict_resolved": "同步冲突已解决",
}


def audit_action_label(action: str) -> str:
    """审计动作 → 中文 (没登记过的动作原样返回, 宁可露 id 也不显示空白)."""
    return AUDIT_ACTION_LABEL.get(action or "", action or "")

# 当前状态 → 允许对它做的动作 (给"为什么不能做"用)
_STATE_HINT: dict[str, str] = {
    PENDING: "该资产正在等审核, 审核通过前不能再上架",
    PUBLISHED: "该资产已在架, 要下架请走「申请下架」",
    REJECTED: "该资产已被驳回, 改完请点「重新提交审核」",
    UNPUBLISHED: "该资产已下架, 可以点「重新上架」",
    UNPUBLISH_PENDING: "该资产已申请下架, 等管理员确认 (可撤销申请)",
}


class TransitionError(ValueError):
    """状态迁移不被允许 —— 消息直接给用户看."""


def allowed_actions(state: str) -> tuple[str, ...]:
    """当前状态允许做哪些动作."""
    return tuple(a for a, (froms, _to, _who) in _ACTIONS.items() if state in froms)


def assert_transition(
    action: str,
    state: str,
    *,
    is_author: bool = False,
    is_reviewer: bool = False,
    is_admin: bool = False,
) -> str:
    """断言「这个动作在这个状态下、这个人身份下」是允许的.

    返回目标状态 ("" = 该动作不改变状态, 比如彻底删除).

    Raises:
        TransitionError: 不允许 —— 消息说明"现在是什么状态、该怎么做".
    """
    spec = _ACTIONS.get(action)
    if spec is None:
        raise TransitionError(f"未知动作: {action}")
    froms, to, who = spec

    # 1) 状态对不对
    if state not in froms:
        hint = _STATE_HINT.get(state, f"当前状态是 {state}")
        raise TransitionError(
            f"不能{_ACTION_LABEL.get(action, action)}: {hint}"
        )

    # 2) 身份够不够
    if who == "admin":
        ok = is_admin
    elif who == "reviewer":
        ok = is_reviewer or is_admin
    else:  # author
        ok = is_author or is_admin
    if not ok:
        raise TransitionError(f"没有权限{_ACTION_LABEL.get(action, action)}")

    return to
