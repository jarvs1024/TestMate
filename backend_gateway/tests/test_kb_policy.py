"""知识库写权限的唯一判定入口。"""
from app.core.kb_policy import can_write_kb
from app.models.user import User, UserRole


def _user(role: UserRole) -> User:
    return User(username=f"kb-policy-{role.value}", password_hash="unused", role=role)


def test_admin_and_tester_can_write_kb():
    assert can_write_kb(_user(UserRole.admin)) is True
    assert can_write_kb(_user(UserRole.tester)) is True


def test_viewer_cannot_write_kb():
    assert can_write_kb(_user(UserRole.viewer)) is False
