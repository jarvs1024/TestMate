"""知识库归属 + 删除数据集 (2026-10-29 第三轮).

背景:
    ① **谁建的库 / 谁传的文档** —— RAGFlow 记不了 TestMate 的账号:
       它的 `created_by` 指的是 RAGFlow 用户, 而 TestMate 的所有登录用户共用
       **同一把 API key**. 所以归属只能存在 TestMate 自己的两张新表里
       (`kb_dataset_meta` / `kb_document_meta`).
    ② **删除数据集** —— 以前只有「删除文档」(admin only), 库建错了删不掉.
       现在补上, 门槛跟删文档一样: **admin only**; 而且前端还要**输入库名**确认
       (RAGFlow 的删除是硬删, 没有回收站).

⚠️ 这里的 RAGFlow 全是**假的** (monkeypatch) —— 单测不碰真的 RAGFlow.
"""
from __future__ import annotations

import io

import pytest

API = "/api/v1"


# ---------- 假的 RAGFlow ----------

class FakeRagflow:
    def __init__(self) -> None:
        #: dataset_id → dataset dict
        self.datasets: dict[str, dict] = {
            "ds-legacy": {
                "id": "ds-legacy", "name": "协议文档", "description": "",
                "chunk_method": "manual", "embedding_model": "emb",
                "permission": "me", "document_count": 5, "chunk_count": 796,
            },
        }
        self.docs: list[dict] = []
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.fail_delete = False

    async def list_datasets(self, page=1, page_size=50):
        return list(self.datasets.values())

    async def create_dataset(self, name, description="", chunk_method="naive",
                             embedding_model="", permission="me"):
        did = f"ds-new-{len(self.created) + 1}"
        ds = {
            "id": did, "name": name, "description": description,
            "chunk_method": chunk_method, "embedding_model": embedding_model,
            "permission": permission, "document_count": 0, "chunk_count": 0,
        }
        self.created.append(ds)
        self.datasets[did] = ds
        return ds

    async def upload_documents(self, dataset_id, files):
        out = []
        for name, data, _ctype in files:
            doc = {
                "id": f"doc-{len(self.docs) + 1}",
                "name": name,
                "size": len(data),
                "location": name,
                "run": "UNSTART",
                "_ds": dataset_id,
            }
            self.docs.append(doc)
            out.append(doc)
        return out

    async def ingest_documents(self, doc_ids, run="1", delete=False):
        return True

    async def list_documents(self, dataset_id, page=1, page_size=30,
                             orderby="create_time", desc=True, keywords="", run=""):
        # ⚠️ 这个**必须**打桩 —— 不打的话会走真的 RAGFlow, 拿到的是线上真库的文档,
        #    跟这里 fake 出来的 doc id 对不上, 断言就成了"查无此文"
        docs = [d for d in self.docs if d.get("_ds") == dataset_id]
        return {"docs": docs, "total": len(docs)}

    async def delete_dataset(self, dataset_id):
        if self.fail_delete:
            raise RuntimeError("ragflow 炸了")
        self.deleted.append(dataset_id)
        self.datasets.pop(dataset_id, None)
        return True


@pytest.fixture
def fake_rf(monkeypatch):
    """把 kb 模块里的 RAGFlow 调用全换成假的."""
    import app.api.kb as kb_mod

    rf = FakeRagflow()
    monkeypatch.setattr(kb_mod, "create_dataset", rf.create_dataset)
    monkeypatch.setattr(kb_mod, "list_datasets", rf.list_datasets)
    monkeypatch.setattr(kb_mod, "upload_documents", rf.upload_documents)
    monkeypatch.setattr(kb_mod, "ingest_documents", rf.ingest_documents)
    monkeypatch.setattr(kb_mod, "list_documents", rf.list_documents)
    monkeypatch.setattr(kb_mod, "delete_dataset", rf.delete_dataset)
    return rf


def _files(*names: str):
    return [
        ("file", (n, io.BytesIO(f"内容-{n}".encode()), "text/plain")) for n in names
    ]


