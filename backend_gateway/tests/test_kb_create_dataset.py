"""新建知识库数据集 (2026-10-29).

背景:
    知识库的数据集以前是**管理员在 RAGFlow 里手工建的** —— 普通 tester
    想把"项目管理""协议管理"这类内容单独分个库, 只能去求 admin.
    现在把建库入口开放出来 (tester 及以上, 跟上传同一档).

权限分层:
    · 建库 / 上传 → **tester 及以上**
    · viewer       → **只读**, 界面不显示按钮, 接口也拦 (403)
    · 删除数据集   → 目前**没有**开放 (RAGFlow 支持, 但建错库该由 admin 收拾)

⚠️ 这里的 RAGFlow 全是**假的** (monkeypatch) —— 单测不碰真的 RAGFlow,
   更不碰真的知识库.
"""
from __future__ import annotations

import pytest

API = "/api/v1"

#: 现有数据集里用的嵌入模型 —— 新建的库必须跟它一致, 否则检索对不上
EMB = "qwen3-embedding:0.6b@qwen3-embedding:@Ollama"


# ---------- 假的 RAGFlow ----------

class FakeRagflow:
    """记录建库调用, 返回可预期的结果."""

    def __init__(self, datasets: list[dict] | None = None) -> None:
        self.datasets = datasets if datasets is not None else [
            {"id": "ds-1", "name": "协议文档", "chunk_method": "manual"},
            {"id": "ds-2", "name": "项目管理", "chunk_method": "naive",
             "embedding_model": EMB},
        ]
        self.calls: list[dict] = []
        self.next_id = "ds-new"

    async def list_datasets(self, page=1, page_size=50):
        return self.datasets

    async def create_dataset(self, name, description="", chunk_method="naive",
                             embedding_model="", permission="me"):
        self.calls.append({
            "name": name,
            "description": description,
            "chunk_method": chunk_method,
            "embedding_model": embedding_model,
            "permission": permission,
        })
        return {
            "id": self.next_id,
            "name": name,
            "description": description,
            "chunk_method": chunk_method,
            "embedding_model": embedding_model,
            "permission": permission,
            "document_count": 0,
            "chunk_count": 0,
        }


@pytest.fixture
def fake_rf(monkeypatch):
    """把 kb 模块里的建库调用换成假的."""
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "create_dataset", rf.create_dataset)
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    return rf


# ---------- ① 权限: 谁能建库 ----------

async def test_tester_can_create_dataset(client, publisher_user, fake_rf):
    """tester 能建库 —— tester 本来就能往库里塞东西, 建库是同一档权限."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "售后培训资料", "description": "新人入职要看的材料"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["dataset"]["id"] == "ds-new"
    assert j["dataset"]["name"] == "售后培训资料"
    assert j["dataset"]["description"] == "新人入职要看的材料"
    assert fake_rf.calls, "建库请求该发出去了"


async def test_admin_can_create_dataset(client, admin_user, fake_rf):
    """admin 当然能建."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "管理员建的库"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text


async def test_viewer_cannot_create_dataset(client, stranger_user, fake_rf):
    """⚠️ viewer 是**只读**角色 —— 不能建库.

    建出来的库是**共享**的 (所有人共用一把 RAGFlow API key),
    viewer 往里塞东西等于替所有人做主.
    """
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "viewer 建的库"},
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 403, r.text
    assert fake_rf.calls == [], "viewer 不该能建库"


async def test_create_dataset_requires_login(client, fake_rf):
    """没登录不能建库."""
    r = await client.post(f"{API}/kb/datasets", json={"name": "匿名库"})
    assert r.status_code == 401, r.text
    assert fake_rf.calls == []


# ---------- ② 参数校验 ----------

