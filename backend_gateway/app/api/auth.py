from typing import Optional
"""登录 / 当前用户 / 账号管理。"""
import asyncio
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.identity import local_part, lookup_candidates, to_email
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.db.session import get_session
from app.models.asset import AssetAudit
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


# ===== 登录失败限流 =====
#
# ⚠️ 为什么需要: 登录接口**没有**任何失败次数限制, 而密码是 bcrypt(cost=12) ——
#    慢得让在线爆破不划算, 但离线爆破/自动化撞库照样能做, 而且登录端点还能
#    用来**枚举账号** (account_not_found / account_disabled / password_required
#    三个 code 各自说明账号存不存在).
#    限流是成本最低、见效最快的一层.
#
# ⚠️ 计数是**进程内内存**的 (多副本部署时各自计数, 不共享) ——
#    这对本系统的规模够用 (单副本), 别把它当成防分布式攻击的东西.
#    阈值故意放宽 (默认 10 次 / 15 分钟): 既挡得住撞库, 又不会
#    让"手抖连输错几次"的同事被锁在门外.
_LOGIN_FAIL_LIMIT = max(1, int(os.environ.get("AUTH_LOGIN_FAIL_LIMIT", "10")))
_LOGIN_FAIL_WINDOW = max(60, int(os.environ.get("AUTH_LOGIN_FAIL_WINDOW_SECONDS", "900")))
_login_failures: dict[str, list[float]] = {}
_login_fail_lock = asyncio.Lock()


def _login_fail_key(username: str, client_ip: str) -> str:
    """限流键: 用户名 + 来源 IP.

    ⚠️ 带上 IP: 否则一个人狂输错密码能把**别人**的账号也锁上 (登录名撞了就行).
    """
    return f"{(username or '').strip().lower()}|{client_ip or '-'}"


async def _login_fail_count(key: str) -> int:
    """当前窗口内的失败次数 (顺手把过期记录清掉)."""
    now = time.monotonic()
    async with _login_fail_lock:
        hits = [t for t in _login_failures.get(key, []) if now - t < _LOGIN_FAIL_WINDOW]
        if hits:
            _login_failures[key] = hits
        else:
            _login_failures.pop(key, None)
        return len(hits)


async def _record_login_failure(key: str) -> int:
    async with _login_fail_lock:
        now = time.monotonic()
        hits = [t for t in _login_failures.get(key, []) if now - t < _LOGIN_FAIL_WINDOW]
        hits.append(now)
        _login_failures[key] = hits
        return len(hits)


