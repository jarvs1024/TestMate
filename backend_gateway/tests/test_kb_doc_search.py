"""知识库「按文件名搜文档」(2026-10-29 第五轮).

背景:
    知识库有 4 个库 / 11 篇文档, 找一篇东西只能一个个库展开翻。
    现在加一个**跨库**的文件名搜索 —— 输入关键词, 一次列出所有命中的文档
    (连同它们在哪个库、谁传的), 搜到就能接着分段/下载/更新。

⚠️ RAGFlow 的 keywords 语义是 `LOWER(name).contains(keywords.lower())`
   —— **不区分大小写的子串匹配**, 且**只搜文件名, 不搜内容**
   (`api/db/services/document_service.py:135`).

⚠️ RAGFlow 的 keywords 是**按单个数据集**过滤的 —— 搜全部库要**逐个库**查.

⚠️ 这里的 RAGFlow 全是**假的** (monkeypatch) —— 单测不碰真的 RAGFlow.
"""
from __future__ import annotations

import pytest

API = "/api/v1"


# ---------- 假的 RAGFlow ----------

class FakeRagflow:
    def __init__(self) -> None:
        self.datasets: dict[str, dict] = {
            "ds-a": {"id": "ds-a", "name": "协议文档", "chunk_method": "manual"},
            "ds-b": {"id": "ds-b", "name": "技术文档", "chunk_method": "naive"},
        }
        self.docs: list[dict] = [
            {"id": "d-1", "name": "验收标准.pdf", "_ds": "ds-a", "size": 100},
            {"id": "d-2", "name": "2026年度计划.docx", "_ds": "ds-a", "size": 200},
            {"id": "d-3", "name": "AGENTS.md", "_ds": "ds-b", "size": 300},
            {"id": "d-4", "name": "readme.TXT", "_ds": "ds-b", "size": 400},
        ]
        self.list_datasets_fail = False
        #: 记录每次 list_documents 传了什么 keywords
        self.calls: list[dict] = []

    async def list_datasets(self, page=1, page_size=50):
        if self.list_datasets_fail:
            raise RuntimeError("ragflow 炸了")
        return list(self.datasets.values())

    async def upload_documents(self, dataset_id, files):
        out = []
        for name, data, _ctype in files:
            doc = {"id": f"d-up-{len(self.docs) + 1}", "name": name,
                   "_ds": dataset_id, "size": len(data)}
            self.docs.append(doc)
            out.append(doc)
        return out

    async def ingest_documents(self, doc_ids, run="1", delete=False):
        return True

    async def list_documents(self, dataset_id, page=1, page_size=30,
                             orderby="create_time", desc=True, keywords="", run=""):
        self.calls.append({"dataset_id": dataset_id, "keywords": keywords, "page": page})
        docs = [d for d in self.docs if d.get("_ds") == dataset_id]
        if keywords:
            # ⚠️ 照 RAGFlow 的真实语义: 不区分大小写的**子串**匹配
            k = keywords.lower()
            docs = [d for d in docs if k in str(d.get("name") or "").lower()]
        # 照 RAGFlow 的分页: 本页条数不足就是最后一页
        start = (page - 1) * page_size
        return {"docs": docs[start:start + page_size], "total": len(docs)}


@pytest.fixture
def fake_rf(monkeypatch):
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    monkeypatch.setattr(kb_mod, "list_documents", rf.list_documents)
    monkeypatch.setattr(kb_mod, "upload_documents", rf.upload_documents)
    monkeypatch.setattr(kb_mod, "ingest_documents", rf.ingest_documents)
    return rf


# ---------- ① 基本搜索 ----------

async def test_search_across_datasets(client, publisher_user, fake_rf):
    """⚠️ **跨库**搜 —— 一个关键词要把所有库都翻一遍."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "计划"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 1, j
    assert j["items"][0]["name"] == "2026年度计划.docx", j
    # ⚠️ 结果必须带「在哪个库」—— 否则用户找到了却不知道东西在哪
    assert j["items"][0]["dataset_name"] == "协议文档", j
    assert j["items"][0]["dataset_id"] == "ds-a", j


async def test_search_is_case_insensitive(client, publisher_user, fake_rf):
    """RAGFlow 的匹配是 `LOWER(name).contains(...)` —— 不区分大小写."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "agents"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 1, j
    assert j["items"][0]["name"] == "AGENTS.md", j


