"""RAGFlow 建库客户端 (2026-10-29).

⚠️ 这里锁的是**几个真实的坑**, 都是真机跑出来才知道的 (单测的假 httpx
   永远测不出来 —— 它不会校验字段名):

  ① 对外字段是 **`chunk_method`**, **不是 `parser_id`** ——
     `parser_id` 只是 RAGFlow 服务内部的别名 (CreateDatasetReq 里标了
     serialization_alias="parser_id"), 直接当请求字段传会被判
     "Extra inputs are not permitted".
     通用切片的值是 **`naive`**, "general" 是更新版本的说法, v0.26.1 不认.
  ② 响应的 `data` 是**一个对象**, 不是数组 —— 列表接口才是数组.
  ③ `description` **可以直接在 create 时传** (旧版文档说不行, v0.26.1 可以),
     所以不用建完再补一次 PUT.
  ④ 数据集名**大小写不敏感且唯一**, 重名 RAGFlow 会自动加数字后缀
     (`项目管理` → `项目管理(1)`) —— 用户以为建了个新库, 结果多出两个几乎一样的库.
     所以客户端先查重, 撞了直接报错.
  ⑤ `permission` 跟现有数据集保持一致 (默认 'me') —— 这台机器上所有数据集
     都是 'me', 混着来不好排查.

⚠️ httpx 是**假的** —— 单测不碰真的 RAGFlow.
"""
from __future__ import annotations

import pytest


class FakeResp:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeClient:
    """假的 httpx.AsyncClient —— 记录请求, 返回预设响应."""

    #: (method, url, payload) 三元组
    calls: list[tuple[str, str, dict]] = []
    #: GET /datasets 时返回的列表
    datasets: list[dict] = []
    #: POST /datasets 的响应体 —— ⚠️ RAGFlow 的 create 返回**对象**, 不是数组
    post_data: dict = {}

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        FakeClient.calls.append(("GET", url, params or {}))
        return FakeResp({"code": 0, "data": FakeClient.datasets})

    async def post(self, url, headers=None, json=None):
        FakeClient.calls.append(("POST", url, json or {}))
        return FakeResp({"code": 0, "data": FakeClient.post_data or {"id": "ds-new"}})

    async def put(self, url, headers=None, json=None):
        FakeClient.calls.append(("PUT", url, json or {}))
        return FakeResp({"code": 0, "data": {}})


@pytest.fixture
def fake_http(monkeypatch):
    """把 httpx 和配置都换成假的."""
    import app.core.ragflow_client as rc

    FakeClient.calls = []
    FakeClient.datasets = []
    FakeClient.post_data = {}

    monkeypatch.setattr(rc.httpx, "AsyncClient", FakeClient)

    async def _cfg():
        return ("http://ragflow.test", "key-123")

    monkeypatch.setattr(rc, "_config", _cfg)
    return FakeClient


# ---------- ① 请求体对不对 ----------

async def test_create_dataset_body(fake_http):
    """⚠️ 对外字段是 **`chunk_method`**, 不是 `parser_id`.

    传 `parser_id` 会被 RAGFlow 当成多余字段拒掉:
    "Field: <parser_id> - Message: <Extra inputs are not permitted>"
    """
    import app.core.ragflow_client as rc

    out = await rc.create_dataset(
        name="项目管理", description="项目相关文档", chunk_method="naive",
        embedding_model="bge-m3",
    )
    assert out["id"] == "ds-new"

    posts = [c for c in fake_http.calls if c[0] == "POST"]
    assert len(posts) == 1, fake_http.calls
    _m, url, body = posts[0]
    assert url.endswith("/datasets"), url
    assert body["name"] == "项目管理"
    assert body["chunk_method"] == "naive", body
    assert body["embedding_model"] == "bge-m3", body
    assert body["permission"] == "me", body
    # ⚠️ 这些字段 RAGFlow 1.0 不收 —— 传了直接 400
    assert "parser_id" not in body, body
    assert "parse_type" not in body, body
    assert "pipeline_id" not in body, body


async def test_create_dataset_returns_object_not_list(fake_http):
    """⚠️ create 接口的 `data` 是**一个对象** —— 写成 `data[0]` 会 IndexError."""
    import app.core.ragflow_client as rc

    fake_http.post_data = {"id": "ds-9", "name": "x", "chunk_method": "naive"}
    out = await rc.create_dataset(name="x")
    assert isinstance(out, dict), type(out)
    assert out["id"] == "ds-9"


async def test_create_dataset_handles_array_response(fake_http):
    """万一哪天 RAGFlow 改回数组, 也不能崩."""
    import app.core.ragflow_client as rc

    fake_http.post_data = [{"id": "ds-8", "name": "x"}]
    out = await rc.create_dataset(name="x")
    assert isinstance(out, dict), type(out)
    assert out["id"] == "ds-8"


