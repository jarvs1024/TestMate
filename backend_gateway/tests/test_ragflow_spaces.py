"""RAGFlow 用户空间: 加密、回退空间、解析与旧配置迁移."""
from datetime import datetime

import pytest

from app.core import ragflow_spaces as rs
from app.db.session import AsyncSessionLocal
from app.models.ragflow_space import RagflowSpace
from app.models.system_setting import SystemSetting


async def _add_space(name="A", key="ragflow-old-key-123456"):
    return await rs.create_space(name, key)


async def test_create_encrypts_key_and_resolves():
    sp = await _add_space("空间A", "ragflow-aaaa-1111")
    assert sp.id.startswith("sp_")
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, sp.id)
        assert row.api_key_cipher.startswith("v1:")
        assert "ragflow-aaaa-1111" not in row.api_key_cipher
    _base, key, resolved = await rs.credential_for(sp.id)
    assert resolved.id == sp.id
    assert key == "ragflow-aaaa-1111"


async def test_fallback_space_is_the_oldest():
    a = await _add_space("A")
    await _add_space("B")
    # created_at 只存到秒, 连续创建会撞同一秒 —— 明确把 A 拨早
    async with AsyncSessionLocal() as s:
        row = await s.get(RagflowSpace, a.id)
        row.created_at = datetime(2026, 1, 1)
        await s.commit()
    assert (await rs.fallback_space()).id == a.id


async def test_resolve_unknown_lists_available():
    await _add_space("空间A")
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
    sp = await rs.fallback_space()
    assert sp is not None and sp.name == "默认空间"
    assert (await rs.credential_for(sp.id))[1] == "ragflow-legacy-999"


async def test_any_space_can_be_deleted():
    a = await _add_space("A")
    b = await _add_space("B")
    await rs.delete_space(a.id)
    assert (await rs.fallback_space()).id == b.id, "删掉最早的空间后回退到下一个"
