"""业务分类表 —— 值域 / 归一 / 目录 slug (2026-10-24 分类重排).

锁住三件事:
  1. 分类是**固定枚举** + 「其他」兜底 —— 自定义分类一律归「其他」
  2. 目录 slug **冻结**: 分类改名不搬家 (改名 = 改 name, 不改 slug)
  3. 旧分类名能自动映射到新名 (老数据迁移用)
"""
from __future__ import annotations

import pytest

from app.core import market_categories as mc

# 正式分类 (顺序 = 测试全流程的阶段顺序)
EXPECTED = [
    ("cases", "方案用例"),
    ("env", "环境助手"),
    ("schedule", "任务调度"),
    ("flow", "流程管控"),
    ("diagnose", "质量诊断"),
    ("knowledge", "知识资产"),
    ("misc", "其他"),
]


def test_category_table_is_the_expected_set():
    assert [(c["slug"], c["name"]) for c in mc.table()] == EXPECTED


def test_categories_are_unique():
    slugs = [c["slug"] for c in mc.table()]
    names = [c["name"] for c in mc.table()]
    assert len(set(slugs)) == len(slugs)
    assert len(set(names)) == len(names)


def test_order_is_sequential():
    """顺序要能表达"流程阶段" —— 小的在前, 且不重复."""
    orders = [c["order"] for c in mc.table()]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)


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


def test_legacy_names_map_to_new_ones():
    """旧分类名 → 新分类名 (迁移老数据用)."""
    assert mc.normalize("Trace 诊断") == "质量诊断"
    assert mc.normalize("Spec 问答") == "方案用例"
    assert mc.normalize("老化任务") == "任务调度"
    assert mc.normalize("测试报告") == "流程管控"
    assert mc.normalize("自动化代码") == "流程管控"
    assert mc.normalize("机台运维") == "环境助手"
    assert mc.normalize("FW 比对") == "质量诊断"


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
