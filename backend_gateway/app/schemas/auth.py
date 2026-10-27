"""Pydantic 校验模型。"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.models.user import UserRole

# bcrypt 只取前 **72 字节** (不是 72 个字符) —— 超出的部分被**静默丢弃**,
# 不报错也不提示. 后果: 两个只有尾部不同的口令会互相登录, 而管理员以为
# 自己设的是 128 位强口令. 所以在入参层按**字节数**拦住.
_BCRYPT_MAX_BYTES = 72


def _check_bcrypt_len(v: str | None) -> str | None:
    if v and len(v.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        raise ValueError(
            f"密码过长: bcrypt 只支持前 {_BCRYPT_MAX_BYTES} 字节 "
            f"(当前 {len(v.encode('utf-8'))} 字节)"
        )
    return v


class LoginRequest(BaseModel):
    """登录请求.

    ⚠️ password 可空 —— **管理员建过**的账号可以不设密码 (免密登录),
       设了密码的账号 / 管理员账号则必须给.
    ⚠️ password 原样比对, 不 strip —— 跟建号时的处理保持一致.
    """

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=128)

    _pwd_len = field_validator("password")(_check_bcrypt_len)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AccountHintOut(BaseModel):
    """账号提示 —— 登录页用来决定"要不要显示密码框".

    ⚠️ 这是**公开**端点 (不用登录) —— 它只回答跟登录表单直接相关的问题:
       这个账号存不存在、要不要密码. 不含任何凭据信息.
    """

    # ok = 账号存在且可用; missing = 没开通; disabled = 已停用; unknown = 输入还不成形
    account: str = "unknown"
    # 这个账号登录要不要密码 (admin 一律 True; 普通账号看建号时有没有给密码)
    needs_password: bool = False
    role: UserRole | None = None
    # 库里这个账号的**规范用户名** (普通用户是邮箱, 管理员是账号名) —— 前端拿它校正提示
    username: str | None = None


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
    ⚠️ password **原样存, 不 strip** —— 登录也是原样比对, 两边必须一致.
    """

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=128)
    role: UserRole = UserRole.tester
    # 显式要求密码登录 —— 跟"有没有给密码"配套用 (给了密码就自动 True)
    password_required: bool = False

    _pwd_len = field_validator("password")(_check_bcrypt_len)

    @field_validator("role")
    @classmethod
    def _reject_anonymous(cls, v: UserRole) -> UserRole:
        """anonymous 是**占位角色**(不入库, 只用于公共只读看板的匿名访问),
        不该被建成一个真实账号 —— 那种账号既进不了管理功能, 又是数据库里的僵尸行.
        """
        if v == UserRole.anonymous:
            raise ValueError("anonymous 是内部占位角色, 不能用来建号")
        return v


class UserUpdate(BaseModel):
    """改账号: 停用/启用、改角色、重置密码、切换要不要密码.

    ⚠️ 字段全是可选的 —— 只改传了的那些.
    ⚠️ password 给了 = 重置成这个密码 (并自动变成"必须密码").
    """

    is_active: bool | None = None
    role: UserRole | None = None
    password: str | None = Field(default=None, max_length=128)
    password_required: bool | None = None

    _pwd_len = field_validator("password")(_check_bcrypt_len)

    @field_validator("role")
    @classmethod
    def _reject_anonymous(cls, v: UserRole | None) -> UserRole | None:
        if v is not None and v == UserRole.anonymous:
            raise ValueError("anonymous 是内部占位角色, 不能赋给真实账号")
        return v
