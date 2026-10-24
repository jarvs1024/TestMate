"""资产生命周期状态机 —— 五态迁移的唯一真源.

⚠️ 2026-10-25 整改: 以前每个端点各自 if 判断状态, 于是作者能对**待审核**的
   资产调 /publish 绕过审核、审核人能驳回**在架**资产 —— 现在统一由这张表裁决.
"""
from __future__ import annotations

import pytest

from app.core import market_state as ms


def test_pending_cannot_be_published_by_author():
    """作者对**待审核**的资产自助上架 = 绕过审核 —— 必须拒绝."""
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("publish", ms.PENDING, is_author=True)


def test_publish_only_from_unpublished():
    assert ms.assert_transition("publish", ms.UNPUBLISHED, is_author=True) == ms.PUBLISHED
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("publish", ms.PUBLISHED, is_author=True)


def test_review_only_accepts_pending():
    """审核只接受 pending → published / rejected."""
    assert ms.assert_transition("approve", ms.PENDING, is_reviewer=True) == ms.PUBLISHED
    assert ms.assert_transition("reject", ms.PENDING, is_reviewer=True) == ms.REJECTED
    # 已上架的资产不能被"驳回" —— 那等于让审核人把在架资产下线
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("reject", ms.PUBLISHED, is_reviewer=True)


def test_unpublish_request_only_from_published():
    assert ms.assert_transition(
        "unpublish_request", ms.PUBLISHED, is_author=True) == ms.UNPUBLISH_PENDING
    # 待下架的资产不能再"申请下架" (两条路打架)
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("unpublish_request", ms.UNPUBLISH_PENDING, is_author=True)


def test_cancel_unpublish_back_to_published():
    assert ms.assert_transition(
        "unpublish_cancel", ms.UNPUBLISH_PENDING, is_author=True) == ms.PUBLISHED


def test_submit_only_from_rejected():
    assert ms.assert_transition("submit", ms.REJECTED, is_author=True) == ms.PENDING
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("submit", ms.PUBLISHED, is_author=True)


def test_reviewer_cannot_unpublish_approve():
    """通过下架申请 = **彻底删除别人的资产** —— 只有管理员能做."""
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("unpublish_approve", ms.UNPUBLISH_PENDING, is_reviewer=True)
    # 管理员可以
    assert ms.assert_transition(
        "unpublish_approve", ms.UNPUBLISH_PENDING, is_admin=True) == ""


def test_author_cannot_review():
    """作者不能审自己的资产 (哪怕他是审核人以外的角色)."""
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("approve", ms.PENDING, is_author=True)


def test_admin_can_do_everything():
    assert ms.assert_transition("approve", ms.PENDING, is_admin=True) == ms.PUBLISHED
    assert ms.assert_transition("publish", ms.UNPUBLISHED, is_admin=True) == ms.PUBLISHED
    assert ms.assert_transition(
        "unpublish_approve", ms.UNPUBLISH_PENDING, is_admin=True) == ""


def test_error_message_explains_current_state():
    """报错要说清"现在是什么状态、该怎么做" —— 用户才看得懂."""
    with pytest.raises(ms.TransitionError) as ei:
        ms.assert_transition("publish", ms.PENDING, is_author=True)
    assert "审核" in str(ei.value)


def test_unknown_action_is_rejected():
    with pytest.raises(ms.TransitionError):
        ms.assert_transition("whatever", ms.PUBLISHED, is_author=True)


def test_allowed_actions_are_consistent_with_table():
    """每个状态的可用动作都能真的走通 (表与实现不自相矛盾)."""
    for state in ms.ALL_STATES:
        for action in ms.allowed_actions(state):
            target = ms.assert_transition(action, state, is_admin=True)
            assert target in ms.ALL_STATES or target == ""
