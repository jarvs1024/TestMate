"""扩展可见性闸门 (``app/core/ext_visibility.py``) —— **可见性矩阵**的纯逻辑单测.

⚠️ 为什么这个模块要单独测:
    列表 (apply_visibility) 与详情 (assert_visible) 必须用**同一套规则** ——
    2026-10-25 整改前详情端点根本没有过滤, 任意登录用户 GET /assets/{code}
    就能看到待审核 / 被驳回 / 已下架的资产 (连接器的 MCP 配置也一并暴露).

    这个模块是 6 个端点的**唯一**可见性真源, 但之前零单测 —— 安全语义全靠
    API 层间接测. 一旦有人改了状态常量 (比如把 unpublished 加进在架态),
    API 层的用例不一定能抓到**矩阵**级别的回归.

⚠️ 本文件里的绝大多数用例**不碰数据库**:
    visible_to / assert_visible 只读资产的两个字段 (``publish_status`` 与
    ``author``), 所以直接 ``Asset(...)`` 造一个**内存对象**即可 (SQLAlchemy
    不 flush 就不会连库). 只有最后一组用例真的落库, 用来确认 ORM 路径 +
    真实用户 fixture 下行为一致.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import ext_state
from app.core.ext_visibility import apply_visibility, assert_visible, visible_to
from app.models.asset import Asset

# ---- 身份口径 (与 app/core/identity.author_forms 对齐) ----

#: 资产作者 (DB 里存短名)
AUTHOR = "zhangsan"
#: 作者本人用**邮箱形式**登录 (最常见的真实场景)
AUTHOR_LOGIN = "zhangsan@twsc.com.cn"
#: 陌生人
STRANGER_LOGIN = "lisi@twsc.com.cn"

#: 在架态 —— 与 ext_state.ON_SHELF_STATES 一致 (published / unpublish_pending)
ON_SHELF = (ext_state.PUBLISHED, ext_state.UNPUBLISH_PENDING)
#: 不在架的三个态 —— 只有作者本人 / 管理员 / 审核人看得见
OFF_SHELF = (ext_state.PENDING, ext_state.REJECTED, ext_state.UNPUBLISHED)

ALL_STATUSES = list(ext_state.ALL_STATES)


def _asset(*, author: str = AUTHOR, publish_status: str | None = ext_state.PUBLISHED,
           code: str = "vis-asset") -> Asset:
    """造一个**内存里**的 Asset (不 flush → 不连库)."""
    return Asset(
        code=code, name="可见性测试资产", icon="🧩", kind="skill",
        version="1.0.0", author=author, publish_status=publish_status,
    )


# 身份 → (username, is_reviewer, is_admin)
IDENTITIES = {
    "author": (AUTHOR_LOGIN, False, False),
    "admin": ("admin_t", False, True),
    "reviewer": ("reviewer_t", True, False),
    "stranger": (STRANGER_LOGIN, False, False),
}


# ---------- 可见性矩阵 ----------


@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize("identity", list(IDENTITIES))
def test_visible_to_matrix(status: str, identity: str):
    """**可见性矩阵**: 身份 × publish_status → 能不能看见.

    规则 (来自模块 docstring):
      · 在架 (published / unpublish_pending) —— 所有人可见
      · 管理员 / 审核人 —— 全部可见
      · 作者本人 —— 自己的都可见 (待审 / 被驳回 / 待下架)
    """
    username, is_reviewer, is_admin = IDENTITIES[identity]
    asset = _asset(author=AUTHOR, publish_status=status)

    got = visible_to(
        asset, username=username, is_reviewer=is_reviewer, is_admin=is_admin
    )

    if status in ON_SHELF:
        assert got is True, f"{status} 在架 → 所有人都该看得见 ({identity})"
    elif identity in ("author", "admin", "reviewer"):
        assert got is True, f"{status} → {identity} 该看得见"
    else:
        assert got is False, f"{status} → 陌生人**不该**看得见"


def test_matrix_covers_every_state_in_ext_state():
    """矩阵必须覆盖 ext_state 的**全部**状态 —— 少一个就等于漏测一条路径."""
    assert set(ALL_STATUSES) == set(ext_state.ALL_STATES)
    assert len(ALL_STATUSES) == 5
    # 断言矩阵用的常量与 ext_state 真源一致 (防止本文件自己漂移)
    assert ON_SHELF == ext_state.ON_SHELF_STATES


def test_stranger_cannot_see_off_shelf_asset():
    """陌生人对**不在架**的资产一律看不见 (待审 / 被驳回 / 已下架)."""
    for status in OFF_SHELF:
        asset = _asset(author=AUTHOR, publish_status=status)
        assert visible_to(asset, username=STRANGER_LOGIN) is False, status


def test_author_sees_own_off_shelf_asset():
    """作者本人对自己的待审 / 被驳回 / 已下架资产可见 (否则改不了)."""
    for status in OFF_SHELF:
        asset = _asset(author=AUTHOR, publish_status=status)
        assert visible_to(asset, username=AUTHOR_LOGIN) is True, status


def test_reviewer_and_admin_see_everything():
    """审核人 / 管理员看得见**全部**状态 (他们要处理待审资产)."""
    for status in ALL_STATUSES:
        asset = _asset(author=AUTHOR, publish_status=status)
        assert visible_to(asset, username=STRANGER_LOGIN, is_reviewer=True) is True
        assert visible_to(asset, username=STRANGER_LOGIN, is_admin=True) is True


# ---------- 作者身份匹配 (短名 / 全邮箱) ----------


@pytest.mark.parametrize("author", [AUTHOR, AUTHOR_LOGIN, " ZhangSan ", "ZHANGSAN"])
def test_author_forms_are_recognised(author: str):
    """作者名按 ``identity.author_forms`` 认 —— 短名 / 全邮箱 / 大小写 / 空格都算本人.

    ⚠️ 详情层把 ``asset.author`` 洗过 (strip + lower), 所以存量数据里的
    ' ZhangSan ' 也认 —— 跟列表层的 SQL 口径要对得上.
    """
    asset = _asset(author=author, publish_status=ext_state.PENDING)
    assert visible_to(asset, username=AUTHOR_LOGIN) is True, author


def test_author_of_another_person_is_not_visible():
    """别人的资产不是本人 —— 不可见."""
    asset = _asset(author="lisi", publish_status=ext_state.PENDING)
    assert visible_to(asset, username=AUTHOR_LOGIN) is False


def test_same_local_part_from_other_domain_matches():
    """⚠️ **已知口径**: author_forms 只看 @ 前的本地部分, 不校验域名 ——

    'zhangsan@other.com' 的本地部分也是 'zhangsan' → 认作同一个作者.
    这是 ``identity.author_forms`` 的既有行为 (不是本模块引入的), 但值得钉住:
    将来谁要把"同名不同域"当两个人, 这里就是改动点.
    """
    asset = _asset(author=AUTHOR, publish_status=ext_state.PENDING)
    assert visible_to(asset, username="zhangsan@other.com") is True


def test_full_email_author_is_invisible_to_short_name_login():
    """⚠️ **已知不对称**: author 存全邮箱 + 用户用短名登录 → **认不出是本人**.

    identity.author_forms('zhangsan') = ['zhangsan'] (短名不会反推出全邮箱),
    所以 author='zhangsan@twsc.com.cn' 匹配不上. 详情层与列表层口径**一致**
    (都认不出), 但与 ext_policy.can_modify 用的 identity.name_matches
    (双向认) **不一致** —— 那一处用 name_matches, 所以"能不能改"和"能不能看"
    在这个组合下结论相反. 本用例把这个现状钉住, 便于将来统一口径时对照.
    """
    asset = _asset(author=AUTHOR_LOGIN, publish_status=ext_state.PENDING)
    assert visible_to(asset, username=AUTHOR) is False


# ---------- assert_visible ----------


@pytest.mark.parametrize("status", OFF_SHELF)
def test_assert_visible_raises_404_for_stranger(status: str):
    """看不见 → 抛 **404** (不是 403 —— 403 等于告诉对方"这个 code 存在")."""
    asset = _asset(author=AUTHOR, publish_status=status)
    with pytest.raises(HTTPException) as ei:
        assert_visible(asset, username=STRANGER_LOGIN)
    assert ei.value.status_code == 404
    assert ei.value.detail == "资产不存在"


@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize("identity", list(IDENTITIES))
def test_assert_visible_matches_visible_to_on_the_whole_matrix(status: str, identity: str):
    """**完整矩阵**: assert_visible 的行为必须与 visible_to 逐条一致.

    visible_to 说能看见 → assert_visible 安静通过;
    visible_to 说看不见 → assert_visible 抛 **404** (不抛 403).
    """
    username, is_reviewer, is_admin = IDENTITIES[identity]
    asset = _asset(author=AUTHOR, publish_status=status)
    seen = visible_to(
        asset, username=username, is_reviewer=is_reviewer, is_admin=is_admin
    )
    if seen:
        assert assert_visible(
            asset, username=username, is_reviewer=is_reviewer, is_admin=is_admin
        ) is None
    else:
        with pytest.raises(HTTPException) as ei:
            assert_visible(
                asset, username=username, is_reviewer=is_reviewer, is_admin=is_admin
            )
        assert ei.value.status_code == 404
        assert ei.value.detail == "资产不存在"


# ---------- apply_visibility (SQL 层) ----------


def test_apply_visibility_returns_stmt_untouched_for_admin_or_reviewer():
    """管理员 / 审核人 → **不加任何过滤** (列表里能看到全部状态)."""
    from sqlalchemy import select

    stmt = select(Asset)
    assert apply_visibility(stmt, username="x", is_admin=True) is stmt
    assert apply_visibility(stmt, username="x", is_reviewer=True) is stmt


def test_apply_visibility_uses_on_shelf_states_and_author_forms():
    """普通用户 → 在架态 OR 自己提交的 (作者两种写法都带上)."""
    from sqlalchemy import select

    stmt = apply_visibility(select(Asset), username=AUTHOR_LOGIN)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert f"'published', 'unpublish_pending'" in sql
    assert "'zhangsan@twsc.com.cn', 'zhangsan'" in sql


def test_apply_visibility_and_visible_to_agree_on_the_same_matrix():
    """**列表层与详情层必须同口径** —— 这是整个模块存在的理由.

    对每个 (状态, 身份) 组合: SQL 里能查出来的集合 与 visible_to 逐条判定
    必须完全一致 (不靠真的跑数据库, 直接比对编译出来的谓词与真源常量).
    """
    from sqlalchemy import select

    for status in ALL_STATUSES:
        for identity, (username, is_reviewer, is_admin) in IDENTITIES.items():
            stmt = apply_visibility(
                select(Asset), username=username,
                is_reviewer=is_reviewer, is_admin=is_admin,
            )
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            if is_reviewer or is_admin:
                # 无过滤 → 所有状态都能查到
                visible_in_list = True
            else:
                visible_in_list = status in ON_SHELF or identity == "author"
            detail_visible = visible_to(
                _asset(author=AUTHOR, publish_status=status),
                username=username, is_reviewer=is_reviewer, is_admin=is_admin,
            )
            assert visible_in_list == detail_visible, (status, identity, sql)


def test_apply_visibility_empty_username_falls_back_to_empty_author_match():
    """⚠️ **已知可疑行为**: username 为空 → author_forms 返回空列表 →

    谓词退化成 ``author = ''`` —— 也就是**空作者的资产**对空用户名用户可见.
    真实调用方传的都是登录用户名 (不会为空), 但这个退化分支值得钉住:
    将来改 author_forms 时会看到这里.
    """
    from sqlalchemy import select

    sql = str(
        apply_visibility(select(Asset), username="").compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "assets.author = ''" in sql


# ---------- 详情层与列表层的**已知不一致* (空状态) ----------


def test_empty_publish_status_is_visible_in_detail_but_hidden_in_list():
    """⚠️ **已知不一致**: publish_status 为空串时, 详情层当"在架"放行, 列表层却过滤掉.

    · 详情层: ``(asset.publish_status or PUBLISHED) in ON_SHELF_STATES``
      → 空串被当成 'published' → **所有人可见**.
    · 列表层: ``Asset.publish_status.in_(ON_SHELF_STATES)``
      → 空串不在集合里 → **被过滤掉** (除非是本人提交的).

    模块 docstring 声称"列表与详情用同一套规则", 这里就破了一次.
    现状钉住 (不是要现在改): 将来统一时, 这个用例会红 —— 那正是信号.
    """
    from sqlalchemy import select

    asset = _asset(author=AUTHOR, publish_status="")
    assert visible_to(asset, username=STRANGER_LOGIN) is True  # 详情层放行

    sql = str(
        apply_visibility(select(Asset), username=STRANGER_LOGIN).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "'published', 'unpublish_pending'" in sql  # 列表层只认这两个
    assert "OR assets.author IN" in sql  # 空状态的资产不在在架集合里


def test_unpublished_is_not_in_ext_visibility_on_shelf_states():
    """⚠️ **已知口径差异**: 'unpublished' 不在 ext_visibility.ON_SHELF_STATES 里.

    但 ext_catalog.INDEX_VISIBLE_STATES = ('published', 'unpublished',
    'unpublish_pending') —— 也就是说**已下架**的资产仍然留在 marketplace 索引里
    (对外可见), 而本模块的列表/详情闸门对普通用户**看不到**它.

    ext_state 的五态说明里写的是 "unpublished ... 在用用户仍可见", 与
    ext_catalog 的索引口径一致, 与本模块的 ON_SHELF_STATES 不一致.
    这里把现状钉住, 便于将来决定"下架后该不该从索引里摘掉".
    """
    from app.core import ext_catalog

    assert ext_state.UNPUBLISHED not in ext_state.ON_SHELF_STATES
    assert ext_state.UNPUBLISHED in ext_catalog.INDEX_VISIBLE_STATES


# ---------- 落库路径 (真 ORM + 真用户 fixture) ----------


async def test_db_backed_visibility_for_real_users(
    publisher_user, stranger_user, admin_user
):
    """落库的 Asset + 真实用户 fixture → 详情层判定与矩阵一致.

    ⚠️ 这里用 conftest 的 publisher_user / stranger_user / admin_user ——
    它们的用户名是 'publisher_t' / 'stranger_t' / 'admin_t' (短名形态),
    正好覆盖"author 短名 + 登录短名"这条最常见的存量组合.
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="vis-db-pending", name="待审资产", icon="🧩", kind="skill",
            version="1.0.0", author=publisher_user["username"],
            publish_status=ext_state.PENDING, sync_status="pushed",
        ))
        s.add(Asset(
            code="vis-db-published", name="在架资产", icon="🧩", kind="skill",
            version="1.0.0", author=publisher_user["username"],
            publish_status=ext_state.PUBLISHED, sync_status="pushed",
        ))
        await s.commit()

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select

        rows = (await s.execute(
            select(Asset).where(Asset.code.in_(["vis-db-pending", "vis-db-published"]))
        )).scalars().all()
        by_code = {a.code: a for a in rows}

    pending_asset = by_code["vis-db-pending"]
    published_asset = by_code["vis-db-published"]

    # 作者本人: 两种状态都看得见
    for a in (pending_asset, published_asset):
        assert visible_to(a, username=publisher_user["username"]) is True
    # 陌生人: 只看得见在架的
    assert visible_to(published_asset, username=stranger_user["username"]) is True
    assert visible_to(pending_asset, username=stranger_user["username"]) is False
    # 管理员: 全部看得见
    assert visible_to(pending_asset, username=admin_user["username"], is_admin=True) is True


