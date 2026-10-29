"""新建数据集: 解析方式 (chunk_method) + 语言 (language) (2026-10-29 第七轮).

背景:
    用户要能在建库时选**解析方式**和**语言**.

⚠️ **这版 RAGFlow (v0.26.1) 的三个硬事实** (真机 + 容器源码都核过):
    ① 对外字段是 **`chunk_method`**, **不是 `parser_id`** ——
       `parser_id` 只是服务内部的 `serialization_alias`,
       直接当请求字段传会被判 "Extra inputs are not permitted" → 400.
    ② 通用切片的值是 **`naive`** —— `general` 是更新版本的说法, **这版不认**.
    ③ **建库接口不吃 `language`** (`CreateDatasetReq` 里根本没这个字段) ——
       但 `UpdateDatasetReq` (PUT /datasets/{id}) 有, 所以网关是
       **先建库、再补一次 PUT** 设语言.
       而且 RAGFlow 建库时的默认语言是 **English**, 中文库必须显式补 PUT.

⚠️ 单测不碰真的 RAGFlow —— 全部 monkeypatch 掉.
"""
from __future__ import annotations

import pytest

API = "/api/v1"

#: 这版 RAGFlow 允许的 chunk_method 全集 (容器里的校验器)
VALID_CHUNK_METHODS = {
    "naive", "qa", "table", "paper", "book", "laws",
    "presentation", "picture", "one", "email", "tag", "resume", "manual",
}


class FakeRagflow:
    def __init__(self) -> None:
        self.created: list[dict] = []
        #: ⚠️ **建库那一步实际收到的参数** —— 用来断言"没有传 language"
        self.created_kwargs: list[dict] = []
        self.updated: list[dict] = []
        #: 模拟「补语言那一步失败」
        self.fail_update = False

    async def list_datasets(self, page=1, page_size=50):
        return []

    async def create_dataset(self, name, description="", chunk_method="naive",
                             embedding_model="", permission="me"):
        ds = {
            "id": f"ds-new-{len(self.created) + 1}",
            "name": name,
            "description": description,
            "chunk_method": chunk_method,
            "embedding_model": embedding_model,
            "permission": permission,
            "document_count": 0,
            "chunk_count": 0,
            # ⚠️ RAGFlow 建库返回的 language 是它的默认值 (English)
            "language": "English",
        }
        self.created.append(ds)
        self.created_kwargs.append({
            "name": name, "description": description,
            "chunk_method": chunk_method, "embedding_model": embedding_model,
        })
        return ds

    async def update_dataset(self, dataset_id, name=None, description=None,
                             chunk_method=None, language=None):
        if self.fail_update:
            raise RuntimeError("ragflow 炸了")
        call = {"dataset_id": dataset_id, "language": language,
                "name": name, "description": description, "chunk_method": chunk_method}
        self.updated.append(call)
        return {"id": dataset_id, "language": language}

    async def delete_dataset(self, dataset_id):
        return True


@pytest.fixture
def fake_rf(monkeypatch):
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "create_dataset", rf.create_dataset)
    monkeypatch.setattr(kb_mod, "update_dataset", rf.update_dataset)
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    return rf


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------- ① 解析方式 ----------

async def test_create_dataset_defaults_to_naive(client, publisher_user, fake_rf):
    """默认是「通用」= RAGFlow 的 `naive` (不是 `general`)."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "默认库"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 200, r.text
    assert fake_rf.created[0]["chunk_method"] == "naive", fake_rf.created[0]
    assert r.json()["dataset"]["chunk_method"] == "naive", r.text


async def test_create_dataset_accepts_other_parsers(client, publisher_user, fake_rf):
    """⚠️ RAGFlow 支持 13 种解析方式 —— 都能选, 且原样传下去."""
    for m in ("qa", "table", "paper", "book", "laws", "manual", "tag", "resume"):
        fake_rf.created.clear()
        r = await client.post(
            f"{API}/kb/datasets",
            json={"name": f"库-{m}", "chunk_method": m},
            headers=_auth(publisher_user["token"]),
        )
        assert r.status_code == 200, f"{m}: {r.text}"
        assert fake_rf.created[0]["chunk_method"] == m, fake_rf.created[0]


async def test_create_dataset_rejects_unknown_parser(client, publisher_user, fake_rf):
    """⚠️ 非法值要在**网关**就拦下来 —— 传到 RAGFlow 是 code 101, 库建不出来."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "坏库", "chunk_method": "general"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 422, r.text
    assert not fake_rf.created, "不该真的去建库"


async def test_create_dataset_parser_case_insensitive(client, publisher_user, fake_rf):
    """大小写不敏感 —— 用户手打 `QA` 也能用."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "大写库", "chunk_method": "QA"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 200, r.text
    assert fake_rf.created[0]["chunk_method"] == "qa", fake_rf.created[0]


# ---------- ② 语言 ----------

async def test_create_dataset_sets_language_via_second_put(client, publisher_user, fake_rf):
    """⚠️ 建库接口**不吃** language → 网关建完必须**补一次 PUT**."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "中文库", "language": "Chinese"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 200, r.text
    # 建库那步**没带** language (RAGFlow 会 400)
    assert "language" not in fake_rf.created_kwargs[0], fake_rf.created_kwargs[0]
    # 但补了 PUT
    assert len(fake_rf.updated) == 1, fake_rf.updated
    assert fake_rf.updated[0]["language"] == "Chinese", fake_rf.updated[0]
    # 响应里回填用户要的那个语言 (不是 RAGFlow 的默认值 English)
    assert r.json()["dataset"]["language"] == "Chinese", r.text


async def test_create_dataset_language_english(client, publisher_user, fake_rf):
    """英文库也能建."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "英文库", "language": "English"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 200, r.text
    assert fake_rf.updated[0]["language"] == "English", fake_rf.updated[0]


async def test_create_dataset_rejects_unknown_language(client, publisher_user, fake_rf):
    """非法语言要在网关拦下来."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "怪库", "language": "Klingon"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 422, r.text
    assert not fake_rf.created, "不该真的去建库"


async def test_create_dataset_language_failure_is_reported_not_hidden(client, publisher_user, fake_rf):
    """⚠️ 补 PUT 失败 → **库已经建出来了**, 不能整个失败, 但要**如实说**.

    谎报成功 = 用户以为语言设上了, 其实是 English —— 后面自动问答全跑偏.
    """
    fake_rf.fail_update = True
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "半成品库", "language": "Chinese"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body.get("warning"), f"语言没设上必须给 warning: {body}"
    assert "语言" in body["warning"], body["warning"]


async def test_create_dataset_no_warning_when_all_good(client, publisher_user, fake_rf):
    """一切正常时**不该**有 warning —— 别制造噪音."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "正常库", "language": "Chinese"},
        headers=_auth(publisher_user["token"]),
    )
    assert r.status_code == 200, r.text
    assert not r.json().get("warning"), r.text


# ---------- ③ 权限不变 ----------

async def test_create_dataset_still_tester_and_above(client, stranger_user, fake_rf):
    """⚠️ 加了参数**不等于**放宽权限 —— viewer 还是不能建库."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "只读库", "language": "Chinese", "chunk_method": "qa"},
        headers=_auth(stranger_user["token"]),
    )
    assert r.status_code == 403, r.text
    assert not fake_rf.created