# ---------- ① 归属: 数据集谁建的 ----------

async def test_create_dataset_records_owner(client, publisher_user, fake_rf):
    """建库要记下「谁建的」—— RAGFlow 那边记不了 TestMate 的账号."""
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "项目管理"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    ds_id = r.json()["dataset"]["id"]

    r2 = await client.get(
        f"{API}/kb/datasets",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    items = r2.json()["items"]
    hit = [x for x in items if x["id"] == ds_id]
    assert hit, r2.text
    assert hit[0]["created_by_name"] == publisher_user["username"], hit[0]
    assert hit[0]["created_by"] == publisher_user["id"], hit[0]


async def test_legacy_dataset_has_no_owner(client, publisher_user, fake_rf):
    """⚠️ 建库功能上线**之前**手工建的库没有归属记录 —— 显示「—」, 不瞎猜."""
    r = await client.get(
        f"{API}/kb/datasets",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    hit = [x for x in r.json()["items"] if x["id"] == "ds-legacy"]
    assert hit, r.text
    assert hit[0]["created_by_name"] == "", hit[0]
    assert not hit[0]["created_at"], hit[0]


async def test_owner_created_at_is_utc_with_z(client, publisher_user, fake_rf):
    """⚠️ 时间戳必须带 `Z` —— 这个接口返回 plain dict, 走不到 UTCModel 序列化器.

    不加 Z 的话前端会按本地时区解析, 显示差 8 小时.
    """
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "带时间的库"},
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    ds_id = r.json()["dataset"]["id"]

    r2 = await client.get(
        f"{API}/kb/datasets",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    hit = [x for x in r2.json()["items"] if x["id"] == ds_id][0]
    assert hit["created_at"].endswith("Z"), hit["created_at"]


# ---------- ② 归属: 文档谁传的 ----------

async def test_upload_records_document_owner(client, publisher_user, fake_rf):
    """上传要记下「谁传的」."""
    r = await client.post(
        f"{API}/kb/datasets/ds-legacy/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["docs"][0]["id"]

    r2 = await client.get(
        f"{API}/kb/datasets/ds-legacy/documents",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    hit = [x for x in r2.json()["docs"] if x["id"] == doc_id]
    assert hit, r2.text
    assert hit[0]["uploaded_by_name"] == publisher_user["username"], hit[0]
    assert hit[0]["uploaded_at"].endswith("Z"), hit[0]


async def test_reupload_same_name_is_a_new_document(client, publisher_user, fake_rf, admin_user):
    """⚠️ 同名重传在 RAGFlow 里是**新文档**(新 id) —— 所以是两条独立的归属.

    归属表按 `document_id` 存 (一个文档一行), 重传不会覆盖前一个文档的归属.
    """
    r = await client.post(
        f"{API}/kb/datasets/ds-legacy/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 200, r.text
    first_id = r.json()["docs"][0]["id"]

    r2 = await client.post(
        f"{API}/kb/datasets/ds-legacy/documents",
        files=_files("a.txt"),
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r2.status_code == 200, r2.text
    second_id = r2.json()["docs"][0]["id"]
    assert first_id != second_id, "同名重传应该是新文档"

    r3 = await client.get(
        f"{API}/kb/datasets/ds-legacy/documents",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    docs = r3.json()["docs"]
    first = [x for x in docs if x["id"] == first_id][0]
    second = [x for x in docs if x["id"] == second_id][0]
    assert first["uploaded_by_name"] == publisher_user["username"], first
    assert second["uploaded_by_name"] == admin_user["username"], second


# ---------- ③ 删除数据集: admin only ----------

async def test_only_admin_can_delete_dataset(client, publisher_user, stranger_user, fake_rf):
    """⚠️ 删除数据集是**硬删** —— 门槛必须跟删文档一样, 只有 admin."""
    for who in (publisher_user, stranger_user):
        r = await client.request(
            "DELETE", f"{API}/kb/datasets/ds-legacy",
            headers={"Authorization": f"Bearer {who['token']}"},
        )
        assert r.status_code == 403, f"{who['username']} 不该能删: {r.text}"
    assert fake_rf.deleted == [], fake_rf.deleted


async def test_admin_can_delete_dataset(client, admin_user, fake_rf):
    """admin 能删, 并且把删掉的规模报回去 (前端要用来写确认文案)."""
    r = await client.request(
        "DELETE", f"{API}/kb/datasets/ds-legacy",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["deleted"]["name"] == "协议文档", j
    assert j["deleted"]["documents"] == 5, j
    assert j["deleted"]["chunks"] == 796, j
    assert fake_rf.deleted == ["ds-legacy"], fake_rf.deleted


async def test_delete_missing_dataset_returns_404(client, admin_user, fake_rf):
    """删一个不存在的库 → 404, 别去调 RAGFlow 删空气."""
    r = await client.request(
        "DELETE", f"{API}/kb/datasets/ds-nope",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 404, r.text
    assert fake_rf.deleted == []


async def test_delete_dataset_failure_returns_502(client, admin_user, fake_rf):
    """RAGFlow 报错 → 502 (是服务端故障, 不是用户的错)."""
    fake_rf.fail_delete = True
    r = await client.request(
        "DELETE", f"{API}/kb/datasets/ds-legacy",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 502, r.text
    assert "ragflow" in r.json()["detail"], r.text


async def test_delete_dataset_is_audited(client, admin_user, fake_rf):
    """删库要留痕 —— 不留的话没人知道谁把哪个库干掉了."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    r = await client.request(
        "DELETE", f"{API}/kb/datasets/ds-legacy",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(KbAudit))).scalars().all()
    hits = [x for x in rows if x.action == "delete" and x.dataset_id == "ds-legacy"]
    assert hits, "删库要写审计"
    assert hits[-1].actor_name == admin_user["username"]
    assert hits[-1].error == ""


async def test_delete_dataset_clears_ownership(client, admin_user, fake_rf):
    """库没了, 归属记录也得没 —— 否则详情页会指向一个不存在的库."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbDatasetMeta

    # 先建一个库 (有归属记录)
    r = await client.post(
        f"{API}/kb/datasets",
        json={"name": "待删的库"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    ds_id = r.json()["dataset"]["id"]

    async with AsyncSessionLocal() as s:
        before = (await s.execute(
            select(KbDatasetMeta).where(KbDatasetMeta.dataset_id == ds_id)
        )).scalars().all()
    assert before, "建库要写归属"

    r2 = await client.request(
        "DELETE", f"{API}/kb/datasets/{ds_id}",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r2.status_code == 200, r2.text

    async with AsyncSessionLocal() as s:
        after = (await s.execute(
            select(KbDatasetMeta).where(KbDatasetMeta.dataset_id == ds_id)
        )).scalars().all()
    assert not after, "库删了, 归属记录也要清掉"


# ---------- ④ 操作记录收紧到 admin only ----------

async def test_viewer_cannot_read_audits(client, stranger_user, fake_rf):
    """⚠️ 操作记录里有别人的**操作人账号和文件名** —— viewer 不该看到.

    以前是所有登录用户都能看 (共享知识库要透明), 2026-10-29 收紧到
    **admin only** (跟删除文档/删除数据集同一档).
    """
    r = await client.get(
        f"{API}/kb/audits",
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 403, r.text


async def test_tester_cannot_read_audits(client, publisher_user, fake_rf):
    """⚠️ tester 也不能看 —— 能上传 ≠ 能看治理信息.

    跟删除文档/删除数据集一个口径: **破坏性和治理性的操作都归 admin**.
    """
    r = await client.get(
        f"{API}/kb/audits",
        headers={"Authorization": f"Bearer {publisher_user['token']}"},
    )
    assert r.status_code == 403, r.text


async def test_admin_can_read_audits(client, admin_user, fake_rf):
    """admin 能看."""
    r = await client.get(
        f"{API}/kb/audits",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 200, r.text
