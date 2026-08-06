from typing import Optional
"""登录 / 当前用户。"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
    result = await session.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token, expires_in = create_access_token(user.id, {"role": user.role.value, "username": user.username})
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    req: UserCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    """仅 admin 可创建用户。"""
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
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
