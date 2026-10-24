"""MCP 配置校验 —— 连接器是**配置型**资产 (只有一段 JSON, 没有包).

规则 (前后端一致, 见 frontend_web/src/views/Market/mcpConfig.ts):
    必须是 JSON 对象
    必须有 mcpServers (对象, 非空)
    每个连接器: 要么 command (进程型), 要么 url (远程型, http/https)
"""
from __future__ import annotations

import pytest

from app.core.mcp_config import (
    McpConfigError,
    format_mcp_config,
    parse_mcp_config,
    validate_mcp_config,
)


def test_valid_command_style():
    cfg = {"mcpServers": {"dml-demo": {"command": "npx", "args": ["-y", "dml-demo"]}}}
    assert validate_mcp_config(cfg) == cfg


def test_valid_url_style():
    cfg = {"mcpServers": {"dml-demo": {"url": "http://host:5050/mcp"}}}
    assert validate_mcp_config(cfg) == cfg


def test_parse_from_text():
    text = '{"mcpServers": {"dml-demo": {"url": "https://h/mcp"}}}'
    cfg = parse_mcp_config(text)
    assert cfg["mcpServers"]["dml-demo"]["url"] == "https://h/mcp"


def test_empty_is_error():
    with pytest.raises(McpConfigError):
        parse_mcp_config("")


def test_bad_json_points_at_the_line():
    with pytest.raises(McpConfigError) as ei:
        parse_mcp_config('{\n  "mcpServers": {,}\n}')
    assert "JSON 格式错误" in str(ei.value)


def test_not_an_object():
    with pytest.raises(McpConfigError):
        validate_mcp_config([1, 2, 3])


def test_missing_mcp_servers():
    with pytest.raises(McpConfigError) as ei:
        validate_mcp_config({"foo": 1})
    assert "mcpServers" in str(ei.value)


def test_empty_mcp_servers():
    with pytest.raises(McpConfigError) as ei:
        validate_mcp_config({"mcpServers": {}})
    assert "至少要有一个" in str(ei.value)


def test_server_without_command_or_url():
    with pytest.raises(McpConfigError) as ei:
        validate_mcp_config({"mcpServers": {"dml-demo": {"args": ["x"]}}})
    assert "缺启动方式" in str(ei.value)


def test_bad_url_scheme():
    with pytest.raises(McpConfigError) as ei:
        validate_mcp_config({"mcpServers": {"dml-demo": {"url": "ftp://h/mcp"}}})
    assert "http://" in str(ei.value)


def test_args_must_be_list():
    with pytest.raises(McpConfigError) as ei:
        validate_mcp_config({"mcpServers": {"dml-demo": {"command": "npx", "args": "x"}}})
    assert "args" in str(ei.value)


def test_env_must_be_object():
    with pytest.raises(McpConfigError) as ei:
        validate_mcp_config({"mcpServers": {"dml-demo": {"command": "npx", "env": ["A=1"]}}})
    assert "env" in str(ei.value)


def test_format_is_stable():
    cfg = {"mcpServers": {"dml-demo": {"url": "http://h/mcp"}}}
    out = format_mcp_config(cfg)
    assert out.endswith("\n")
    assert '"mcpServers"' in out


def test_server_name_must_start_with_dml():
    """连接器名必须 dml- 开头 —— 详情页会原样展示这份配置, 用户照着抄。"""
    with pytest.raises(McpConfigError) as ei:
        validate_mcp_config({"mcpServers": {"xx-xxx": {"url": "http://h/mcp"}}})
    assert "dml-" in str(ei.value)


def test_server_name_rejects_illegal_chars():
    with pytest.raises(McpConfigError):
        validate_mcp_config({"mcpServers": {"dml-Bad_Name": {"url": "http://h/mcp"}}})
