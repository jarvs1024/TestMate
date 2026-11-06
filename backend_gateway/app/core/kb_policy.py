"""知识库写权限 —— REST 与 MCP 共用这一处判定。"""
from __future__ import annotations

from app.models.user import User, UserRole


def can_write_kb(user: User) -> bool:
    """admin / tester 可以写知识库; viewer 只读。"""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role in (UserRole.admin.value, UserRole.tester.value)