async def test_search_matches_substring(client, publisher_user, fake_rf):
    """子串匹配 —— 搜「标准」能命中「验收标准.pdf」."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "标准"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1, r.json()


async def test_search_hit_in_multiple_datasets(client, publisher_user, fake_rf):
    """同一个关键词命中多个库 —— 结果要**全部**返回, 别只取第一个库."""
    fake_rf.docs.append({"id": "d-5", "name": "readme.md", "_ds": "ds-a", "size": 500})
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "readme"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 2, j
    assert {x["dataset_id"] for x in j["items"]} == {"ds-a", "ds-b"}, j


async def test_search_every_dataset_is_queried(client, publisher_user, fake_rf):
    """⚠️ 得**逐个库**查 —— 漏一个库就漏一批文档."""
    await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "x"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert {c["dataset_id"] for c in fake_rf.calls} == {"ds-a", "ds-b"}, fake_rf.calls


async def test_search_limit_to_one_dataset(client, publisher_user, fake_rf):
    """限定某个库时, 只查那个库."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "e", "dataset_id": "ds-b"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert {c["dataset_id"] for c in fake_rf.calls} == {"ds-b"}, fake_rf.calls
    assert all(x["dataset_id"] == "ds-b" for x in j["items"]), j


# ---------- ② 边界 ----------

async def test_empty_keywords_returns_nothing(client, publisher_user, fake_rf):
    """空关键词 → 空结果, **不要**去查 RAGFlow (白跑一轮)."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "   "},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["items"] == [] and j["total"] == 0, j
    assert fake_rf.calls == [], fake_rf.calls


async def test_no_match_returns_empty(client, publisher_user, fake_rf):
    """搜不到 → 空列表, 不是报错."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "压根没有这个文件"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["items"] == [] and j["total"] == 0, j


async def test_search_needs_login(client, fake_rf):
    """搜索是只读操作 —— 但**得登录** (跟其它知识库接口一个口径)."""
    r = await client.get(f"{API}/kb/documents/search", params={"keywords": "a"})
    assert r.status_code in (401, 403), r.text


async def test_viewer_can_search(client, stranger_user, fake_rf):
    """⚠️ viewer 也能搜 —— 搜索是**只读**操作, 跟「看数据集」「下载文档」同一档."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "a"},
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 1, r.text


async def test_ragflow_down_returns_502(client, publisher_user, fake_rf):
    """RAGFlow 挂了 → 502 (服务端故障, 不是用户的错)."""
    fake_rf.list_datasets_fail = True
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "a"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 502, r.text
    assert "ragflow" in r.json()["detail"], r.text


# ---------- ③ 结果里带上归属 ----------

async def test_search_result_carries_owner(client, publisher_user, admin_user, fake_rf):
    """结果里要带「谁传的」—— RAGFlow 那边记不了 TestMate 的账号."""
    # 先上传一篇, 让它有归属
    import io

    r0 = await client.post(
        f"{API}/kb/datasets/ds-b/documents",
        files=[("file", ("readme.TXT", io.BytesIO(b"x"), "text/plain"))],
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r0.status_code == 200, r0.text

    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "readme"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    hits = [x for x in r.json()["items"] if x["uploaded_by_name"]]
    assert hits, r.json()
    assert hits[0]["uploaded_by_name"] == publisher_user["username"], hits[0]


async def test_search_result_has_full_document_fields(client, publisher_user, fake_rf):
    """⚠️ 结果必须是**完整的文档对象** —— 点「详情」「分段」都要用得到."""
    r = await client.get(
        f"{API}/kb/documents/search",
        params={"keywords": "AGENTS"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    hit = r.json()["items"][0]
    for k in ("id", "name", "size", "chunk_count", "run", "location",
              "type", "status", "parser_config", "process_duration"):
        assert k in hit, f"少了字段 {k}: {hit}"
