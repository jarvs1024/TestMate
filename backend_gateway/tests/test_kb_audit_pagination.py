"""知识库操作记录 **分页** (2026-10-29 第六轮).

背景:
    审计流水 (`kb_audits`) 是**只增不减**的事件流水 —— 每一篇文档的上传/更新/
    重解析/删除都会留一行. 以前接口只有 `limit` (最多 50 条), 一次拉回来就那么多,
    后面发生的操作**在页面上根本看不见**, 越用越查不出问题.

    这一轮把接口改成 `page` / `page_size` + **真实总数**, 前端加翻页控件.

⚠️ 重点测的是那些**容易做错**的地方:
    · `total` 必须是**真实总条数** —— 以前返回的是"本页有几条" (len(rows)),
      跟翻页控件对不上 (第 2 页还显示"共 20 条");
    · **页码越界** (删过数据 / 前端还停在旧页码) 不能返回一个空表 + 一个
      看着很正常的"共 N 条";
    · 老的 `?limit=N` 调用方式**不能坏** —— 一堆存量脚本还在用它.
"""
from __future__ import annotations

API = "/api/v1"


# ---------- 造审计流水 ----------

async def _seed(client, admin_token: str, n: int) -> list[int]:
    """直接往审计表里灌 n 行, 返回它们的 id (按写入顺序)."""
    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    ids: list[int] = []
    async with AsyncSessionLocal() as s:
        for i in range(n):
            row = KbAudit(
                dataset_id="ds-pg",
                dataset_name="分页测试库",
                document_id=f"doc-pg-{i}",
                doc_name=f"分页测试-{i}.txt",
                action="upload",
                actor_name="admin",
                error="",
                size=100 + i,
            )
            s.add(row)
            await s.flush()
            ids.append(row.id)
        await s.commit()
    return ids


async def _clear(client) -> None:
    from sqlalchemy import delete

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    async with AsyncSessionLocal() as s:
        await s.execute(delete(KbAudit).where(KbAudit.dataset_id == "ds-pg"))
        await s.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------- ① 基本分页 ----------

