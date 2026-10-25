"""Pydantic 校验模型。"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.models.user import UserRole


class LoginRequest(BaseModel):
    """登录请求.

    ⚠️ password 可空 —— **管理员建过**的账号可以不设密码 (免密登录),
       设了密码的账号 / 管理员账号则必须给.
    """

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    created_at: datetime


class UserManageOut(UserOut):
    """账号管理列表用的行 —— 多两个字段: 能不能用 / 要不要密码."""

    is_active: bool = True
    password_required: bool = False


class UserCreate(BaseModel):
    """管理员建号.

    ⚠️ password 可以不给: 不给 = 免密账号 (填用户名就进).
       给了 = 必须输密码.
    ⚠️ username 填短名时后端自动补 @twsc.com.cn (普通用户);
       管理员账号名不含 @, 原样存.
    """

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=128)
    role: UserRole = UserRole.tester
    # 显式要求密码登录 —— 跟"有没有给密码"配套用 (给了密码就自动 True)
    password_required: bool = False


class UserUpdate(BaseModel):
    """改账号: 停用/启用、改角色、重置密码、切换要不要密码.

    ⚠️ 字段全是可选的 —— 只改传了的那些.
    ⚠️ password 给了 = 重置成这个密码 (并自动变成"必须密码").
    """

    is_active: bool | None = None
    role: UserRole | None = None
    password: str | None = Field(default=None, max_length=128)
    password_required: bool | None = None
