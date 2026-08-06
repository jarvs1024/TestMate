"""User + RBAC。"""
from datetime import datetime
from sqlalchemy import String, DateTime, Enum, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.db.session import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    tester = "tester"
    viewer = "viewer"
    # 匿名访问占位角色 (不入库, 仅用于 /code-review-v2 等公共只读看板, 由 get_optional_user 返回).
    anonymous = "anonymous"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.viewer)
    api_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
