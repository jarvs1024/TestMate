"""PLM 问题描述标准模板: 复用 PingCode/AiTestX 的 10 段 HTML, 再按 PLM 富文本归一化."""
from __future__ import annotations

import re
from typing import Any

from app.mcp.pingcode.templates import render_description as render_standard

_GRID_COLGROUP = '<colgroup><col style="width:150px"><col></colgroup>'
_V_GRID_COLGROUP = "<colgroup>" + "<col>" * 10 + "</colgroup>"
_FONT_SIZE = re.compile(r"font-size:\s*11px")


def _apply_grid(html: str) -> str:
    """PLM 富文本会把表格列宽归一化成等宽列; 改成 10 等分栅格保住 20%/80% 布局."""
    return (
        html.replace(_GRID_COLGROUP, _V_GRID_COLGROUP)
        .replace('<th width="150" ', '<th colspan="2" width="150" ')
        .replace(
            '<td style="background-color:#ffffff',
            '<td colspan="8" style="background-color:#ffffff',
        )
        .replace(
            '<th colspan="2" style="background-color:#e5e7eb',
            '<th colspan="10" style="background-color:#e5e7eb',
        )
    )


def _normalize(html: str) -> str:
    """PLM 容器不再放大字号且折叠文本换行, 对齐 AiTestX plmNormalizeDescHtml."""
    html = _FONT_SIZE.sub("font-size:12px", html)
    html = html.replace("font-size:12px;", "font-size:12px;line-height:1.65;")
    return re.sub(r"\r\n?|\n", "<br>", html)


def render_description(fields: dict[str, Any] | None = None) -> str:
    return _normalize(_apply_grid(render_standard(fields)))