async def test_create_dataset_permission_defaults_to_me(fake_http):
    """默认权限跟现有数据集一致 ('me')."""
    import app.core.ragflow_client as rc

    await rc.create_dataset(name="权限测试")
    _m, _u, body = [c for c in fake_http.calls if c[0] == "POST"][0]
    assert body["permission"] == "me", body


# ---------- ② description 直接传 ----------

async def test_description_is_sent_on_create(fake_http):
    """⚠️ v0.26.1 的 create **能直接收 description** —— 不用建完再补一次 PUT.

    少一次请求就少一次失败机会 (补说明失败还得处理"库建好了但说明没写上").
    """
    import app.core.ragflow_client as rc

    await rc.create_dataset(name="带说明的库", description="这个库放项目管理的东西")

    methods = [c[0] for c in fake_http.calls]
    assert methods == ["GET", "POST"], methods

    _m, _u, body = [c for c in fake_http.calls if c[0] == "POST"][0]
    assert body["description"] == "这个库放项目管理的东西", body


async def test_no_description_means_no_description_field(fake_http):
    """没填说明就别发空串 —— 少一个没意义的字段."""
    import app.core.ragflow_client as rc

    await rc.create_dataset(name="没说明的库")
    _m, _u, body = [c for c in fake_http.calls if c[0] == "POST"][0]
    assert "description" not in body, body


async def test_create_failure_is_raised(fake_http, monkeypatch):
    """RAGFlow 报错要往上抛 —— 不能建出个半成品还当成功."""
    import app.core.ragflow_client as rc

    async def _fail(self, url, headers=None, json=None):
        FakeClient.calls.append(("POST", url, json or {}))
        return FakeResp({"code": 100, "message": "名称已存在"})

    monkeypatch.setattr(FakeClient, "post", _fail)

    with pytest.raises(RuntimeError) as ex:
        await rc.create_dataset(name="会失败的库")
    assert "名称已存在" in str(ex.value)


# ---------- ③ 重名要拦 ----------

async def test_duplicate_name_raises_value_error(fake_http):
    """⚠️ 重名直接报错 —— 不能让 RAGFlow 建出个 `项目管理(1)`."""
    import app.core.ragflow_client as rc

    fake_http.datasets = [{"id": "ds-1", "name": "项目管理"}]

    with pytest.raises(ValueError) as ex:
        await rc.create_dataset(name="项目管理")
    assert "项目管理" in str(ex.value)

    # ⚠️ 压根不该发 POST —— 已经知道撞名了
    assert not [c for c in fake_http.calls if c[0] == "POST"], fake_http.calls


async def test_duplicate_name_is_case_insensitive(fake_http):
    """RAGFlow 的名字**大小写不敏感** —— 撞名判定也得一样."""
    import app.core.ragflow_client as rc

    fake_http.datasets = [{"id": "ds-1", "name": "Project Management"}]

    with pytest.raises(ValueError):
        await rc.create_dataset(name="project management")


async def test_duplicate_name_ignores_surrounding_space(fake_http):
    """名字前后的空格不该影响撞名判定."""
    import app.core.ragflow_client as rc

    fake_http.datasets = [{"id": "ds-1", "name": "项目管理"}]

    with pytest.raises(ValueError):
        await rc.create_dataset(name="  项目管理  ")


async def test_different_name_is_allowed(fake_http):
    """不撞名就放行."""
    import app.core.ragflow_client as rc

    fake_http.datasets = [{"id": "ds-1", "name": "项目管理"}]
    out = await rc.create_dataset(name="协议管理")
    assert out["id"] == "ds-new"


# ---------- ④ 名字本身要合法 ----------

async def test_empty_name_raises(fake_http):
    import app.core.ragflow_client as rc

    with pytest.raises(ValueError):
        await rc.create_dataset(name="   ")


async def test_too_long_name_raises(fake_http):
    import app.core.ragflow_client as rc

    with pytest.raises(ValueError):
        await rc.create_dataset(name="x" * 129)


# ---------- ⑤ update_dataset ----------

async def test_update_dataset_sends_only_given_fields(fake_http):
    """改数据集时只传要改的字段 —— 传多了会把没打算改的东西覆盖掉."""
    import app.core.ragflow_client as rc

    await rc.update_dataset("ds-1", description="新的说明")
    _m, url, body = [c for c in fake_http.calls if c[0] == "PUT"][0]
    assert url.endswith("/datasets/ds-1"), url
    assert body == {"description": "新的说明"}, body


async def test_update_dataset_with_chunk_method(fake_http):
    """改切片方式时字段名也是 `chunk_method`."""
    import app.core.ragflow_client as rc

    await rc.update_dataset("ds-1", chunk_method="manual")
    _m, _u, body = [c for c in fake_http.calls if c[0] == "PUT"][0]
    assert body["chunk_method"] == "manual", body
    assert "parser_id" not in body, body
    assert "parse_type" not in body, body


async def test_update_dataset_with_nothing_is_noop(fake_http):
    """什么都不改就别发请求."""
    import app.core.ragflow_client as rc

    assert await rc.update_dataset("ds-1") == {}
    assert fake_http.calls == [], fake_http.calls
