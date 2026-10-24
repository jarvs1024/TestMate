"""索引与文件校验单元测试 —— 市场目录的"真相源"逻辑."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import market_catalog as mc


# ---------- 文件校验 ----------

def test_validate_files_accepts_normal():
    out = mc.validate_files({"SKILL.md": "# x", "docs/a.md": "y"})
    assert out == {"SKILL.md": "# x", "docs/a.md": "y"}


@pytest.mark.parametrize("bad", ["../evil.md", "a/../../evil.md", "a/../b.md"])
def test_validate_files_rejects_path_escape(bad: str):
    with pytest.raises(mc.ManifestError, match="非法路径"):
        mc.validate_files({bad: "x"})


def test_validate_files_normalizes_absolute_path():
    """绝对路径被规范化成相对路径 (落点仍在资产目录内, 不构成逃逸)."""
    out = mc.validate_files({"/abs/evil.md": "x"})
    assert "abs/evil.md" in out
    assert not any(p.startswith("/") or ".." in p for p in out)


def test_validate_files_rejects_bad_suffix():
    with pytest.raises(mc.ManifestError, match="不支持的文件类型"):
        mc.validate_files({"evil.exe": "x"})


def test_validate_files_rejects_too_many():
    with pytest.raises(mc.ManifestError, match="文件数超限"):
        mc.validate_files({f"f{i}.md": "x" for i in range(5)}, max_files=2)


def test_validate_files_rejects_too_big():
    with pytest.raises(mc.ManifestError, match="总体积超限"):
        mc.validate_files({"a.md": "A" * 100}, max_total_bytes=10)


def test_validate_files_normalizes_backslash():
    out = mc.validate_files({"sub\\a.md": "x"})
    assert "sub/a.md" in out


# ---------- code / 版本 校验 ----------

def test_validate_code():
    assert mc.validate_code("abc-123") == "abc-123"
    for bad in ("A", "ab", "-abc", "abc-", "a b", "a_b", "x" * 100):
        with pytest.raises(mc.ManifestError):
            mc.validate_code(bad)


def test_validate_version():
    assert mc.validate_version("1.2.3") == "1.2.3"
    assert mc.validate_version("v1.2.3") == "1.2.3"
    assert mc.validate_version("1.2.3-beta.1") == "1.2.3-beta.1"
    for bad in ("1.2", "abc", "1.2.3.4.5", ""):
        with pytest.raises(mc.ManifestError):
            mc.validate_version(bad)


def test_category_slug_and_path():
    # 分类 → 目录 slug (分类表是唯一真源, 详见 test_market_categories.py)
    assert mc.category_slug("质量诊断") == "diagnose"
    assert mc.category_slug("方案用例") == "cases"
    # 不在表里的分类 → 「其他」(misc), 不会再临时生成新 slug
    assert mc.category_slug("没在表里的分类") == "misc"
    # 旧分类名也能算出旧 slug 之外的映射 —— 归一到新分类再取 slug
    assert mc.category_slug("Trace 诊断") == "diagnose"
    p = mc.asset_git_path("skill", "质量诊断", "demo")
    assert p == "assets/skills/diagnose/demo"
    p2 = mc.asset_git_path("plugin", "流程管控", "demo")
    assert p2 == "assets/plugins/flow/demo"


# ---------- 索引条目 ----------

class _FakeAsset:
    """够 asset_to_index_entry 用的最小对象 (不落库)."""

    def __init__(self, **kw):
        self.code = kw.get("code", "demo")
        self.name = kw.get("name", "演示")
        self.icon = kw.get("icon", "🧩")
        self.kind = kw.get("kind", "skill")
        self.version = kw.get("version", "1.0.0")
        self.summary = kw.get("summary", "摘要")
        self.description = kw.get("description", "说明")
        self.use_when = kw.get("use_when", "何时")
        self.not_for = kw.get("not_for", "何时不")
        self.category = kw.get("category", "Trace 诊断")
        self.tags = kw.get("tags", ["a"])
        self.keywords = kw.get("keywords", [])
        self.author = kw.get("author", "admin")
        self.featured = kw.get("featured", 0)
        self.homepage = kw.get("homepage", None)
        self.permissions = kw.get("permissions", {})
        self.install_steps = kw.get("install_steps", [])
        self.bindings = kw.get("bindings", {})
        self.project = kw.get("project", "")
        self.review_note = kw.get("review_note", "")
        self.git_path = kw.get("git_path", "assets/skills/trace/demo")
        self.download_count = kw.get("download_count", 0)
        self.publish_status = kw.get("publish_status", "published")
        self.updated_at = None


def test_index_entry_carries_publish_status():
    """发布状态必须进索引 —— 别的实例才知道这个资产被下架/待审了."""
    e = mc.asset_to_index_entry(_FakeAsset(publish_status="pending"))
    assert e["publish_status"] == "pending"
    e2 = mc.asset_to_index_entry(_FakeAsset(publish_status="unpublished"))
    assert e2["publish_status"] == "unpublished"


def test_index_entry_defaults_published():
    assert mc.asset_to_index_entry(_FakeAsset(publish_status=""))["publish_status"] == "published"


def test_render_index_entries_is_deterministic():
    a = mc.asset_to_index_entry(_FakeAsset(code="b"))
    b = mc.asset_to_index_entry(_FakeAsset(code="a"))
    one = mc.render_index_entries([a, b])
    two = mc.render_index_entries([b, a])
    # 排序按 code, 与入参顺序无关
    assert one == two
    d = json.loads(one)
    assert [x["code"] for x in d["assets"]] == ["a", "b"]
    assert d["schema_version"] == mc.INDEX_SCHEMA_VERSION


async def test_stage_index_and_apply_back(ws, restore_git_config):  # noqa: ARG001
    """索引写出去再读回来, 资产不该丢."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="idx-demo", name="索引演示", kind="skill", version="1.0.0",
            publish_status="rejected", git_path="assets/skills/trace/idx-demo",
        ))
        await s.commit()

    async with AsyncSessionLocal() as s:
        await mc.stage_index(
            s, override=mc.asset_to_index_entry(
                _FakeAsset(code="idx-demo", publish_status="rejected")
            ),
        )
    raw = (ws / mc.INDEX_PATH).read_text(encoding="utf-8")
    d = json.loads(raw)
    assert d["assets"][0]["code"] == "idx-demo"

    # 回灌: publish_status 要能还原 (不然下架状态在别的实例上会丢)
    async with AsyncSessionLocal() as s:
        from sqlalchemy import select

        a = (await s.execute(select(Asset).where(Asset.code == "idx-demo"))).scalar_one()
        a.publish_status = "published"
        await s.commit()
    async with AsyncSessionLocal() as s:
        added, updated = await mc.apply_index_to_db(s)
    assert added == 0
    async with AsyncSessionLocal() as s:
        from sqlalchemy import select

        a = (await s.execute(select(Asset).where(Asset.code == "idx-demo"))).scalar_one()
        assert a.publish_status == "rejected"


