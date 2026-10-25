"""Pydantic 校验模型。"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.models.user import UserRole


class LoginRequest(BaseModel):
    """登录请求.

    ⚠️ password 可空 —— 普通用户是**免密登录** (公司邮箱即身份),
       管理员才必须给密码. 前端据此展开密码框.
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


class UserCreate(BaseModel):
    """管理员建号.

    ⚠️ password 可空: 普通用户免密登录, 用不上密码.
       username 建议填邮箱 (填短名后端会自动补 @twsc.com.cn).
    """

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=128)
    role: UserRole = UserRole.viewer
