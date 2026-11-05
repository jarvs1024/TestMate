"""扩展表单与 MCP 共用的只读规则包.

命名、包后缀、分类和项目均从现有校验模块派生, 避免接口再维护一套规则.
"""
from __future__ import annotations

import re
from typing import Any

from app.core import ext_catalog, ext_categories, ext_naming, ext_projects
from app.core.ext_catalog import CODE_EXAMPLE

_LENGTH_MATCH = re.search(
    r"\(\?=\.\{(\d+),(\d+)\}\$\)",
    ext_catalog.CODE_RE.pattern,
)
if _LENGTH_MATCH is None:  # pragma: no cover - 防止上游改格式后静默丢失长度约束
    raise RuntimeError("ext_catalog.CODE_RE 必须声明代码长度范围")
CODE_MIN_LENGTH = int(_LENGTH_MATCH.group(1))
CODE_MAX_LENGTH = int(_LENGTH_MATCH.group(2))


async def rules_payload() -> dict[str, Any]:
    """返回当前生效的扩展规则; 项目列表读取现有设置项."""
    try:
        from app.core.settings_store import get

        raw_projects = await get(ext_projects.SETTINGS_KEY, "")
    except Exception:  # noqa: BLE001 - 与现有项目列表接口一样, 设置读取失败用默认项目
        raw_projects = ""
    projects = ext_projects.parse(raw_projects) or list(ext_projects.DEFAULT_PROJECTS)
    segment_pattern = ext_catalog.CODE_RE.pattern
    # code 与 segment 同一套规则 —— 没有任何前缀要求.
    code_pattern = segment_pattern
    return {
        "code": {
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
        "package": {"suffixes": list(ext_naming.PACKAGE_SUFFIXES)},
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
        "categories": [dict(c) for c in ext_categories.table()],
        "projects": projects,
        "enforcement": {
            "code_must_match_package": True,
            "code_must_match_mcp_server": True,
            "unknown_category": ext_categories.normalize("__unknown__"),
            "unknown_project": ext_projects.normalize("__unknown__", projects),
        },
    }
