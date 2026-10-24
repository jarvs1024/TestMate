"""资产命名契约 —— code / 安装包名 / MCP 连接器名 三者的关系.

⚠️ 2026-10-25 整改: 一致性这条规则以前**只有前端**管 ——
   绕过前端直接调 API, 就能上架一个"资产号与包名对不上"的资产.
"""
from __future__ import annotations

from app.core import market_naming as mn


# ---------- 包名 ----------

def test_package_base_name_strips_suffix():
    assert mn.package_base_name("dml-foo.zip") == "dml-foo"
    assert mn.package_base_name("dml-foo.tar.gz") == "dml-foo"
    assert mn.package_base_name("dml-foo.tgz") == "dml-foo"
    assert mn.package_base_name("") == ""


def test_package_consistency_accepts_matching():
    assert mn.check_package_consistency("dml-foo.zip", "dml-foo") == ""


def test_package_consistency_rejects_mismatch():
    err = mn.check_package_consistency("weekly-report.zip", "dml-foo")
    assert "一致" in err
    assert "weekly-report" in err and "dml-foo" in err


def test_package_consistency_ignores_when_no_package():
    assert mn.check_package_consistency("", "dml-foo") == ""


# ---------- MCP 连接器名 ----------

def test_mcp_code_must_be_one_of_the_servers():
    cfg = {"mcpServers": {"dml-a": {"url": "http://h/mcp"}, "dml-b": {"url": "http://h/mcp"}}}
    assert mn.check_mcp_code_consistency(cfg, "dml-a") == ""
    assert mn.check_mcp_code_consistency(cfg, "dml-b") == ""
    err = mn.check_mcp_code_consistency(cfg, "dml-other")
    assert "一致" in err
    assert "dml-a" in err and "dml-b" in err


def test_mcp_code_check_ignores_empty_config():
    assert mn.check_mcp_code_consistency(None, "dml-a") == ""
    assert mn.check_mcp_code_consistency({"mcpServers": {}}, "dml-a") == ""
