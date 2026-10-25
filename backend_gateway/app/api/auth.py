from typing import Optional
"""登录 / 当前用户 / 账号管理。"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.identity import local_part, lookup_candidates, to_email
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.db.session import get_session
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserManageOut,
    UserOut,
    UserUpdate,
)

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效或过期")
    user_id = int(payload.get("sub", 0))
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    # ⚠️ 停用要**立刻**生效 —— token 有 7 天有效期, 不查这一列的话,
    #    管理员停用了账号, 对方手上的 token 照样能用一整周.
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已停用")
    return user


def require_role(*roles: UserRole):
    async def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user
    return dep


def _anonymous_user() -> User:
    """匿名访问占位用户 (不入库, 内存构造).

    用于 /code-review-v2 等公共只读看板: 没 token / token 无效 时返回这个,
    后端 review-agent/pr-agent 路由用 get_optional_user 兼容 anonymous + 真实 user.
    anonymous 角色严禁走任何写操作 (review-agent 全部是 GET, 安全边界天然 OK).
    """
    from datetime import datetime
    now = datetime.utcnow()
    return User(
        id=0,
        username="anonymous",
        password_hash="",
        role=UserRole.anonymous,
        api_token=None,
        is_active=True,
        password_required=False,
        created_at=now,
        updated_at=now,
    )


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """跟 get_current_user 一样, 但没 token / token 无效 / 用户不存在 时返回 anonymous 用户, 不抛 401.

    用于公共只读看板接口: 登录用户走真实身份, 匿名用户走 anonymous 占位, 后端统一处理.
    """
    if not token:
        return _anonymous_user()
    payload = decode_token(token)
    if not payload:
        return _anonymous_user()
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        return _anonymous_user()
    user = await session.get(User, user_id)
    if user and not user.is_active:
        # 停用的账号 → 退化成匿名 (它连"自己的身份"都不该还有)
        return _anonymous_user()
    return user or _anonymous_user()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    """登录 —— **账号必须管理员先建过** (2026-10-25 账号管理重构).

    | 账号 | 登录要求 |
    |---|---|
    | 管理员建的普通账号 (建号时没给密码) | 免密: 只填用户名就能进 |
    | 管理员建的普通账号 (建号时给了密码) | 必须密码 |
    | 管理员账号 | 必须密码 |
    | 库里没有 / 已被停用 | 401 |

    ⚠️ 为什么不再"首次登录自动开通": 任何人知道同事邮箱就能进他的号 ——
       账号必须**管理员先建**, 登录才是真的鉴权. 免密只保留在"管理员认可这个号"
       的前提下 —— 免的是密码, 不是身份.

    ⚠️ 管理员缺密码时返回 401 + detail.code='password_required', 前端据此
       展开密码框 —— 别改成笼统的"用户名或密码错误", 那样用户会一直以为自己
       密码错了, 而实际是"这个账号压根不需要密码".
    """
    user = await _find_user(session, req.username)

    if user is None:
        # 账号不存在 → 不给自动开通, 让管理员先建号
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "account_not_found", "message": "账号不存在, 请联系管理员开通"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "account_disabled", "message": "账号已停用, 请联系管理员"},
        )

    # 需要密码的两种情况: 管理员账号 / 建号时设了密码的账号
    need_password = user.role == UserRole.admin or user.password_required
    if need_password:
        if not req.password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "password_required",
                    "message": "管理员账号需要密码" if user.role == UserRole.admin else "该账号需要密码",
                },
            )
        if not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    elif req.password:
        # 免密账号: 用户还是输了密码 —— 这个账号**压根没有密码**, 输什么都对不上.
        # 直接放行 (而不是报"密码错误"), 否则用户会以为自己记错了密码.
        pass

    token, expires_in = create_access_token(user.id, {"role": user.role.value, "username": user.username})
    return TokenResponse(access_token=token, expires_in=expires_in)


async def _find_user(session: AsyncSession, raw_username: str) -> User | None:
    """按输入找用户 (见 identity.lookup_candidates 的候选顺序)."""
    for candidate in lookup_candidates(raw_username):
        result = await session.execute(select(User).where(User.username == candidate))
        user = result.scalar_one_or_none()
        if user:
            return user
    return None


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


# ===== 账号管理 (仅 admin) =====
# 用户名口径: 普通用户 = 公司邮箱 (管理员建号时填前缀或全邮箱都行, 后端统一
# 补成 'zhangsan@twsc.com.cn'); 管理员 = 不含 @ 的账号名.


def _normalize_username(raw: str, role: UserRole) -> str:
    """建号时的用户名归一.

    · admin 角色 → 账号名原样 (小写, 去空格), **不补邮箱后缀** ——
      管理员是账号名不是邮箱, 补上域名就变成另一个东西了.
    · 其他角色  → 必须是公司邮箱形式 (填前缀自动补后缀).
    """
    s = (raw or "").strip().lower()
    if not s:
        raise HTTPException(status_code=422, detail="用户名不能为空")
    if role == UserRole.admin:
        if "@" in s:
            raise HTTPException(status_code=422, detail="管理员账号名不能带 @, 请用纯账号名")
        return s
    email = to_email(s)
    if not email:
        raise HTTPException(
            status_code=422,
            detail=f"普通用户必须是公司邮箱 (如 zhangsan{settings.AUTH_EMAIL_DOMAIN})",
        )
    return email


async def _check_name_collision(session: AsyncSession, username: str, role: UserRole) -> None:
    """建号时挡住"撞名": 管理员账号名 与 用户邮箱前缀 撞了.

    管理员账号名是不含 @ 的短名 ('zhangsan'), 普通用户的邮箱前缀也是短名
    ('zhangsan') —— 两者撞名时, 用户用短名登录会**先命中管理员账号**
    (精确匹配优先), 结果被要求输管理员的密码, 用户完全懵.

    两个方向都要挡:
      · 建管理员 'zhangsan' 时 → 库里不能已有 'zhangsan@twsc.com.cn' 这个用户
      · 建用户 'zhangsan@…' 时 → 库里不能已有叫 'zhangsan' 的管理员
    """
    if role == UserRole.admin:
        clash = f"{local_part(username)}{settings.AUTH_EMAIL_DOMAIN}"
        exists = (
            await session.execute(
                select(User).where(User.username == clash, User.role != UserRole.admin)
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(
                status_code=422,
                detail=f"账号名 '{username}' 与用户 '{clash}' 撞名 —— 换个账号名, 否则该用户用短名登录会撞到这个管理员",
            )
    else:
        lp = local_part(username)
        exists = (
            await session.execute(
                select(User).where(User.username == lp, User.role == UserRole.admin)
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(
                status_code=422,
                detail=f"邮箱前缀 '{lp}' 与管理员账号 '{lp}' 撞名 —— 换个邮箱前缀, 否则该用户用短名登录会撞到那个管理员",
            )


def _check_password(raw: str | None) -> str:
    """校验并返回管理员设置的密码 (原样, 不 strip).

    ⚠️ **一律不 strip**: 口令是原样比对的, 建号时 strip 掉首尾空格、登录时
    不 strip, 就会出现"管理员给的密码永远登不上"的不对称.
    首尾空格本来就该是密码的一部分 —— 用户输入什么就存什么.

    ⚠️ 全空白要显式拒绝: 否则 "   " 会被当成"没给密码" → 静默生成一个**免密**
    账号, 管理员以为自己设了密码, 实际这个号谁都能进.
    """
    pw = raw or ""
    if pw and not pw.strip():
        raise HTTPException(status_code=422, detail="密码不能只有空白字符")
    return pw


@router.get("/users", response_model=list[UserManageOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    """账号列表 —— 设置页「用户管理」区块的数据源."""
    result = await session.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


@router.post("/users", response_model=UserManageOut, status_code=201)
async def create_user(
    req: UserCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    """管理员建号.

    ⚠️ 密码给不给由管理员定:
       · 给了 → password_required=True, 登录必须输密码;
       · 没给 → 免密账号 (只填用户名就能进), password_hash 存随机串
         (不是空串 —— 免得以后有人加个"空密码也算对"的判断就把它放行了).
    """
    username = _normalize_username(req.username, req.role)
    await _check_name_collision(session, username, req.role)

    password = _check_password(req.password)
    if req.password_required and not password:
        raise HTTPException(status_code=422, detail="要求密码登录的账号必须设置密码")
    if req.role == UserRole.admin and not password:
        # 管理员账号必须密码, 否则建出来也登不进去
        raise HTTPException(status_code=422, detail="管理员账号必须设置密码")

    user = User(
        username=username,
        password_hash=hash_password(password) if password else hash_password(secrets.token_urlsafe(32)),
        role=req.role,
        is_active=True,
        password_required=bool(password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"账号已存在: {username}")
    await session.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserManageOut)
async def update_user(
    user_id: int,
    req: UserUpdate,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role(UserRole.admin)),
):
    """改账号 —— 停用/启用、改角色、重置密码.

    ⚠️ 三条护栏 (防止管理员把自己锁在门外):
       ① 不能停用自己;
       ② 不能降级自己 (把自己从 admin 降成 tester);
       ③ 不能停用/降级**最后一个**管理员 —— 否则这个系统再没人能管账号了.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    # ① 停用 / 启用
    if req.is_active is not None and req.is_active != user.is_active:
        if user.id == admin.id and not req.is_active:
            raise HTTPException(status_code=400, detail="不能停用当前登录的账号")
        if not req.is_active and user.role == UserRole.admin:
            await _guard_last_admin(session, user.id)
        user.is_active = req.is_active

    # ② 重置密码 —— 给了新密码就换掉, 同时这个账号变成"必须密码"
    #    (不变式: password_required=True ⟹ 这个账号有可用的密码)
    new_password = _check_password(req.password)
    if new_password:
        user.password_hash = hash_password(new_password)
        user.password_required = True

    # ③ 角色变更
    if req.role is not None and req.role != user.role:
        if user.id == admin.id:
            raise HTTPException(status_code=400, detail="不能修改当前登录账号自己的角色")
        if user.role == UserRole.admin:
            await _guard_last_admin(session, user.id)
        if req.role == UserRole.admin and not user.password_required:
            # 升成管理员却没密码 → 这个号登进去也没法用管理功能, 不许升
            raise HTTPException(status_code=422, detail="升级为管理员必须设置密码")
        user.role = req.role
        if req.role == UserRole.admin:
            user.password_required = True

    # ④ 密码要求开关 (没给新密码时才处理 —— 给了新密码的走 ② 已经定了)
    if req.password_required is not None and not new_password:
        if req.password_required:
            if not user.password_required:
                raise HTTPException(status_code=422, detail="要求密码登录的账号必须设置密码")
            user.password_required = True
        else:
            # 改成免密 → 密码作废 (存随机串, 免得"空密码也算对")
            # ⚠️ admin 角色**不能**改免密 —— 登录时 need_password 对 admin 恒为真,
            #    免密 admin 等于一个谁也进不去的账号 (自己把自己锁死).
            if user.role == UserRole.admin:
                raise HTTPException(status_code=400, detail="管理员账号不能改成免密登录")
            user.password_hash = hash_password(secrets.token_urlsafe(32))
            user.password_required = False

    await session.commit()
    await session.refresh(user)
    return user


async def _guard_last_admin(session: AsyncSession, exclude_user_id: int) -> None:
    """系统里只剩一个管理员时, 不许把他停用/降级."""
    result = await session.execute(
        select(User).where(User.role == UserRole.admin, User.is_active.is_(True))
    )
    admins = [u for u in result.scalars().all() if u.id != exclude_user_id]
    if not admins:
        raise HTTPException(status_code=400, detail="系统至少要保留一个可用的管理员账号")