async def test_apply_index_to_db_creates_missing(ws, restore_git_config):  # noqa: ARG001
    """索引里有、库里没有的资产 → 回灌时补出来."""
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="idx-seed", name="种子", kind="skill", version="1.0.0",
            publish_status="published", git_path="assets/skills/trace/idx-seed",
        ))
        await s.commit()

    async with AsyncSessionLocal() as s:
        await mc.stage_index(s)
    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == "idx-seed"))).scalar_one()
        await s.delete(a)
        await s.commit()

    async with AsyncSessionLocal() as s:
        added, updated = await mc.apply_index_to_db(s)
    assert added == 1
    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == "idx-seed"))).scalar_one()
        assert a.publish_status == "published"


def test_index_entry_carries_project():
    """适用范围必须进索引 —— 别的实例才知道这个资产是哪个项目特有的."""
    e = mc.asset_to_index_entry(_FakeAsset(project="6100"))
    assert e["project"] == "6100"
    # 通用资产 = 空串 (不是 None, 免得前端判空踩坑)
    assert mc.asset_to_index_entry(_FakeAsset(project=""))["project"] == ""


def test_build_manifest_carries_project():
    """manifest 是权威 —— 适用范围要写进去."""
    m = mc.build_manifest(
        code="dml-demo", kind="skill", name="演示", version="1.0.0",
        summary="摘要", project="6100",
    )
    assert m["project"] == "6100"
    # 默认 = 通用
    m2 = mc.build_manifest(
        code="dml-demo2", kind="skill", name="演示", version="1.0.0", summary="摘要",
    )
    assert m2["project"] == ""


async def test_project_and_review_note_survive_index_roundtrip(ws, restore_git_config):  # noqa: ARG001
    """适用范围与审核意见要能经 index.json 往返还原.

    ⚠️ 少了这一步: 别的实例同步过来后, 资产是"6100 特有"却变成通用,
    或者"已驳回"却看不到驳回理由 —— 跨实例就丢信息了.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.asset import Asset
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        s.add(Asset(
            code="rt-demo", name="往返演示", kind="skill", version="1.0.0",
            publish_status="rejected", review_note="权限声明不完整",
            git_path="assets/skills/misc/rt-demo", project="6100",
        ))
        await s.commit()

    async with AsyncSessionLocal() as s:
        await mc.stage_index(
            s, override=mc.asset_to_index_entry(
                _FakeAsset(code="rt-demo", publish_status="rejected",
                           review_note="权限声明不完整", project="6100")
            ),
        )
    raw = (ws / mc.INDEX_PATH).read_text(encoding="utf-8")
    d = json.loads(raw)
    entry = next(x for x in d["assets"] if x["code"] == "rt-demo")
    assert entry["project"] == "6100"
    assert entry["review_note"] == "权限声明不完整"

    # 把 DB 里的值改掉, 再从索引回灌 —— 应该被索引里的值还原
    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == "rt-demo"))).scalar_one()
        a.project = ""
        a.review_note = ""
        await s.commit()
    async with AsyncSessionLocal() as s:
        await mc.apply_index_to_db(s)
    async with AsyncSessionLocal() as s:
        a = (await s.execute(select(Asset).where(Asset.code == "rt-demo"))).scalar_one()
        assert a.project == "6100"
        assert a.review_note == "权限声明不完整"