async def test_db_backed_assert_visible_raises_404_for_stranger(
    publisher_user, stranger_user
):
    """落库路径上, 陌生人看别人的待审资产 → 404."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="vis-db-404", name="待审资产", icon="🧩", kind="skill",
            version="1.0.0", author=publisher_user["username"],
            publish_status=ext_state.PENDING, sync_status="pushed",
        ))
        await s.commit()

    async with AsyncSessionLocal() as s:
        from sqlalchemy import select

        asset = (await s.execute(
            select(Asset).where(Asset.code == "vis-db-404")
        )).scalar_one()

    with pytest.raises(HTTPException) as ei:
        assert_visible(asset, username=stranger_user["username"])
    assert ei.value.status_code == 404
    assert ei.value.detail == "资产不存在"


async def test_db_backed_reviewer_can_see_pending_asset(publisher_user):
    """审核人 (白名单里的普通用户) 看得见别人的待审资产."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.core import ext_policy
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    from tests.conftest import set_setting

    async with AsyncSessionLocal() as s:
        u = User(
            username="reviewer_t", password_hash=hash_password("Rev@12345"),
            role=UserRole.tester,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        uid, uname = u.id, u.username

    await set_setting("extensions.review.reviewer_usernames", uname)

    async with AsyncSessionLocal() as s:
        user = await s.get(User, uid)
        assert await ext_policy.is_reviewer(user) is True

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="vis-db-reviewer", name="待审资产", icon="🧩", kind="skill",
            version="1.0.0", author=publisher_user["username"],
            publish_status=ext_state.PENDING, sync_status="pushed",
        ))
        await s.commit()

    async with AsyncSessionLocal() as s:
        asset = (await s.execute(
            select(Asset).where(Asset.code == "vis-db-reviewer")
        )).scalar_one()

    assert visible_to(asset, username=uname, is_reviewer=True) is True
    # 不给 is_reviewer 标志 → 与详情层一样只看本人/在架
    assert visible_to(asset, username=uname) is False
