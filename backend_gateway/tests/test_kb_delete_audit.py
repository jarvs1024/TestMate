"""删除文档**要留审计** (2026-10-30 · 第九轮).

背景:
    知识库页面把「操作记录」定位成**唯一的治理台账** —— 谁传的、谁删的,
    只能靠这张表 (RAGFlow 记不了 TestMate 的账号, 所有人共用一把 API key).

⚠️ **以前删文档不写审计** —— `delete_docs` 删完直接 `return {"ok": ok}`,
   操作记录里**查无此事**. admin 事后根本查不出"这篇文档是谁删的".
   这轮补上, 并且:

    ① action 用 **delete_doc** (不是 delete) ——
       `delete` 已经被「删除数据集」占着, 混用的话 admin 分不清删的是库还是文档;
    ② 审计里要写清楚**删的是哪几篇文档的名字** (删完就查不到了);
    ③ 删除**失败**也要留痕 (error 字段), 跟上传/更新一个口径.

⚠️ 这里的 RAGFlow 全是**假的** (monkeypatch) —— 单测不碰真的 RAGFlow.
"""
from __future__ import annotations

import pytest

API = "/api/v1"


class FakeRagflow:
    """记录调用, 返回可预期的结果."""

    def __init__(self) -> None:
        self.deleted: list[tuple[str, list[str] | None, bool]] = []
        self.fail = False

    async def list_datasets(self, page=1, page_size=50):
        return [
            {"id": "ds-1", "name": "协议文档", "chunk_method": "naive",
             "document_count": 2, "chunk_count": 30},
        ]

    async def list_documents(self, dataset_id, page=1, page_size=30, **kw):
        return {
            "docs": [
                {"id": "doc-1", "name": "接口规范.pdf", "size": 100},
                {"id": "doc-2", "name": "保密协议.docx", "size": 200},
            ],
            "total": 2,
        }

    async def delete_documents(self, dataset_id, doc_ids=None, delete_all=False):
        if self.fail:
            raise RuntimeError("ragflow 炸了")
        self.deleted.append((dataset_id, list(doc_ids) if doc_ids else None, delete_all))
        return True


@pytest.fixture
def fake_rf(monkeypatch):
    """把 kb 模块里的 RAGFlow 调用全换成假的."""
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    monkeypatch.setattr(kb_mod, "list_documents", rf.list_documents)
    monkeypatch.setattr(kb_mod, "delete_documents", rf.delete_documents)
    return rf


async def _audit_rows():
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    async with AsyncSessionLocal() as s:
        return (await s.execute(select(KbAudit).order_by(KbAudit.id))).scalars().all()


# ---------- 正常路径 ----------

async def test_delete_document_is_audited(client, admin_user, fake_rf):
    """⚠️ 删文档**必须**留审计 —— 这是知识库唯一的治理台账."""
    r = await client.request(
        "DELETE",
        f"{API}/kb/datasets/ds-1/documents",
        json={"ids": ["doc-1"], "delete_all": False},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    rows = await _audit_rows()
    assert rows, "删文档应该留审计"
    row = rows[-1]
    # ⚠️ action 必须是 delete_doc —— delete 是「删除数据集」, 混用 admin 分不清
    assert row.action == "delete_doc", f"action={row.action!r}"
    assert row.actor_name == admin_user["username"]
    assert row.dataset_id == "ds-1"
    assert row.dataset_name == "协议文档"
    # ⚠️ 文档名要写进去 —— 删完就查不到了, 事后没人知道删的是哪几篇
    assert "接口规范.pdf" in row.doc_name, row.doc_name
    assert row.error == ""


async def test_delete_all_documents_also_audited(client, admin_user, fake_rf):
    """delete_all 也得留痕 —— 而且要把所有文档名写上."""
    r = await client.request(
        "DELETE",
        f"{API}/kb/datasets/ds-1/documents",
        json={"ids": None, "delete_all": True},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
    row = (await _audit_rows())[-1]
    assert row.action == "delete_doc"
    assert "接口规范.pdf" in row.doc_name
    assert "保密协议.docx" in row.doc_name


async def test_failed_delete_is_audited(client, admin_user, fake_rf):
    """⚠️ 删除**失败**也要留痕 (带 error) —— 跟上传/更新一个口径."""
    fake_rf.fail = True
    r = await client.request(
        "DELETE",
        f"{API}/kb/datasets/ds-1/documents",
        json={"ids": ["doc-1"], "delete_all": False},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 502, r.text

    rows = await _audit_rows()
    assert rows, "删除失败也要留审计"
    row = rows[-1]
    assert row.action == "delete_doc"
    assert row.error, "失败记录里应该有 error"


# ---------- 权限不变 ----------

async def test_tester_cannot_delete_documents(client, publisher_user, fake_rf):
    """tester 不能删 —— 硬删仍然只有 admin."""
    before = len(await _audit_rows())
    r = await client.request(
        "DELETE",
        f"{API}/kb/datasets/ds-1/documents",
        json={"ids": ["doc-1"], "delete_all": False},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 403, r.text
    assert fake_rf.deleted == []
    # ⚠️ 比"条数"而不是"有没有" —— kb_audits 不在 conftest 的清理清单里,
    #    同一个库里可能残留上一个用例写的行
    assert len(await _audit_rows()) == before, "被拒的请求不该留审计"


async def test_delete_document_requires_login(client, fake_rf):
    """没登录不能删."""
    r = await client.request(
        "DELETE",
        f"{API}/kb/datasets/ds-1/documents",
        json={"ids": ["doc-1"], "delete_all": False},
    )
    assert r.status_code == 401, r.text
    assert fake_rf.deleted == []