async def test_audits_paginate_basic(client, admin_user):
    """第 1 页 / 第 2 页 各返回各自的条数, 且**不重复**."""
    await _clear(client)
    ids = await _seed(client, admin_user["token"], 25)

    r1 = await client.get(
        f"{API}/kb/audits?page=1&page_size=10", headers=_auth(admin_user["token"])
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert len(b1["items"]) == 10, b1
    assert b1["page"] == 1, b1
    assert b1["page_size"] == 10, b1

    r2 = await client.get(
        f"{API}/kb/audits?page=2&page_size=10", headers=_auth(admin_user["token"])
    )
    b2 = r2.json()
    assert len(b2["items"]) == 10, b2
    assert b2["page"] == 2, b2

    # ⚠️ 两页不能有交集 —— offset 算错了就会重复
    id1 = {x["id"] for x in b1["items"]}
    id2 = {x["id"] for x in b2["items"]}
    assert not (id1 & id2), f"两页重了: {id1 & id2}"

    # ⚠️ 最新的排最前 (按 id 倒序)
    assert b1["items"][0]["id"] == max(ids), b1["items"][0]
    await _clear(client)


async def test_audits_total_is_real_count(client, admin_user):
    """⚠️ `total` 必须是**真实总条数**, 不是"本页有几条".

    以前返回 `len(rows)` —— 翻到第 2 页还是显示"共 10 条", 跟实际对不上.
    """
    await _clear(client)
    await _seed(client, admin_user["token"], 25)

    r = await client.get(
        f"{API}/kb/audits?page=2&page_size=10", headers=_auth(admin_user["token"])
    )
    b = r.json()
    assert b["total"] == 25, b
    assert b["pages"] == 3, b
    # 第 2 页只有 10 条, 但 total 必须是 25
    assert len(b["items"]) == 10, b
    await _clear(client)


async def test_audits_last_page_is_partial(client, admin_user):
    """最后一页不满 —— 条数按实际给, pages 向上取整."""
    await _clear(client)
    await _seed(client, admin_user["token"], 25)

    r = await client.get(
        f"{API}/kb/audits?page=3&page_size=10", headers=_auth(admin_user["token"])
    )
    b = r.json()
    assert len(b["items"]) == 5, b
    assert b["pages"] == 3, b
    await _clear(client)


# ---------- ② 边界 ----------

async def test_audits_page_out_of_range_clamps(client, admin_user):
    """⚠️ 页码越界 → 回到最后一页, **不是**空表 + 一个看着正常的 total.

    场景: 用户停在第 5 页, 别人把记录删了 → 第 5 页空了.
    这时候返回空表 + "共 12 条" 用户会以为记录没了.
    """
    await _clear(client)
    await _seed(client, admin_user["token"], 12)

    r = await client.get(
        f"{API}/kb/audits?page=99&page_size=10", headers=_auth(admin_user["token"])
    )
    b = r.json()
    assert b["page"] == 2, b
    assert b["pages"] == 2, b
    assert b["items"], "越界页码应该落到最后一页, 而不是空表"
    await _clear(client)


async def test_audits_empty_table(client, admin_user):
    """一条都没有 → total=0, pages=1 (不是 0 —— 页数至少得有一页)."""
    await _clear(client)
    r = await client.get(
        f"{API}/kb/audits?page=1&page_size=10", headers=_auth(admin_user["token"])
    )
    b = r.json()
    assert b["total"] == 0, b
    assert b["pages"] == 1, b
    assert b["items"] == [], b


async def test_audits_page_size_capped(client, admin_user):
    """page_size 有上限 —— 别让人一次拉 10 万条把服务拖死."""
    await _clear(client)
    r = await client.get(
        f"{API}/kb/audits?page=1&page_size=99999", headers=_auth(admin_user["token"])
    )
    b = r.json()
    assert b["page_size"] == 200, b


async def test_audits_page_size_min_one(client, admin_user):
    """page_size 传 0 / 负数 → 兜到 1, 不能整页不给东西."""
    await _clear(client)
    await _seed(client, admin_user["token"], 2)
    r = await client.get(
        f"{API}/kb/audits?page=1&page_size=0", headers=_auth(admin_user["token"])
    )
    b = r.json()
    assert b["page_size"] == 1, b
    assert len(b["items"]) == 1, b
    await _clear(client)


# ---------- ③ 向后兼容 ----------

async def test_audits_limit_alias_still_works(client, admin_user):
    """⚠️ `?limit=N` 还在用 (一堆存量脚本) —— 不能因为加了分页就把它弄坏.

    传了 limit 就当 page_size 用, 还是返回第一页.
    """
    await _clear(client)
    await _seed(client, admin_user["token"], 5)

    r = await client.get(
        f"{API}/kb/audits?limit=3", headers=_auth(admin_user["token"])
    )
    b = r.json()
    assert r.status_code == 200, r.text
    assert len(b["items"]) == 3, b
    assert b["page"] == 1, b
    assert b["page_size"] == 3, b
    assert b["total"] == 5, b
    await _clear(client)


async def test_audits_default_params(client, admin_user):
    """不传任何参数 → 默认第一页, 20 条."""
    await _clear(client)
    await _seed(client, admin_user["token"], 3)
    r = await client.get(f"{API}/kb/audits", headers=_auth(admin_user["token"]))
    b = r.json()
    assert b["page"] == 1, b
    assert b["page_size"] == 20, b
    assert len(b["items"]) == 3, b
    await _clear(client)


# ---------- ④ 权限不变 ----------

async def test_audits_pagination_still_admin_only(client, publisher_user, stranger_user):
    """⚠️ 加了分页**不等于**放宽权限 —— 翻页也是 admin only."""
    for tok in (publisher_user["token"], stranger_user["token"]):
        r = await client.get(
            f"{API}/kb/audits?page=1&page_size=10", headers=_auth(tok)
        )
        assert r.status_code == 403, r.text


# ---------- ⑤ 字段完整性 ----------

async def test_audits_page_items_keep_fields(client, admin_user):
    """分页后的每一行, 字段一个都不能少 (前端要显示时间/谁/数据集/大小)."""
    await _clear(client)
    await _seed(client, admin_user["token"], 1)
    r = await client.get(
        f"{API}/kb/audits?page=1&page_size=1", headers=_auth(admin_user["token"])
    )
    item = r.json()["items"][0]
    for k in ("id", "dataset_id", "dataset_name", "document_id", "doc_name",
              "action", "actor_name", "error", "size", "created_at"):
        assert k in item, f"少了字段 {k}: {item}"
    # ⚠️ 时间戳要带 Z (后端统一 UTC 契约)
    assert item["created_at"].endswith("Z"), item
    await _clear(client)
