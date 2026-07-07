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
