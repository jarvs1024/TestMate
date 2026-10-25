from typing import Optional
"""登录 / 当前用户。"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.identity import lookup_candidates, to_email
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.db.session import get_session
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, TokenResponse, UserCreate, UserOut

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
    return user or _anonymous_user()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    """登录.

    2026-10-25 重构 —— **普通用户免密, 管理员要密码**:

    | 输入 | 结果 |
    |---|---|
    | 'zhangsan' / 'zhangsan@twsc.com.cn' | 免密登录; 账号不存在则**首次登录自动开通** (角色 tester) |
    | 'admin' (或其他管理员账号) | **必须密码** —— 缺密码时返回 `password_required` |

    ⚠️ 密码可空 (LoginRequest.password 默认 ""), 这是"一键免密"的落点.
    ⚠️ 管理员缺密码时返回 401 + detail.code='password_required', 前端据此
       展开密码框 —— 别改成笼统的"用户名或密码错误", 那样用户会一直以为自己
       密码错了, 而实际是"这个账号压根不需要密码".
    """
    user = await _find_user(session, req.username)

    if user is None:
        # 账号不存在 → 首次登录自动开通 (公司邮箱即身份)
        user = await _provision_user(session, req.username, req.password)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if user.role == UserRole.admin:
        # 管理员必须密码
        if not req.password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "password_required", "message": "管理员账号需要密码"},
            )
        if not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    else:
        # 普通用户: 密码**可空** (免密登录).
        # 填了就必须对 —— 用户明确输了密码, 却不校验, 会让他以为自己密码是错的
        # (或者反过来, 以为密码生效了). 首次开通时这个密码会被存成账号密码.
        if req.password and not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

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


async def _provision_user(
    session: AsyncSession, raw_username: str, password: str = ""
) -> User | None:
    """首次登录自动开通账号 (公司邮箱即身份).

    只有**合法的公司邮箱**才能开通 —— 输入 'admin' 或 'zhangsan@别的域' 一律
    返回 None (走"用户名或密码错误"), 免得垃圾输入在库里堆出一堆账号.

    ⚠️ 密码: 用户输了就存成账号密码 (他主动设的), 没输就存一个随机的 ——
       两种情况下这个账号都能**免密**登录 (普通用户默认免密), 但只有前一种
       还能用密码进. 存随机的而不是空串: 免得以后有人给 users 表加个
       "空密码也算对"的逻辑就把它放行了.
    """
    if not settings.AUTH_AUTO_PROVISION:
        return None
    email = to_email(raw_username)
    if not email:
        return None

    user = User(
        username=email,
        password_hash=hash_password(password) if password else hash_password(secrets.token_urlsafe(32)),
        role=UserRole.tester,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # 并发首次登录: 另一个请求刚建好, 直接用它
        await session.rollback()
        result = await session.execute(select(User).where(User.username == email))
        return result.scalar_one_or_none()
    await session.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    req: UserCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    """仅 admin 可创建用户.

    ⚠️ 2026-10-25: 用户名按**公司邮箱**存 (填 'zhangsan' 自动补成
       'zhangsan@twsc.com.cn'), 跟登录口径一致 —— 否则会出现"登录要邮箱、
       建号填的是短名"这种对不上的情况.

    ⚠️ 密码可以不给 (普通用户免密登录用不上). 给不了就存一个随机的,
       这个账号只能免密进, 管理员也登不进去 —— 符合"普通用户没有密码"的设定.
    """
    username = to_email(req.username) or req.username.strip().lower()
    password_hash = (
        hash_password(req.password) if req.password else hash_password(secrets.token_urlsafe(32))
    )
    user = User(
        username=username,
        password_hash=password_hash,
        role=req.role,
    )
    session.add(user)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=f"创建失败:{e}")
    await session.refresh(user)
    return user
