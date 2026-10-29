"""知识库「更新文档」+「重新解析」(2026-10-29 第四轮).

背景:
    RAGFlow 的文档是**不可变**的 —— 它压根没有"替换文件内容"的接口
    (`PATCH /datasets/{id}/documents/{doc}` 只能改 name / parser_config /
    chunk_method / enabled). 所以「更新文档」是网关自己拼出来的四步:

        ① 传新文件   → RAGFlow 新建一条记录 (同名自动加 "(1)" 后缀)
        ② 删旧文档   → 硬删
        ③ PATCH 新文档 → 名字改回目标名
        ④ 迁移归属 + 启动解析

    ⚠️ 2026-10-29 用户拍板: **旧版直接删除** (不留历史), **更新权限 tester 及以上**.

⚠️ 这里的 RAGFlow 全是**假的** (monkeypatch) —— 单测不碰真的 RAGFlow.
"""
from __future__ import annotations

import io
import os

import pytest

API = "/api/v1"


# ---------- 假的 RAGFlow ----------

class FakeRagflow:
    """照着 RAGFlow 的真实行为仿的: 同名上传会自动加 "(1)" 后缀."""

    def __init__(self) -> None:
        self.datasets: dict[str, dict] = {
            "ds-naive": {
                "id": "ds-naive", "name": "技术文档", "description": "",
                "chunk_method": "naive", "embedding_model": "emb",
                "permission": "me", "document_count": 0, "chunk_count": 0,
            },
            "ds-manual": {
                "id": "ds-manual", "name": "协议文档", "description": "",
                "chunk_method": "manual", "embedding_model": "emb",
                "permission": "me", "document_count": 0, "chunk_count": 0,
            },
        }
        self.docs: list[dict] = []
        self._seq = 0
        #: 记录调用过哪些 PATCH —— 断言用
        self.patched: list[dict] = []
        #: 记录解析请求
        self.parsed: list[list[str]] = []
        self.ingested: list[list[str]] = []
        #: 故障注入 —— 只让删**指定 id** 失败 (不然回滚那次删除也会挂, 测不了回滚)
        self.fail_delete_ids: set[str] = set()
        self.fail_update = False
        self.fail_parse = False

    def _next_id(self) -> str:
        self._seq += 1
        return f"doc-{self._seq}"

    def _name_in_use(self, kb_id: str, name: str) -> bool:
        return any(d.get("_ds") == kb_id and d.get("name") == name for d in self.docs)

    async def list_datasets(self, page=1, page_size=50):
        return list(self.datasets.values())

    async def list_documents(self, dataset_id, page=1, page_size=30,
                             orderby="create_time", desc=True, keywords="", run=""):
        docs = [d for d in self.docs if d.get("_ds") == dataset_id]
        return {"docs": docs, "total": len(docs)}

    async def upload_documents(self, dataset_id, files):
        out = []
        for name, data, _ctype in files:
            # ⚠️ RAGFlow 的 duplicate_name: 同名自动加 "(1)" 后缀 (插在扩展名**前**)
            final = name
            if self._name_in_use(dataset_id, name):
                stem, ext = os.path.splitext(name)
                n = 1
                while self._name_in_use(dataset_id, f"{stem}({n}){ext}"):
                    n += 1
                final = f"{stem}({n}){ext}"
            doc = {
                "id": self._next_id(), "name": final, "size": len(data),
                "location": final, "run": "UNSTART", "_ds": dataset_id,
                "chunk_method": self.datasets.get(dataset_id, {}).get("chunk_method", "naive"),
            }
            self.docs.append(doc)
            out.append(doc)
        return out

    async def delete_documents(self, dataset_id, doc_ids=None, delete_all=False):
        ids = set(doc_ids or [])
        if ids & self.fail_delete_ids:
            raise RuntimeError("ragflow 炸了")
        self.docs = [
            d for d in self.docs
            if not (d.get("_ds") == dataset_id and (d.get("id") in ids or delete_all))
        ]
        return True

    async def update_document(self, dataset_id, document_id, name=None,
                               parser_config=None, chunk_method=None, enabled=None):
        if self.fail_update:
            raise RuntimeError("ragflow 炸了")
        self.patched.append({
            "dataset_id": dataset_id, "document_id": document_id, "name": name,
            "parser_config": parser_config, "chunk_method": chunk_method, "enabled": enabled,
        })
        for d in self.docs:
            if d.get("id") == document_id:
                if name is not None:
                    d["name"] = name
                if chunk_method is not None:
                    d["chunk_method"] = chunk_method
                return d
        return {}

    async def ingest_documents(self, doc_ids, run="1", delete=False):
        self.ingested.append(list(doc_ids))
        return True

    async def parse_documents(self, dataset_id, document_ids):
        if self.fail_parse:
            raise RuntimeError("ragflow 炸了")
        self.parsed.append(list(document_ids))
        return True