async def _clear_login_failures(key: str) -> None:
    async with _login_fail_lock:
        _login_failures.pop(key, None)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效或过期")
    # ⚠️ sub / tv 都要**防一手**: token 虽然是自己签的, 但解析失败不能变成 500.
    #    (以前 int(payload.get("sub",0)) 遇到非数字直接 ValueError → 500)
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效")
    try:
        token_version = int(payload.get("tv", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    # ⚠️ 停用要**立刻**生效 —— token 有 7 天有效期, 不查这一列的话,
    #    管理员停用了账号, 对方手上的 token 照样能用一整周.
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已停用")
    # ⚠️ 改密码 / 改角色 / 停用 → token_version 自增 → **旧 token 立即作废**.
    #    (老 token 没有 tv 字段 → 当 0, 与存量用户的 0 相等 → 升级不用重新登录)
    if token_version != (user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态已失效 (账号信息或密码已变更), 请重新登录",
        )
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
    try:
        token_version = int(payload.get("tv", 0))
    except (TypeError, ValueError):
        return _anonymous_user()
    user = await session.get(User, user_id)
    if user and not user.is_active:
        # 停用的账号 → 退化成匿名 (它连"自己的身份"都不该还有)
        return _anonymous_user()
    if user and token_version != (user.token_version or 0):
        # 改密码/改角色/停用之后手上的旧 token → 同样退化成匿名
        return _anonymous_user()
    return user or _anonymous_user()


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
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
    # ⚠️ 限流: 连续失败太多次就先挡住 (默认 10 次 / 15 分钟).
    #    挡在**查库之前** —— 账号不存在也照样计数, 否则枚举账号反而没有代价.
    client_ip = request.client.host if request.client else "-"
    fail_key = _login_fail_key(req.username, client_ip)
    fails = await _login_fail_count(fail_key)
    if fails >= _LOGIN_FAIL_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录失败次数过多, 请 {_LOGIN_FAIL_WINDOW // 60} 分钟后再试",
        )

    user = await _find_user(session, req.username)

    if user is None:
        # 账号不存在 → 不给自动开通, 让管理员先建号
        await _record_login_failure(fail_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "account_not_found", "message": "账号不存在, 请联系管理员开通"},
        )

    if not user.is_active:
        await _record_login_failure(fail_key)
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
            await _record_login_failure(fail_key)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    elif req.password:
        # 免密账号: 用户还是输了密码 —— 这个账号**压根没有密码**, 输什么都对不上.
        # 直接放行 (而不是报"密码错误"), 否则用户会以为自己记错了密码.
        pass

    # 登录成功 → 清掉失败计数 (别让一次误输把账号一直挂着"快锁了")
    await _clear_login_failures(fail_key)

    # ⚠️ token 里带 tv (token_version) —— 之后改密码/改角色/停用会让旧 token 立即作废
    token, expires_in = create_access_token(
        user.id,
        {
            "role": user.role.value,
            "username": user.username,
            "tv": user.token_version or 0,
        },
    )
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


@router.get("/config")
async def auth_config() -> dict:
    """登录/建号页面需要的**公开**配置 (不用登录).

    ⚠️ 只有"填表单要用"的东西才能放这儿 —— 任何**权限/凭据**相关的一律不行.
       现在就一项: 公司邮箱后缀 (后端 AUTH_EMAIL_DOMAIN 是**可配的**,
       前端以前把 '@twsc.com.cn' 写死在两处 → 生产改了域名, 页面提示还是旧的,
       用户按提示填了错的域名, 登录时后端补的却是另一个域).
    """
    return {"email_domain": settings.AUTH_EMAIL_DOMAIN}


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


def _username_spellings(username: str) -> set[str]:
    """同一个"人"在库里的**所有可能写法** —— 短名 + 公司邮箱形式.

    管理员账号名不含 @ ('zhangsan'), 普通用户的库内名是邮箱 ('zhangsan@twsc.com.cn'),
    而**老库里可能还存着短名的普通用户** (迁移 0020 之前的遗留行).
    这几种写法在登录时是**同一个候选集** (见 identity.lookup_candidates),
    所以撞名检查必须按候选集来查, 不能按"对方是什么角色"来查.
    """
    out: set[str] = set()
    s = (username or "").strip().lower()
    if s:
        out.add(s)
    lp = local_part(username)
    if lp:
        out.add(lp)
        email = to_email(lp)
        if email:
            out.add(email)
    return out


async def _check_name_collision(session: AsyncSession, username: str, role: UserRole) -> None:
    """建号时挡住"撞名" —— 同一个人的不同写法只能留一个.

    ⚠️ 为什么按**写法候选集**查, 而不是"对方是不是管理员":
       登录用的是 lookup_candidates —— 'zhangsan' 会依次尝试
       'zhangsan' → 'zhangsan@twsc.com.cn' → 'zhangsan'. 只要库里存在**任意一种写法**
       的另一行, 短名登录就会命中错的那个. 以前只查了"对方是 admin"这一种组合, 于是:

         · 库里有个短名的普通用户 'zhangsan' (迁移前遗留) →
           再建 admin 'zhangsan' → **不报撞名** → 老用户用短名登录直接进管理员账号;
         · 反过来, 库里有个短名的普通用户 'zhangsan' →
           再建用户 'zhangsan@twsc.com.cn' → **不报撞名** → 一人两号,
           而**新账号会继承老账号名下的资产所有权** (作者名匹配是容错的, 两种写法都算).

    所以这里查全部写法, 且**不区分角色**.
    """
    spellings = _username_spellings(username)
    if not spellings:
        return
    rows = (
        await session.execute(select(User).where(User.username.in_(spellings)))
    ).scalars().all()

    for u in rows:
        if u.username == username:
            # 完全同名 → 是"重名"而不是"撞写法", 说清楚区别
            role_hint = "" if u.role == role else f" (库里那个是 {u.role.value} 角色)"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"账号已存在: {username}{role_hint} —— "
                    f"如果那就是本人, 直接用那个账号即可, 不必再建"
                ),
            )
        other_role = "管理员账号" if u.role == UserRole.admin else "用户账号"
        raise HTTPException(
            status_code=422,
            detail=(
                f"账号名 '{username}' 与已有的{other_role} '{u.username}' 撞名 —— "
                f"同一个人的不同写法只能留一个, 否则用短名登录会命中错的那个账号, "
                f"还可能出现一人两号 (新账号会继承老账号名下的资产). "
                f"如果 '{u.username}' 就是本人, 直接用那个账号即可, 不必再建."
            ),
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


async def _audit_user_action(
    session: AsyncSession,
    *,
    action: str,
    target: User,
    actor: User,
    detail: dict | None = None,
    comment: str = "",
) -> None:
    """账号操作留痕 —— 谁在什么时候建了/改了哪个账号, 改了什么.

    ⚠️ 为什么复用 AssetAudit 而不是另开一张表:
       资产侧本来就有"谁动了什么"的审计流水, 账号侧**一个字的痕迹都没有** ——
       出了问题 (资产被谁改了 / 号被谁降级) 根本查不出来.
       复用同一张表 = 零迁移成本, 而且管理员在「操作记录」抽屉里**顺手就能看到**
       (那个抽屉本来就是 admin only).

    ⚠️ code 用 'user:<用户名>' 命名空间 —— 和资产的 code 不会混.
    """
    session.add(
        AssetAudit(
            asset_id=None,
            code=f"user:{target.username}",
            action=action,
            actor_id=actor.id if actor else None,
            actor_name=actor.username if actor else "",
            comment=comment,
            detail={"username": target.username, **(detail or {})},
        )
    )


@router.post("/users", response_model=UserManageOut, status_code=201)
async def create_user(
    req: UserCreate,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role(UserRole.admin)),
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
    await _audit_user_action(
        session,
        action="user.create",
        target=user,
        actor=admin,
        detail={
            "role": req.role.value,
            # ⚠️ **不记密码本身** —— 只记"有没有设密码".
            #    审计表是给人看的, 不该变成第二个密码泄露源.
            "password_set": bool(password),
        },
        comment=f"创建账号 {username} ({req.role.value})",
    )
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

    ⚠️ 改密码 / 改角色 / 停用 → **旧 token 立即作废** (token_version 自增).
       以前只靠"查库看 is_active"挡停用, 改密码完全挡不住 ——
       管理员给员工重置了密码, 员工手上那个泄露出去的旧 token 还能用满 7 天.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    changes: dict = {}

    # ① 停用 / 启用
    if req.is_active is not None and req.is_active != user.is_active:
        if user.id == admin.id and not req.is_active:
            raise HTTPException(status_code=400, detail="不能停用当前登录的账号")
        if not req.is_active and user.role == UserRole.admin:
            await _guard_last_admin(session, user.id)
        changes["is_active"] = req.is_active
        user.is_active = req.is_active

    # ② 重置密码 —— 给了新密码就换掉, 同时这个账号变成"必须密码"
    #    (不变式: password_required=True ⟹ 这个账号有可用的密码)
    new_password = _check_password(req.password)
    if new_password:
        user.password_hash = hash_password(new_password)
        user.password_required = True
        changes["password_reset"] = True

    # ③ 角色变更
    if req.role is not None and req.role != user.role:
        if user.id == admin.id:
            raise HTTPException(status_code=400, detail="不能修改当前登录账号自己的角色")
        if user.role == UserRole.admin:
            await _guard_last_admin(session, user.id)
        if req.role == UserRole.admin and not user.password_required:
            # 升成管理员却没密码 → 这个号登进去也没法用管理功能, 不许升
            raise HTTPException(status_code=422, detail="升级为管理员必须设置密码")
        changes["role"] = req.role.value
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
            changes["password_required"] = False

    # ⚠️ 凡是"改动了登录凭证/权限"的动作 → token_version 自增 → 旧 token 全废.
    #    (改密码 / 改角色 / 停用 / 改成免密 —— 任何一个都会让"旧凭证"失去意义)
    if changes:
        user.token_version = (user.token_version or 0) + 1
        changes["token_version"] = user.token_version

    if changes:
        await _audit_user_action(
            session,
            action="user.update",
            target=user,
            actor=admin,
            detail=changes,
            comment=(
                f"修改账号 {user.username}: " + ", ".join(
                    k for k in changes if k != "token_version"
                )
            ),
        )

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
