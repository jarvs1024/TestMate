"""测试提单标准 10 段描述模板 (与 AiTestX renderDescriptionHtml 同形)."""
from __future__ import annotations

import re
from html import escape
from typing import Any

_URL_RE = re.compile(r"^https?://", re.I)
_LINE_BREAK_RE = re.compile(r"\r\n?|\n|\\r\\n|\\n")

_FIELD_STYLE = (
    "background-color:#ffffff;padding:4px 0 4px 12px;color:#1f2937;"
    "vertical-align:top;border-bottom:1px solid #e5e7eb;word-break:break-word;font-size:11px;"
)
_KEY_STYLE = (
    "text-align:left;width:150px;background-color:#f3f4f6;color:#6b7280;"
    "padding:4px 10px;vertical-align:top;font-weight:500;border-bottom:1px solid #e5e7eb;"
    "font-size:11px;"
)
_SECTION_STYLE = (
    "background-color:#e5e7eb;color:#1f2937;font-size:12px;font-weight:600;"
    "padding:6px 10px;text-align:left;border-bottom:1px solid #e5e7eb;"
    "border-top:1px solid #d1d5db;"
)


def _display(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _render_field(label: str, value: Any, *, required: bool = False, multiline: bool = False) -> str:
    text = _display(value)
    suffix = ' <sup style="color:#ef4444;font-weight:700;font-size:11px;">*</sup>' if required else ""
    if text == "-":
        rendered = "-"
    elif _URL_RE.match(text):
        safe = escape(text)
        rendered = (
            f'<a href="{safe}" target="_blank" style="color:#2563eb;text-decoration:none;">'
            f'{safe} <span style="color:#9ca3af;font-size:10px;">&#8599;</span></a>'
        )
    elif multiline and _LINE_BREAK_RE.search(text):
        rendered = "<br>".join(escape(part) for part in _LINE_BREAK_RE.split(text))
    else:
        rendered = escape(text)
    return (
        "<tr>"
        f'<th width="150" style="{_KEY_STYLE}">{escape(label)}{suffix}</th>'
        f'<td style="{_FIELD_STYLE}">{rendered}</td>'
        "</tr>"
    )


def _render_section(number: int, title: str, rows: str) -> str:
    heading = escape(f"{number}. {title}")
    return (
        '<tr class="dl-section-row">'
        f'<th colspan="2" style="{_SECTION_STYLE}">{heading}</th></tr>{rows}'
    )


def render_description(fields: dict[str, Any] | None = None) -> str:
    """按 11 大模块表单字段拼装 10 段 HTML; 未填字段渲染为 -."""
    data = fields or {}
    case = data.get("case") if isinstance(data.get("case"), dict) else data

    def pick(*keys: str) -> Any:
        for key in keys:
            value = case.get(key)
            if value is not None and value != "":
                return value
        return None

    steps = pick("steps", "caseName")
    failure = pick("failurePhenomenon", "failanany")
    expected = pick("expectedResult") or "用例执行成功"
    log_ips = case.get("logTextIps") if isinstance(case.get("logTextIps"), list) else []

    section1 = _render_section(
        1,
        "问题描述",
        _render_field("测试特性/开发模块", pick("featureModule"))
        + _render_field("预置条件", pick("preconditions"), multiline=True)
        + _render_field("关键操作步骤", steps, required=True, multiline=True)
        + _render_field("预期效果", expected, multiline=True)
        + _render_field("测试失败现象", failure, required=True, multiline=True),
    )
    section2 = _render_section(
        2,
        "测试环境",
        _render_field("主机信息-IP/Host", pick("hostIp") or (log_ips[0] if log_ips else None))
        + _render_field("主机信息-SN", pick("hostSn"))
        + _render_field("主机信息-OS", pick("hostOs"))
        + _render_field("SSD 数量及连接方式", pick("hostSsdTopology")),
    )
    section3 = _render_section(
        3,
        "版本信息",
        _render_field("FPGA", pick("fpgaVersion"))
        + _render_field("FW", pick("fwVersion"))
        + _render_field("驱动", pick("driverVersion")),
    )
    section4 = _render_section(
        4,
        "测试仪器",
        _render_field("仪器名称", pick("instrumentName"))
        + _render_field("IP/SN", pick("instrumentIpSn"))
        + _render_field("软件版本", pick("instrumentVersion")),
    )
    section5 = _render_section(5, "软件工具", _render_field("工具及版本", pick("softwareTools")))
    section6 = _render_section(
        6,
        "被测设备(盘片)信息",
        _render_field("硬件版本", pick("hwVersion"))
        + _render_field("固件版本", pick("dutFwVersion"))
        + _render_field("SN", pick("dutSn")),
    )
    section7 = _render_section(
        7,
        "测试用例信息",
        _render_field("用例编号", pick("caseId"), required=True)
        + _render_field("脚本编号/版本", pick("scriptInfo"))
        + _render_field("仓库信息", pick("scriptRepo"))
        + _render_field("修改记录", pick("scriptModifications")),
    )
    section8 = _render_section(8, "定位履历", _render_field("关键定位信息", pick("analysisTrace"), multiline=True))
    section9 = _render_section(
        9,
        "初步分析结论",
        _render_field("分析人", pick("analyzer"))
        + _render_field("初步原因", pick("initialReason"))
        + _render_field("问题发生时间", pick("occurTime", "startTime")),
    )
    section10 = _render_section(
        10,
        "测试日志",
        _render_field("串口日志", pick("logSerial"), multiline=True)
        + _render_field("训练器 Trace", pick("logTrace"), multiline=True)
        + _render_field("操作系统日志", pick("logOs"), multiline=True)
        + _render_field("测试工具输出", pick("logTool"), multiline=True),
    )

    header = (
        '<div style="margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #e5e7eb;'
        'font-size:12px;color:#1f2937;">'
        '<span style="color:#6b7280;">测试用例:</span> '
        f'<span style="font-weight:600;">{escape(_display(case.get("caseId")))}</span>'
        "</div>"
    )
    table = (
        '<table style="width:100%;table-layout:fixed;border-collapse:collapse;'
        'margin:6px 0 4px;border:0;">'
        '<colgroup><col style="width:150px"><col></colgroup>'
        "<tbody>"
        + section1
        + section2
        + section3
        + section4
        + section5
        + section6
        + section7
        + section8
        + section9
        + section10
        + "</tbody></table>"
    )
    return header + table
