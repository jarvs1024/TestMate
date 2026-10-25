"""User + RBAC。"""
from datetime import datetime
from sqlalchemy import String, DateTime, Enum, BigInteger, Boolean, Integer
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
    # 账号是否可用 —— 管理员停用后不能登录 (比删号安全: 资产归属还在).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 这个账号登录是否必须输密码.
    #   · admin 角色永远是 True (跟 role 分开存, 是为了让"管理员"这条规则
    #     只有一个来源 —— 登录时直接看 role, 不依赖这一列).
    #   · 普通账号由管理员建号时定: 给了密码 → True; 没给密码 → False (免密).
    # ⚠️ 免密账号的 password_hash 仍存一个随机哈希 (不是空串) —— 免得哪天
    #    有人加个"空密码也算对"的判断就把它放行了.
    password_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 登录态版本号 —— **改密码 / 改角色 / 停用账号时自增**, 用来作废旧 token.
    #
    # ⚠️ 为什么需要它: JWT 一签发就是 7 天有效. 管理员重置了某人的密码 (或把
    #    角色降了 / 停用了账号), 但那个人手上的旧 token **照样能用到过期** ——
    #    "改了密码等于没改". 光靠"查库看 is_active"只能挡住停用, 挡不住改密码.
    #
    # ⚠️ 老 token (签发时还没有这一版号的) 没有 tv 字段 → 当成 0 处理,
    #    而存量用户的 token_version 也是 0 → 升级后不用全员重新登录.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
