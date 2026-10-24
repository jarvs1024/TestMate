"""MCP (连接器) 配置的校验 —— 连接器是**配置型**资产.

跟技能/插件的根本区别:
    技能 / 插件  = 一个安装包 (解压出 SKILL.md / README.md + files/)
    连接器 (mcp) = **一段 MCP 配置** (没有安装包, 也没有 README)

约定的配置格式 (MCP 标准):
    {
      "mcpServers": {
        "<连接器名>": {
          "command": "npx",            # 进程型: command + args
          "args": ["-y", "some-mcp"],
          "env": { "API_URL": "..." }   # 可选
        },
        "<另一个>": {
          "url": "http://host:5050/mcp",   # 远程型: url (+ headers)
          "headers": { "Authorization": "..." }   # 可选
        }
      }
    }

校验只管**结构合不合法**, 不管这个服务真的连不连得上 (那是运行期的事).
"""
from __future__ import annotations

import json
from typing import Any

MAX_CONFIG_BYTES = 64 * 1024


class McpConfigError(ValueError):
    """MCP 配置不合法 —— 消息直接给用户看."""


def parse_mcp_config(raw: str | dict | None) -> dict[str, Any]:
    """把用户填的文本解析成配置对象; 不合法就抛 McpConfigError.

    raw 可以是 str (表单里的 JSON 文本) 或已经是 dict (API 直接传对象).
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise McpConfigError("连接器必须提供 MCP 配置 (mcpServers)")
    if isinstance(raw, dict):
        cfg = raw
    else:
        text = raw.strip()
        if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
            raise McpConfigError("MCP 配置太大 (超过 64KB)")
        try:
            cfg = json.loads(text)
        except json.JSONDecodeError as e:
            raise McpConfigError(f"JSON 格式错误: 第 {e.lineno} 行第 {e.colno} 列 — {e.msg}") from e
    validate_mcp_config(cfg)
    return cfg


def validate_mcp_config(cfg: Any) -> dict[str, Any]:
    """校验 MCP 配置结构, 合法就原样返回, 不合法抛 McpConfigError."""
    if not isinstance(cfg, dict):
        raise McpConfigError("MCP 配置必须是一个 JSON 对象")

    servers = cfg.get("mcpServers")
    if servers is None:
        raise McpConfigError("缺少 mcpServers —— 配置形如 {\"mcpServers\": {\"名字\": {...}}}")
    if not isinstance(servers, dict):
        raise McpConfigError("mcpServers 必须是一个对象")
    if not servers:
        raise McpConfigError("mcpServers 里至少要有一个连接器")

    for name, spec in servers.items():
        if not isinstance(name, str) or not name.strip():
            raise McpConfigError("mcpServers 里的连接器名不能为空")
        if not isinstance(spec, dict):
            raise McpConfigError(f"连接器「{name}」的配置必须是一个对象")

        command = spec.get("command")
        url = spec.get("url")
        if not command and not url:
            raise McpConfigError(
                f"连接器「{name}」缺启动方式: 要么给 command (进程型), 要么给 url (远程型)"
            )
        if command is not None and not isinstance(command, str):
            raise McpConfigError(f"连接器「{name}」的 command 必须是字符串")
        if url is not None:
            if not isinstance(url, str):
                raise McpConfigError(f"连接器「{name}」的 url 必须是字符串")
            if not url.startswith(("http://", "https://")):
                raise McpConfigError(f"连接器「{name}」的 url 必须以 http:// 或 https:// 开头")
        if "args" in spec and not isinstance(spec["args"], list):
            raise McpConfigError(f"连接器「{name}」的 args 必须是数组")
        for opt in ("env", "headers"):
            if opt in spec and not isinstance(spec[opt], dict):
                raise McpConfigError(f"连接器「{name}」的 {opt} 必须是一个对象")

    return cfg


def format_mcp_config(cfg: dict[str, Any]) -> str:
    """格式化 (给前端展示用) —— 统一 2 空格缩进, 末尾换行."""
    return json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
