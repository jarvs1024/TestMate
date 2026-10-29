"""业务分类表 —— 值域 / 归一 / 目录 slug (2026-10-26 分类重排).

锁住三件事:
  1. 分类是**固定枚举** + 「其他」兜底 —— 自定义分类一律归「其他」
  2. 目录 slug **冻结**: 分类改名不搬家 (改名 = 改 name, 不改 slug)
  3. 旧分类名能自动映射到新名 (老数据迁移用) —— 而且是**链式**的
     ("Spec 问答" → "方案用例" → "效率工具", 只查一次表会掉进「其他」)

另外锁住「逐资产迁移表」本身 (scripts/migrate_categories.py):
  每个资产的新分类必须是分类表里的正式名, 且 13 个存量资产**一个都不能漏** ——
  漏一个 = 那个资产要么留在旧分类 (前端筛不出来), 要么被静默归到「其他」.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core import market_categories as mc

# 正式分类 (顺序 = 按协作角色: 兜底 → 提效 → 守流程 → 管协同)
EXPECTED = [
    ("quality", "质量保障"),
    ("efficiency", "效率工具"),
    ("process", "流程规范"),
    ("management", "管理协同"),
    ("misc", "其他"),
]

# 2026-10-26 之前用过的所有分类名 (含 10-24 那轮改过的别名)
OLD_NAMES = [
    "Spec 问答", "机台运维", "环境助手", "老化任务", "测试报告",
    "Trace 诊断", "FW 比对", "自动化代码",
    "方案用例", "环境运维", "任务调度", "流程管控", "质量诊断", "知识资产",
]

# 存量 13 个资产 —— 迁移表必须**一个不漏**地覆盖
CURRENT_ASSETS = [
    "burn-result-reader", "code-review-pipeline", "dingtalk-notify",
    "nvme-spec-cheatsheet", "pr-agent-review", "review-agent-board",
    "ssd-log-cheatsheet", "ssd-log-doctor", "test-plan-assistant",
    "test-report-gen", "testcase-template-gen", "testmate-machine-ops",
    "weekly-report-assistant",
]


def _load_migration_module():
    """加载 scripts/migrate_categories.py (迁移映射表的真源)."""
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "migrate_categories.py"
    spec = importlib.util.spec_from_file_location("migrate_categories", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_category_table_is_the_expected_set():
    assert [(c["slug"], c["name"]) for c in mc.table()] == EXPECTED


def test_categories_are_unique():
    slugs = [c["slug"] for c in mc.table()]
    names = [c["name"] for c in mc.table()]
    assert len(set(slugs)) == len(slugs)
    assert len(set(names)) == len(names)


def test_order_is_sequential():
    """顺序要能表达"角色分工" —— 小的在前, 且不重复."""
    orders = [c["order"] for c in mc.table()]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)


def test_every_category_has_a_desc():
    """每个分类都要有一句话说明 —— 上传的人靠它判断"该往哪一类放"."""
    for c in mc.table():
        assert c.get("desc"), f"{c['name']} 缺说明"


def test_category_desc_is_short_enough_to_read_in_a_dropdown():
    """desc 必须**短** (2026-10-29 整改).

    ⚠️ desc 显示在「分类」下拉框的**选项行里**, 跟分类名并排.
       原来那种"对功能、性能、可靠性的全方位兜底 —— 定位问题、判定结果、给出判据"
       的长句会被**硬截断**成「…」, 用户根本读不到 —— 等于白写.
       长解释应该放到表单下面的说明文字里, 下拉框里只留一句短的.
    """
    for c in mc.table():
        d = c.get("desc") or ""
        assert len(d) <= 24, f"{c['name']} 的 desc 太长({len(d)}字): {d}"
        # 破折号是长文案的标志 —— 一旦出现基本就说明又写长了
        assert "——" not in d, f"{c['name']} 的 desc 里还有长破折号: {d}"


@pytest.mark.parametrize("name", [n for _, n in EXPECTED])
def test_normalize_keeps_known_categories(name):
    assert mc.normalize(name) == name
    assert mc.is_valid(name) is True


def test_normalize_falls_back_to_misc():
    """自填分类 / 空分类 → 「其他」 (不能开新目录, 也不能留孤儿分类)."""
    assert mc.normalize("自创分类") == "其他"
    assert mc.normalize("") == "其他"
    assert mc.normalize(None) == "其他"
    assert mc.is_valid("自创分类") is False


@pytest.mark.parametrize("old", OLD_NAMES)
def test_every_old_name_maps_into_the_new_table(old):
    """所有历史分类名都要能落到**新表**里的某个正式分类 (不能掉进「其他」).

    ⚠️ 这是**链式**的: "Spec 问答" → "方案用例" → "效率工具".
       只查一次表的话中间那层 (已经不是正式名了) 会把结果带进「其他」.
    """
    got = mc.normalize(old)
    assert got in [n for _, n in EXPECTED], f"{old} → {got}"
    assert got != "其他", f"{old} 掉进「其他」了 (别名链断了)"


def test_alias_chain_resolves_transitively():
    """链式解析的具体断言 (两层)."""
    assert mc.normalize("Spec 问答") == "效率工具"
    assert mc.normalize("Trace 诊断") == "质量保障"
    assert mc.normalize("测试报告") == "管理协同"
    assert mc.normalize("机台运维") == "效率工具"


def test_slug_of_is_stable_per_category():
    """slug 由分类决定, 且跟中文名一一对应."""
    for slug, name in EXPECTED:
        assert mc.slug_of(name) == slug
    # 未知分类 → misc (绝不临时生成新 slug, 否则仓库里会开一堆新目录)
    assert mc.slug_of("自创分类") == "misc"
    assert mc.slug_of("") == "misc"


def test_name_of_slug():
    for slug, name in EXPECTED:
        assert mc.name_of_slug(slug) == name
    assert mc.name_of_slug("不存在") == "其他"


def test_names_helper_is_ordered():
    assert mc.names() == [n for _, n in EXPECTED]


def test_no_old_slugs_left():
    """2026-10-26 之前的 slug 全作废了 —— 留着会让旧目录名继续被算出来."""
    old_slugs = {"cases", "env", "schedule", "flow", "diagnose", "knowledge"}
    assert not (old_slugs & {s for s, _ in EXPECTED})


# ---------- 逐资产迁移表 ----------

def test_migration_covers_every_current_asset():
    """迁移表必须覆盖全部存量资产 —— 漏一个 = 那个资产留在旧分类."""
    mod = _load_migration_module()
    missing = [c for c in CURRENT_ASSETS if c not in mod.TARGET_CATEGORY]
    assert not missing, f"迁移表漏了: {missing}"


def test_migration_targets_are_valid_categories():
    """迁移表里的目标分类必须都是正式分类 (不能写成"其他"糊弄过去)."""
    mod = _load_migration_module()
    valid = {n for _, n in EXPECTED}
    for code, target in mod.TARGET_CATEGORY.items():
        assert target in valid, f"{code} → {target} 不是正式分类"
        assert target != "其他", f"{code} 不该归到「其他」"


def test_migration_targets_cover_all_five_categories():
    """5 个分类都要有资产 —— 空着的分类说明映射表没想清楚."""
    mod = _load_migration_module()
    used = set(mod.TARGET_CATEGORY.values())
    used.discard("其他")   # 「其他」是兜底, 可以没有资产
    assert used == {"质量保障", "效率工具", "流程规范", "管理协同"}, used


def test_fallback_by_old_category_is_consistent():
    """兜底映射的目标也必须是正式分类 (老数据撞上没登记的资产时用)."""
    mod = _load_migration_module()
    valid = {n for _, n in EXPECTED}
    for old, target in mod.FALLBACK_BY_OLD.items():
        assert target in valid, f"旧分类 {old} → {target} 不是正式分类"


def test_unpublish_list_only_contains_known_assets():
    """下架名单里的资产必须真实存在 —— 否则是打错字, 白改."""
    mod = _load_migration_module()
    unknown = mod.UNPUBLISH - set(CURRENT_ASSETS)
    assert not unknown, f"下架名单里有不存在的资产: {unknown}"
    assert mod.UNPUBLISH, "下架名单不该是空的"


def test_copy_patches_only_touch_known_assets():
    """文案补丁只能改真实存在的资产."""
    mod = _load_migration_module()
    unknown = set(mod.COPY_PATCHES) - set(CURRENT_ASSETS)
    assert not unknown, f"文案补丁里有不存在的资产: {unknown}"


# ---------- 种子脚本与迁移表必须一致 ----------

def _load_seed_module():
    """加载 scripts/seed_market.py (种子资产定义)."""
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "seed_market.py"
    spec = importlib.util.spec_from_file_location("seed_market", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_categories_match_migration_table():
    """种子里的分类必须跟迁移表一致.

    ⚠️ 这两处**必须一样**: 种子是"新环境怎么长出这个市场"的说明书,
       迁移表是"现有市场怎么改过来"的说明书. 说的不是一回事 = 迟早漂移.
    """
    seed = _load_seed_module()
    mod = _load_migration_module()
    by_code = {a["code"]: a for a in seed.ASSETS}
    for code, target in mod.TARGET_CATEGORY.items():
        if code not in by_code:
            continue  # 故意不种的 (已下架的连接器) 不在种子里
        assert by_code[code]["category"] == target, (
            f"{code}: 种子写的是「{by_code[code]['category']}」, 迁移表写的是「{target}」"
        )


def test_seed_copy_matches_migration_patches():
    """种子里的文案必须跟迁移补丁一致 (否则新环境灌出来的话跟线上不一样)."""
    seed = _load_seed_module()
    mod = _load_migration_module()
    by_code = {a["code"]: a for a in seed.ASSETS}
    for code, patch in mod.COPY_PATCHES.items():
        if code not in by_code:
            continue
        for field, want in patch.items():
            got = by_code[code].get(field)
            assert got == want, f"{code}.{field}: 种子写的是 {got!r}, 迁移补丁是 {want!r}"


def test_seed_has_no_orphan_or_dead_assets():
    """种子里不能有: ① 已下架的资产 ② 指向已下线服务的资产.

    ⚠️ 这两条都是踩过的坑:
       · kb-search 指向已下线的 RAGFlow —— 再灌一次就把死连接器又造出来了
       · pr-agent-review / testmate-machine-ops 的目标服务不在部署范围内 —— 已下架
    """
    seed = _load_seed_module()
    mod = _load_migration_module()
    codes = {a["code"] for a in seed.ASSETS}
    assert not (mod.UNPUBLISH & codes), f"种子里不该有已下架的资产: {mod.UNPUBLISH & codes}"
    assert "kb-search" not in codes, "kb-search 指向已下线的 RAGFlow, 不该再种"
    # 连接器必须显式写 mcp_server (别让脚本兜一个连不上的默认 url)
    for a in seed.ASSETS:
        if a["kind"] == "mcp":
            assert a.get("mcp_server"), f"{a['code']}: 连接器必须显式写 mcp_server"

