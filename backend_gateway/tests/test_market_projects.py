"""项目列表 —— "这条资产属于哪个项目 (还是通用)".

规则:
    · 项目列表是**配置** (设置项 marketplace.projects), 不是写死的常量
    · 空 project = **通用** (所有项目都能用)
    · 不在列表里的项目名 → 归一成通用 (脏值不进 manifest)
"""
from __future__ import annotations

from app.core import market_projects as mp


# ---------- 解析配置 ----------

def test_parse_comma_separated():
    assert mp.parse("6100,3361,8560") == ["6100", "3361", "8560"]


def test_parse_accepts_chinese_and_newline_separators():
    assert mp.parse("6100，3361、8560\n9560") == ["6100", "3361", "8560", "9560"]


def test_parse_drops_empty_and_dedupes():
    assert mp.parse("6100,,3361 ,6100") == ["6100", "3361"]


def test_parse_empty_gives_empty_list():
    assert mp.parse("") == []
    assert mp.parse(None) == []


# ---------- 归一 ----------

def test_normalize_keeps_known_project():
    assert mp.normalize("6100", ["6100", "3361"]) == "6100"


def test_normalize_unknown_project_becomes_general():
    """项目从列表里删掉 / 用户瞎填 → 归通用, 不让脏值流进索引."""
    assert mp.normalize("9999", ["6100"]) == mp.GENERAL


def test_normalize_empty_is_general():
    assert mp.normalize("", ["6100"]) == mp.GENERAL
    assert mp.normalize(None, ["6100"]) == mp.GENERAL


def test_is_valid():
    assert mp.is_valid("", ["6100"]) is True      # 通用永远合法
    assert mp.is_valid("6100", ["6100"]) is True
    assert mp.is_valid("9999", ["6100"]) is False


# ---------- 展示 ----------

def test_label():
    assert mp.label("6100") == "6100 项目"
    assert mp.label("") == "通用"


def test_default_projects_not_empty():
    """默认项目列表不能是空的 —— 否则上传表单只剩「通用」可选."""
    assert mp.DEFAULT_PROJECTS
    assert all(p.strip() for p in mp.DEFAULT_PROJECTS)
