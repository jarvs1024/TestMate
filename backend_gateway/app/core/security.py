"""JWT + 密码 hash。

直接用 bcrypt 原生 API, 不走 passlib(passlib 1.7.4 不兼容 bcrypt 4.x,
会打 `error reading bcrypt version` 警告). 算法用 bcrypt (cost=12).
"""
from datetime import datetime, timedelta
from typing import Any

import bcrypt
from jose import jwt, JWTError

from app.core.config import settings

# bcrypt salt cost = 12 (~250ms/hash, 单台足够, 想要更高改这里)
_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """返回 bcrypt hash (含 salt, $2b$ 开头, passlib 也能 verify)."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """verify 一个 bcrypt hash. 老 hash (passlib 生成的 $2b$...) 也能 verify."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> tuple[str, int]:
    """返回 (token, expires_in_seconds)。"""
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire}
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, settings.JWT_EXPIRE_MINUTES * 60


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


# ===== 软件库下载票据 =====

#: 下载票据的类型标记 —— 跟普通登录 token 区分开.
#: ⚠️ 必须区分: 登录 token 是**长期**凭证, 一旦塞进 URL 就会进 nginx access_log
#:    和浏览器历史. 下载票是**短时**的 (默认 10 分钟), 窗口小、可撤销、绑定具体版本.
DOWNLOAD_TICKET_TYPE = "sw-dl"

#: 下载票默认有效期 (秒)
DOWNLOAD_TICKET_TTL = 600


def create_download_ticket(
    *, user_id: int, code: str, version: str, ttl_seconds: int = DOWNLOAD_TICKET_TTL
) -> tuple[str, int]:
    """签发一张**短时下载票** —— 返回 (ticket, expires_in_seconds).

    票据里带 uid / code / ver —— 校验时除了验签, 还要确认:
      · 用户还在 (没被删)
      · 用户没被停用 (is_active)
      · 该版本的软件仍然存在且是 ready
    """
    expire = datetime.utcnow() + timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "typ": DOWNLOAD_TICKET_TYPE,
        "uid": int(user_id),
        "code": code,
        "ver": version,
        "exp": expire,
    }
    ticket = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return ticket, ttl_seconds


def decode_download_ticket(ticket: str) -> dict[str, Any] | None:
    """校验下载票 —— 签名有效 + 未过期 + 类型对得上, 才返回 payload; 否则 None."""
    if not ticket:
        return None
    try:
        payload = jwt.decode(ticket, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != DOWNLOAD_TICKET_TYPE:
        return None
    return payload
