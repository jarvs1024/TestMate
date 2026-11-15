"""ragflow_client 按 space_id 解析凭据."""
from app.core import ragflow_client as rc
from app.core import ragflow_spaces as rs


async def test_config_uses_given_space():
    sp = await rs.create_space("空间A", "ragflow-aaaa-1111")
    _base, key = await rc._config(sp.id)
    assert key == "ragflow-aaaa-1111"


async def test_config_defaults_when_no_space():
    await rs.create_space("默认", "ragflow-default-2222")
    _base, key = await rc._config(None)
    assert key == "ragflow-default-2222"


async def test_list_datasets_passes_space_to_config(monkeypatch):
    seen = {}

    async def fake_config(space_id=None):
        seen["space_id"] = space_id
        return "", "mock-key"

    monkeypatch.setattr(rc, "_config", fake_config)
    assert await rc.list_datasets(space_id="sp_x") == []
    assert seen["space_id"] == "sp_x"
