"""知识库上传 / 下载 / 审计 (2026-10-29).

背景:
    知识库的内容**存在 RAGFlow 里**. 这次开放了**普通登录用户上传**的权限
    (以前只有 admin 能动知识库), 所以要锁住三件事:
      ① 谁能上传 —— tester 及以上, **viewer 是只读角色**;
      ② 谁能下载 —— 所有登录用户 (下载是只读操作);
      ③ **谁都不能删** —— 删除仍然只有 admin.

⚠️ 这里的 RAGFlow 全是**假的** (monkeypatch) —— 单测不碰真的 RAGFlow,
   更不碰真的知识库.
"""
from __future__ import annotations

import io

import pytest

API = "/api/v1"


# ---------- 假的 RAGFlow ----------

class FakeRagflow:
    """记录调用, 返回可预期的结果."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, list[tuple[str, bytes, str]]]] = []
        self.ingests: list[list[str]] = []
        self.created: list[dict] = []

    async def upload_documents(self, dataset_id, files):
        self.uploads.append((dataset_id, files))
        out = []
        for name, data, _ctype in files:
            doc = {
                "id": f"doc-{len(self.created)}",
                "name": name,
                "size": len(data),
                "location": name,
                "run": "UNSTART",
            }
            self.created.append(doc)
            out.append(doc)
        return out

    async def ingest_documents(self, doc_ids, run="1", delete=False):
        self.ingests.append(list(doc_ids))
        return True

    async def list_datasets(self, page=1, page_size=50):
        return [{"id": "ds-1", "name": "协议文档"}]

    async def download_document(self, dataset_id, document_id):
        return b"hello from ragflow", "note.txt", "text/plain; charset=utf-8"


@pytest.fixture
def fake_rf(monkeypatch):
    """把 kb 模块里的 RAGFlow 调用全换成假的."""
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "upload_documents", rf.upload_documents)
    monkeypatch.setattr(kb_mod, "ingest_documents", rf.ingest_documents)
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    monkeypatch.setattr(kb_mod, "download_document", rf.download_document)
    return rf


def _files(*names: str):
    """造 multipart 文件列表."""
    return [
        ("file", (n, io.BytesIO(f"内容-{n}".encode()), "text/plain")) for n in names
    ]


# ---------- ① 权限: 谁能上传 ----------

async def test_tester_can_upload(client, publisher_user, fake_rf):
    """tester 能上传 —— 并且上传后**自动发起解析** (不解析就不参与检索)."""
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["uploaded"] == 1
    assert j["ingest_started"] is True
    # ⚠️ 必须有 ingest —— 否则文档永远停在 UNSTART, 检索不到
    assert fake_rf.ingests == [["doc-0"]], fake_rf.ingests


async def test_viewer_cannot_upload(client, stranger_user, fake_rf):
    """viewer 是**只读**角色 —— 不能往共享知识库里塞东西."""
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 403, r.text
    assert fake_rf.uploads == [], "viewer 不该能上传"


async def test_upload_requires_login(client, fake_rf):
    """没登录不能上传."""
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents", files=_files("a.txt"),
    )
    assert r.status_code == 401, r.text


async def test_admin_can_upload(client, admin_user, fake_rf):
    """admin 当然能上传."""
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text


# ---------- ② 数量 / 大小限制 ----------

async def test_upload_rejects_too_many_files(client, publisher_user, fake_rf):
    """单次最多 5 个文件."""
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=_files("a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "f.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 422, r.text
    assert "5" in r.json()["detail"], r.text
    assert fake_rf.uploads == []


async def test_upload_rejects_oversized_file(client, publisher_user, fake_rf):
    """单文件超 20MB → 413 (不能先把文件全吃进内存再判断)."""
    import app.api.kb as kb_mod

    big = b"x" * (kb_mod.MAX_UPLOAD_BYTES + 1024)
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=[("file", ("big.bin", io.BytesIO(big), "application/octet-stream"))],
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 413, r.text
    assert fake_rf.uploads == []


async def test_upload_rejects_empty_file_list(client, publisher_user, fake_rf):
    """一个文件都没选 → 422."""
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=[],
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code in (422, 400), r.text


# ---------- ③ 文件名安全 ----------

async def test_upload_sanitizes_file_name(client, publisher_user, fake_rf):
    """文件名里的路径要洗掉 —— 它会变成 RAGFlow 里的 location."""
    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=[("file", ("../../etc/passwd", io.BytesIO(b"x"), "text/plain"))],
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    _ds, files = fake_rf.uploads[0]
    name = files[0][0]
    assert "/" not in name and ".." not in name, name


# ---------- ④ 下载: 所有登录用户都能 ----------

async def test_viewer_can_download(client, stranger_user, fake_rf):
    """下载是**只读**操作 → viewer 也能下."""
    r = await client.get(
        f"{API}/kb/datasets/ds-1/documents/doc-1/download",
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.content == b"hello from ragflow"
    assert "attachment" in r.headers.get("content-disposition", "")


async def test_download_requires_login(client, fake_rf):
    """没登录不能下载."""
    r = await client.get(f"{API}/kb/datasets/ds-1/documents/doc-1/download")
    assert r.status_code == 401, r.text


async def test_download_returns_raw_bytes_not_json(client, admin_user, fake_rf):
    """⚠️ RAGFlow 这个接口返回的是**文件字节流** —— 不能包成 JSON."""
    r = await client.get(
        f"{API}/kb/datasets/ds-1/documents/doc-1/download",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.content == b"hello from ragflow"
    assert "application/json" not in r.headers.get("content-type", "")


# ---------- ⑤ 删除仍然只有 admin ----------

async def test_only_admin_can_delete_documents(client, publisher_user, stranger_user, admin_user):
    """⚠️ 上传开放了, **删除不能跟着开放** —— 能删就意味着能把别人的东西删掉."""
    for who in (publisher_user, stranger_user):
        r = await client.request(
            "DELETE", f"{API}/kb/datasets/ds-1/documents",
            json={"ids": ["doc-1"]},
            headers={"Authorization": f"Bearer {who['token']}"},
        )
        assert r.status_code == 403, f"{who['username']} 不该能删: {r.text}"


# ---------- ⑥ 审计留痕 ----------

async def test_upload_is_audited(client, publisher_user, fake_rf):
    """上传要留痕 —— RAGFlow 记不了 TestMate 的账号 (所有人共用一把 API key)."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(KbAudit))).scalars().all()
    assert rows, "上传应该留审计"
    row = rows[-1]
    assert row.action == "upload"
    assert row.actor_name == publisher_user["username"]
    assert row.document_id == "doc-0"
    assert row.dataset_id == "ds-1"
    assert row.error == ""


async def test_audit_endpoint_lists_records(client, publisher_user, fake_rf):
    """审计列表能读到."""
    await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    r = await client.get(
        f"{API}/kb/audits",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, r.text
    assert items[0]["action"] == "upload"
    assert items[0]["actor_name"] == publisher_user["username"]
    # ⚠️ 时间戳要带 Z (后端统一 UTC 契约) —— 前端按本地时区显示
    assert items[0]["created_at"].endswith("Z"), items[0]


async def test_failed_upload_is_audited(client, publisher_user, monkeypatch):
    """上传失败也要留痕 (不然有人传失败了就没人知道发生过)."""
    import app.api.kb as kb_mod
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    async def _boom(dataset_id, files):
        raise RuntimeError("ragflow 炸了")

    monkeypatch.setattr(kb_mod, "upload_documents", _boom)

    r = await client.post(
        f"{API}/kb/datasets/ds-1/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 502, r.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(KbAudit))).scalars().all()
    assert rows, "失败也要留痕"
    assert rows[-1].error, "失败原因要记下来"
