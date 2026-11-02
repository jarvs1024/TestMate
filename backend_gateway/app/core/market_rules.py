"""扩展表单与 MCP 共用的只读规则包.

命名、包后缀、分类和项目均从现有校验模块派生, 避免接口再维护一套规则.
"""
from __future__ import annotations

import re
from typing import Any

from app.core import market_catalog, market_categories, market_naming, market_projects
from app.core.market_catalog import CODE_EXAMPLE, CODE_PREFIX

_LENGTH_MATCH = re.search(
    r"\(\?=\.\{(\d+),(\d+)\}\$\)",
    market_catalog.CODE_RE.pattern,
)
if _LENGTH_MATCH is None:  # pragma: no cover - 防止上游改格式后静默丢失长度约束
    raise RuntimeError("market_catalog.CODE_RE 必须声明代码长度范围")
CODE_MIN_LENGTH = int(_LENGTH_MATCH.group(1))
CODE_MAX_LENGTH = int(_LENGTH_MATCH.group(2))


async def rules_payload() -> dict[str, Any]:
    """返回当前生效的扩展规则; 项目列表读取现有设置项."""
    try:
        from app.core.settings_store import get

        raw_projects = await get(market_projects.SETTINGS_KEY, "")
    except Exception:  # noqa: BLE001 - 与现有项目列表接口一样, 设置读取失败用默认项目
        raw_projects = ""
    projects = market_projects.parse(raw_projects) or list(market_projects.DEFAULT_PROJECTS)
    segment_pattern = market_catalog.CODE_RE.pattern
    code_pattern = segment_pattern.replace(
        _LENGTH_MATCH.group(0),
        f"{_LENGTH_MATCH.group(0)}{CODE_PREFIX}",
        1,
    )
    return {
        "code": {
            "prefix": CODE_PREFIX,
            "pattern": code_pattern,
            "example": CODE_EXAMPLE,
            "min_length": CODE_MIN_LENGTH,
            "max_length": CODE_MAX_LENGTH,
        },
        "segment": {
            "pattern": segment_pattern,
            "min_length": CODE_MIN_LENGTH,
            "max_length": CODE_MAX_LENGTH,
        },
        "package": {"suffixes": list(market_naming.PACKAGE_SUFFIXES)},
        "required": {
            "create": {
                "common": ["code", "name", "summary", "category", "version"],
                "skill": ["package"],
                "plugin": ["package"],
                "mcp": ["mcp_config"],
            },
            "update": {
                "common": ["name", "summary", "category", "version"],
                "skill": ["package"],
                "plugin": ["package"],
                "mcp": ["mcp_config"],
            },
            "edit": ["name", "summary", "category"],
        },
        "categories": [dict(c) for c in market_categories.table()],
        "projects": projects,
        "enforcement": {
            "require_code_prefix_on_create": True,
            "require_code_prefix_on_update": False,
            "code_must_match_package": True,
            "code_must_match_mcp_server": True,
            "unknown_category": market_categories.normalize("__unknown__"),
            "unknown_project": market_projects.normalize("__unknown__", projects),
        },
    }
