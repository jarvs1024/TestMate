"""第二十轮 —— 分类 chip 的计数**恒定** (2026-10-31).

用户报的毛病:

> 「选中流程规范或者其他，质量保障，效率工具都没数字显示了，其他类似」

**根因**: 分类 chip 上的数字以前是**前端按当前列表聚合**的 ——
选了某个分类 → 列表里只剩那一类 → 别的分类全被算成 0 → 再被模板里的 `v-if` 藏掉
→ **别的分类的数字全消失**。

**改法**: 计数下沉到后端 (`AssetListOut.cat_counts`), 口径跟 `all_total` **完全一致**
(kind + q + project + 可见性, **忽略 category**)。

盯住这几件事:
  ① 各分类之和 == all_total (不变量);
  ② 选 category 筛选时, cat_counts **不变** (这正是原来那个 bug);
  ③ cat_counts 跟着 kind / q 走 (换作用域时该变);
  ④ 作用域里没有资产的分类**不在 map 里** → 前端显示 0 (不是"没统计")。
"""
from __future__ import annotations

from app.db.session import AsyncSessionLocal
from app.models.asset import Asset


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user['token']}"}


async def _seed_asset(code: str, *, author: str, category: str = "", kind: str = "skill",
                      publish_status: str = "published", summary: str = "") -> None:
    async with AsyncSessionLocal() as s:
        s.add(
            Asset(
                code=code,
                name=code,
                icon="🧩",
                kind=kind,
                version="1.0.0",
                summary=summary,
                description="",
                use_when="",
                not_for="",
                category=category,
                project="",
                tags=[],
                keywords=[],
                permissions={},
                install_steps=[],
                bindings={},
                author=author,
                featured=False,
                publish_status=publish_status,
                sync_status="pushed",
                git_path=f"assets/connectors/misc/{code}",
                mcp_config={"mcpServers": {code: {"url": "http://x/mcp"}}},
            )
        )
        await s.commit()


async def test_cat_counts_sum_equals_all_total(client, admin_user):
    """① 不变量: 各分类之和 == all_total (同一作用域, 只是按 category 分桶)."""
    me = admin_user["username"]
    await _seed_asset("cc-1", author=me, category="质量保障")
    await _seed_asset("cc-2", author=me, category="质量保障")
    await _seed_asset("cc-3", author=me, category="效率工具")

    r = await client.get("/api/v1/extensions", headers=_auth(admin_user))
    body = r.json()
    counts = body["cat_counts"]
    assert counts.get("质量保障") == 2
    assert counts.get("效率工具") == 1
    assert sum(counts.values()) == body["all_total"]


async def test_cat_counts_do_not_change_when_category_selected(client, admin_user):
    """② ⚠️ 这就是原来那个 bug: 选了分类之后, **别的分类的计数不许变**."""
    me = admin_user["username"]
    await _seed_asset("cc-a", author=me, category="质量保障")
    await _seed_asset("cc-b", author=me, category="效率工具")
    await _seed_asset("cc-c", author=me, category="效率工具")

    r0 = await client.get("/api/v1/extensions", headers=_auth(admin_user))
    before = r0.json()["cat_counts"]
    assert before.get("质量保障") == 1
    assert before.get("效率工具") == 2

    # 选「质量保障」→ 列表只剩 1 条, 但 cat_counts 必须**原样不动**
    r1 = await client.get(
        "/api/v1/extensions", params={"category": "质量保障"}, headers=_auth(admin_user)
    )
    body1 = r1.json()
    assert body1["total"] == 1, "列表本身应该只剩这一类"
    assert body1["cat_counts"] == before, "⚠️ 分类计数不能跟着分类筛选变"
    assert body1["cat_counts"].get("效率工具") == 2


async def test_cat_counts_follow_kind_scope(client, admin_user):
    """③ kind 是**当前作用域** —— 计数要跟着它走 (跟 all_total 同理)."""
    me = admin_user["username"]
    await _seed_asset("cc-sk", author=me, category="质量保障", kind="skill")
    await _seed_asset("cc-pl", author=me, category="质量保障", kind="plugin")

    r = await client.get("/api/v1/extensions", params={"kind": "skill"}, headers=_auth(admin_user))
    counts = r.json()["cat_counts"]
    assert counts.get("质量保障") == 1
    assert sum(counts.values()) == r.json()["all_total"]


async def test_cat_counts_follow_search_query(client, admin_user):
    """③ 搜索词也是**当前作用域** —— 计数要跟着它走."""
    me = admin_user["username"]
    await _seed_asset("cc-hit", author=me, category="质量保障", summary="命中关键词")
    await _seed_asset("cc-miss", author=me, category="效率工具", summary="不相关")

    r = await client.get("/api/v1/extensions", params={"q": "命中关键词"}, headers=_auth(admin_user))
    counts = r.json()["cat_counts"]
    assert counts.get("质量保障") == 1
    assert "效率工具" not in counts, "不相关的分类不该出现在计数里"


async def test_cat_counts_omits_categories_with_zero_items(client, admin_user):
    """④ 作用域里没有资产的分类**不在 map 里** → 前端显示 0 (不是"没统计")."""
    me = admin_user["username"]
    await _seed_asset("cc-only", author=me, category="质量保障")

    r = await client.get("/api/v1/extensions", headers=_auth(admin_user))
    counts = r.json()["cat_counts"]
    assert "效率工具" not in counts
    assert counts.get("质量保障") == 1


async def test_cat_counts_respect_visibility(client, admin_user, publisher_user):
    """⚠️ 计数要跟可见性口径一致 —— 别人未上架的资产不该算进我的计数."""
    await _seed_asset(
        "cc-hidden", author=publisher_user["username"], category="效率工具",
        publish_status="pending",
    )
    r = await client.get("/api/v1/extensions", headers=_auth(publisher_user))
    body = r.json()
    counts = body["cat_counts"]
    assert counts.get("效率工具") == 1, "自己提交的待审资产该算进来"
    assert sum(counts.values()) == body["all_total"]