async def test_empty_name_rejected(client, publisher_user, fake_rf):
    """空名字 → 422 (FastAPI 的 min_length 拦)."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": ""},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 422, r.text
    assert fake_rf.calls == []


async def test_invalid_chunk_method_rejected(client, publisher_user, fake_rf):
    """⚠️ 切片方式必须跟 RAGFlow 的合法集合对齐 —— 别的值传下去 RAGFlow 会拒.

    放开了只会让用户收到一句看不懂的 "ragflow error".
    ⚠️ 特别地 **"general" 不行** —— 那是更新版本 RAGFlow 的说法,
    这台机器上的 v0.26.1 只认 "naive"(真机实测 code 101).

    ⚠️ 2026-10-29 第七轮: 合法集合**放开**成了 RAGFlow 真正支持的那 13 种
    (之前只让 naive/manual 过, `qa`/`table` 这些其实 RAGFlow 是支持的) ——
    所以现在拿 `qa` 举例是**非法**了, 得拿真正不存在的值.
    """
    for bad in ("general", "xyz"):
        r = await client.post(
            f"{API}/kb/datasets",
            json={"name": "奇怪的库", "chunk_method": bad},
            headers={"Authorization": f"Bearer {publisher_user['token']}"},
        )
        assert r.status_code == 422, f"{bad!r}: {r.text}"
        assert "naive" in r.json()["detail"], r.text
    assert fake_rf.calls == []

    # ⚠️ 空串 = "没指定" → 走默认的 naive (不是非法值)
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "空切片的库", "chunk_method": ""},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text


async def test_general_chunk_method_rejected(client, publisher_user, fake_rf):
    """⚠️ "general" 在 v0.26.1 上是**非法值** —— 必须在网关这层就挡住."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "用了 general 的库", "chunk_method": "general"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 422, r.text
    assert fake_rf.calls == []


async def test_manual_chunk_method_accepted(client, publisher_user, fake_rf):
    """手动切分 (manual) 是合法选项 —— 协议文档那个库就是它."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "协议规范", "chunk_method": "manual"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert fake_rf.calls[0]["chunk_method"] == "manual"


async def test_chunk_method_defaults_to_naive(client, publisher_user, fake_rf):
    """不填切片方式 → 默认 naive (通用)."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "默认库"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert fake_rf.calls[0]["chunk_method"] == "naive"


# ---------- ③ 嵌入模型: 必须跟现有的一致 ----------

async def test_embedding_model_inherited_from_existing_datasets(client, publisher_user, fake_rf):
    """⚠️ 不指定嵌入模型时**继承现有数据集的** —— 不能用 RAGFlow 租户默认值.

    这台机器上装的是 qwen3-embedding:0.6b, RAGFlow 租户默认值未必是它,
    用错了新库建的向量跟老库不是一个空间, 检索会静默地搜不准.
    """
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "继承嵌入模型的库"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert fake_rf.calls[0]["embedding_model"] == EMB, fake_rf.calls[0]


async def test_explicit_embedding_model_is_used(client, publisher_user, fake_rf):
    """显式指定了就用指定的."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "指定模型的库", "embedding_model": "bge-m3"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert fake_rf.calls[0]["embedding_model"] == "bge-m3"


# ---------- ④ 重名 / 后端故障要分清楚 ----------

async def test_duplicate_name_returns_422(client, publisher_user, monkeypatch):
    """⚠️ 重名 → 422 (是用户自己能改的错), 不是 500.

    RAGFlow 自己会加数字后缀 (`项目管理` → `项目管理(1)`) —— 与其让用户
    以为建了个新库, 不如当场报错.
    """
    import app.api.kb as kb_mod

    async def _dup(name, description="", chunk_method="naive",
                   embedding_model="", permission="me"):
        raise ValueError(f"已经有一个叫「{name}」的数据集了")

    monkeypatch.setattr(kb_mod, "create_dataset", _dup)

    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "项目管理"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 422, r.text
    assert "项目管理" in r.json()["detail"], r.text


async def test_ragflow_failure_returns_502(client, publisher_user, monkeypatch):
    """RAGFlow 炸了 → 502 (是服务端故障, 不是用户的错)."""
    import app.api.kb as kb_mod

    async def _boom(**kw):
        raise RuntimeError("ragflow 连不上")

    monkeypatch.setattr(kb_mod, "create_dataset", _boom)

    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "会失败的库"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 502, r.text
    assert "ragflow" in r.json()["detail"], r.text