@pytest.fixture
def fake_rf(monkeypatch):
    """把 kb 模块里的 RAGFlow 调用全换成假的."""
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    monkeypatch.setattr(kb_mod, "list_documents", rf.list_documents)
    monkeypatch.setattr(kb_mod, "upload_documents", rf.upload_documents)
    monkeypatch.setattr(kb_mod, "delete_documents", rf.delete_documents)
    monkeypatch.setattr(kb_mod, "update_document", rf.update_document)
    monkeypatch.setattr(kb_mod, "ingest_documents", rf.ingest_documents)
    monkeypatch.setattr(kb_mod, "parse_documents", rf.parse_documents)
    return rf


def _files(*names: str, content: bytes = b"hello"):
    """multipart 的 `files` —— httpx 要的是 [(字段名, (文件名, 文件对象, 类型)), ...]."""
    return [("file", (n, io.BytesIO(content), "text/plain")) for n in names]


async def _upload(client, who, ds_id="ds-naive", name="a.txt"):
    r = await client.post(
        f"{API}/kb/datasets/{ds_id}/documents",
        files=_files(name),
        headers={"Authorization": f"Bearer {who['token']}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["docs"][0]["id"]


# ---------- ① 权限: tester 及以上 ----------

async def test_tester_can_update_document(client, publisher_user, fake_rf):
    """tester 能更新 (2026-10-29 用户拍板: 更新权限 = tester 及以上)."""
    doc_id = await _upload(client, publisher_user)
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["updated"]["id"] != doc_id, "RAGFlow 里更新 = 删旧建新, id 会变"
    assert j["updated"]["name"] == "a.txt", j
    assert j["replaced"]["id"] == doc_id, j


async def test_viewer_cannot_update_document(client, stranger_user, fake_rf):
    """⚠️ viewer 是只读角色 —— 更新不了."""
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/doc-1",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 403, r.text


async def test_admin_can_update_document(client, admin_user, fake_rf):
    """admin 当然也能 (admin 是 tester 的超集)."""
    doc_id = await _upload(client, admin_user)
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text


async def test_update_missing_document_returns_404(client, publisher_user, fake_rf):
    """更新一个不存在的文档 → 404, 别去调 RAGFlow 删空气."""
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/doc-nope",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 404, r.text
    assert fake_rf.patched == []


# ---------- ② 扩展名不能变 ----------

async def test_update_rejects_different_extension(client, publisher_user, fake_rf):
    """⚠️ 换文件类型不是"更新内容", 是"加一篇" —— 直接拦掉.

    RAGFlow 的改名接口会拒 ("The extension of file can't be changed"),
    与其做个半成品, 不如一开始就说清楚.
    """
    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("b.pdf", content=b"%PDF-1.4"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 422, r.text
    assert "不一致" in r.json()["detail"], r.text
    # 旧文档还在 (没被动过)
    assert [d for d in fake_rf.docs if d["id"] == doc_id], fake_rf.docs


# ---------- ③ 同名更新: 名字要改回去 ----------

async def test_same_name_update_restores_original_name(client, publisher_user, fake_rf):
    """⚠️ RAGFlow 同名上传会自动加 "(1)" 后缀 —— 更新完得把名字改回去.

    否则用户会看到「a(1).txt」, 以为多了一篇.
    """
    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    new_id = r.json()["updated"]["id"]
    # PATCH 里带了目标名
    assert fake_rf.patched and fake_rf.patched[0]["name"] == "a.txt", fake_rf.patched
    # 新文档最终叫 a.txt, 而且旧的那篇没了
    names = sorted(d["name"] for d in fake_rf.docs)
    assert names == ["a.txt"], names
    assert [d for d in fake_rf.docs if d["id"] == doc_id] == [], "旧文档应该被删了"
    assert new_id != doc_id


async def test_update_with_new_name_keeps_new_name(client, publisher_user, fake_rf):
    """换内容顺便改个名 → 新名字保留 (不跟旧名硬绑)."""
    doc_id = await _upload(client, publisher_user, name="old.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("new.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"]["name"] == "new.txt", r.json()
    assert sorted(d["name"] for d in fake_rf.docs) == ["new.txt"]


# ---------- ④ 归属迁移 ----------

async def test_update_moves_ownership_to_new_document(client, publisher_user, fake_rf):
    """⚠️ 文档 id 变了, 归属也得跟着挪 —— 否则新文档显示「上传者 —」.

    语义跟上传一致: 「**当前这一版**是谁传的」→ 记成这次更新的人.
    """
    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    new_id = r.json()["updated"]["id"]

    r2 = await client.get(
        f"{API}/kb/datasets/ds-naive/documents",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    docs = r2.json()["docs"]
    hit = [x for x in docs if x["id"] == new_id]
    assert hit, r2.text
    assert hit[0]["uploaded_by_name"] == publisher_user["username"], hit[0]
    # 旧文档的归属记录要清掉 (那个 id 已经不存在了)
    old = [x for x in docs if x["id"] == doc_id]
    assert not old, old


async def test_update_records_auditor_as_uploader(client, publisher_user, admin_user, fake_rf):
    """谁更新谁就是当前这一版的上传者."""
    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
    new_id = r.json()["updated"]["id"]
    r2 = await client.get(
        f"{API}/kb/datasets/ds-naive/documents",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    hit = [x for x in r2.json()["docs"] if x["id"] == new_id][0]
    assert hit["uploaded_by_name"] == admin_user["username"], hit


# ---------- ⑤ 解析 ----------

async def test_update_starts_ingest(client, publisher_user, fake_rf):
    """更新完必须重新解析 —— 不解析就不参与检索, 等于没更新."""
    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ingest_started"] is True, r.json()
    assert fake_rf.ingested, fake_rf.ingested


async def test_update_manual_dataset_txt_skips_parse(client, publisher_user, fake_rf):
    """⚠️ 手动分块的数据集只认 pdf/docx —— 传 txt 不能硬发解析 (会 FAIL)."""
    doc_id = await _upload(client, publisher_user, ds_id="ds-manual", name="a.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-manual/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ingest_started"] is False, j
    assert "手动分块" in j["warning"], j
    assert fake_rf.ingested == [], fake_rf.ingested


async def test_update_manual_dataset_pdf_parses(client, publisher_user, fake_rf):
    """手动分块 + pdf → 能解析."""
    doc_id = await _upload(client, publisher_user, ds_id="ds-manual", name="a.pdf")
    r = await client.put(
        f"{API}/kb/datasets/ds-manual/documents/{doc_id}",
        files=_files("a.pdf", content=b"%PDF-1.4"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ingest_started"] is True, r.json()


# ---------- ⑥ 失败要回滚 ----------

async def test_delete_old_failure_rolls_back_new_document(client, publisher_user, fake_rf):
    """⚠️ 删旧文档失败 → 新文档是多余的副本, 必须清掉 (别在库里留垃圾)."""
    doc_id = await _upload(client, publisher_user, name="a.txt")
    fake_rf.fail_delete_ids = {doc_id}
    before = len(fake_rf.docs)
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 502, r.text
    # 回滚: 文档数回到更新前 (旧的在, 新来的被清掉了)
    assert len(fake_rf.docs) == before, fake_rf.docs
    assert [d["name"] for d in fake_rf.docs] == ["a.txt"], fake_rf.docs


async def test_update_is_audited(client, publisher_user, fake_rf):
    """更新要留痕 —— 不留的话没人知道谁把哪篇换掉了."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(KbAudit))).scalars().all()
    hits = [x for x in rows if x.action == "update"]
    assert hits, "更新要写审计"
    assert hits[-1].actor_name == publisher_user["username"]
    assert hits[-1].error == ""
    assert hits[-1].dataset_id == "ds-naive"


async def test_failed_update_is_audited_with_error(client, publisher_user, fake_rf):
    """失败的更新也要留痕 (带 error) —— 否则只看到"少了一篇", 不知道为什么."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    doc_id = await _upload(client, publisher_user, name="a.txt")
    fake_rf.fail_delete_ids = {doc_id}
    r = await client.put(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}",
        files=_files("a.txt", content="新内容".encode()),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 502, r.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(KbAudit))).scalars().all()
    hits = [x for x in rows if x.action == "update"]
    assert hits, "失败的更新也要写审计"
    assert hits[-1].error, "失败要带 error"


# ---------- ⑦ 重新解析 ----------

async def test_tester_can_reparse(client, publisher_user, fake_rf):
    """重解析不删数据 —— 跟更新同一档 (tester 及以上)."""
    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.post(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}/reparse",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert fake_rf.parsed == [[doc_id]], fake_rf.parsed


async def test_viewer_cannot_reparse(client, stranger_user, fake_rf):
    """viewer 是只读角色."""
    r = await client.post(
        f"{API}/kb/datasets/ds-naive/documents/doc-1/reparse",
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 403, r.text


async def test_reparse_missing_document_returns_404(client, publisher_user, fake_rf):
    """重解析一个不存在的文档 → 404."""
    r = await client.post(
        f"{API}/kb/datasets/ds-naive/documents/doc-nope/reparse",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 404, r.text
    assert fake_rf.parsed == []


async def test_reparse_is_audited(client, publisher_user, fake_rf):
    """重解析也要留痕."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.post(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}/reparse",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(KbAudit))).scalars().all()
    hits = [x for x in rows if x.action == "reparse"]
    assert hits, "重解析要写审计"
    assert hits[-1].actor_name == publisher_user["username"]
    assert hits[-1].document_id == doc_id


async def test_reparse_failure_returns_502(client, publisher_user, fake_rf):
    """RAGFlow 报错 → 502 (服务端故障, 不是用户的错)."""
    fake_rf.fail_parse = True
    doc_id = await _upload(client, publisher_user, name="a.txt")
    r = await client.post(
        f"{API}/kb/datasets/ds-naive/documents/{doc_id}/reparse",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 502, r.text
    assert "ragflow" in r.json()["detail"], r.text
