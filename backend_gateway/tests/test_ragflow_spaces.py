"""RAGFlow 用户空间: 加密、默认唯一、解析与旧配置迁移."""
import pytest

from app.core import ragflow_spaces as rs
from app.db.session import AsyncSessionLocal
from app.models.ragflow_space import RagflowSpace
from app.models.system_setting import SystemSetting


async def _add_space(name="A", key="ragflow-old-key-123456", default=False):
    return await rs.create_space(name, key, is_default=default)


async def test_create_encrypts_key_and_resolves():
    sp = await _add_space("空间A", "ragflow-aaaa-1111", default=True)
    assert sp.id.startswith("sp_")
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, sp.id)
        assert row.api_key_cipher.startswith("v1:")
        assert "ragflow-aaaa-1111" not in row.api_key_cipher
    _base, key, resolved = await rs.credential_for(sp.id)
    assert resolved.id == sp.id
    assert key == "ragflow-aaaa-1111"


async def test_default_is_unique():
    a = await _add_space("A", default=True)
    b = await _add_space("B", default=True)
    async with AsyncSessionLocal() as s:
        assert (await s.get(RagflowSpace, a.id)).is_default is False
        assert (await s.get(RagflowSpace, b.id)).is_default is True
    assert (await rs.default_space()).id == b.id


async def test_resolve_unknown_lists_available():
    await _add_space("空间A", default=True)
    with pytest.raises(rs.RagflowSpaceError) as ei:
        await rs.resolve("sp_missing")
    assert "不存在" in str(ei.value)
    assert "空间A" in str(ei.value)


async def test_duplicate_name_rejected():
    await _add_space("同名")
    with pytest.raises(rs.RagflowSpaceError) as ei:
        await rs.create_space("同名", "ragflow-bbbb-2222")
    assert "已经存在" in str(ei.value)


async def test_ensure_legacy_space_uses_old_key():
    async with AsyncSessionLocal() as s:
        s.add(
            SystemSetting(
                key="ragflow.api_key",
                value={"v": "ragflow-legacy-999"},
                category="data-source",
                description="",
                is_secret=True,
            )
        )
        await s.commit()
    await rs.ensure_legacy_space()
    sp = await rs.default_space()
    assert sp is not None and sp.name == "默认空间"
    assert (await rs.credential_for(sp.id))[1] == "ragflow-legacy-999"


async def test_cannot_delete_default():
    sp = await _add_space(default=True)
    with pytest.raises(rs.RagflowSpaceError) as ei:
        await rs.delete_space(sp.id)
    assert "默认空间" in str(ei.value)
