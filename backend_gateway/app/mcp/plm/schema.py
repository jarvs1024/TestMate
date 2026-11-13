"""PLM 问题单建单字段定义与严格校验 (与 AiTestX 对齐)."""
from __future__ import annotations

import base64
from typing import Any

PROJECT_REF = "IMP-PLM-RDPM.plm-rdpm_project_20210410Ref"
QUESTION_TYPE_REF = "plm-base_questionCgr_Ref"
MEMBER_REF = "ucf-staff-center.bd_staff_simple_ref"

MAX_ATTACHMENTS = 3
MAX_EACH_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024

DEFAULTS = {"genyinfenxi": "NA", "attribute1": "NA"}

STATIC_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "key": "project_id",
        "name": "关联项目",
        "type": "refselect",
        "required": True,
        "refCode": PROJECT_REF,
    },
    {
        "key": "questionCgrId",
        "name": "问题类型",
        "type": "refselect",
        "required": True,
        "refCode": QUESTION_TYPE_REF,
    },
    {
        "key": "raisePerson",
        "name": "下一步处理人",
        "type": "refselect",
        "required": True,
        "refCode": MEMBER_REF,
    },
    {
        "key": "quesBelongArea",
        "name": "问题归属领域",
        "type": "select",
        "required": True,
        "options": [
            {"id": "1", "name": "硬件"},
            {"id": "2", "name": "结构"},
            {"id": "3", "name": "固件"},
            {"id": "4", "name": "介质"},
            {"id": "5", "name": "装备"},
            {"id": "6", "name": "生产工艺"},
            {"id": "7", "name": "生产测试"},
            {"id": "8", "name": "来料"},
            {"id": "9", "name": "其他"},
            {"id": "10", "name": "系统测试"},
        ],
    },
    {
        "key": "QuesmoduleSel",
        "name": "问题模块",
        "type": "select",
        "required": True,
        "options": [
            {"id": "1", "name": "硬件"},
            {"id": "2", "name": "芯片"},
            {"id": "3", "name": "介质"},
            {"id": "4", "name": "主机装备"},
            {"id": "5", "name": "外设"},
            {"id": "6", "name": "SATA-IO"},
            {"id": "7", "name": "SATA-类IO"},
            {"id": "8", "name": "SATA-SMART"},
            {"id": "9", "name": "SATA-log page"},
            {"id": "10", "name": "SATA-admin"},
            {"id": "11", "name": "NFC"},
            {"id": "12", "name": "NFI"},
        ],
    },
    {
        "key": "projectJD",
        "name": "项目阶段",
        "type": "select",
        "required": True,
        "options": [{"id": key, "name": key} for key in ("TR1", "TR2", "TR3", "TR4", "TR4A", "TR5", "TR6", "GA", "PDCP", "ADCP")],
    },
    {
        "key": "questionTdArea",
        "name": "提单领域",
        "type": "select",
        "required": True,
        "options": [
            {"id": "1", "name": "固件开发"},
            {"id": "2", "name": "硬件开发"},
            {"id": "3", "name": "测试领域"},
            {"id": "4", "name": "产品工程（生产）"},
            {"id": "5", "name": "FAE(线上)"},
            {"id": "6", "name": "FAE (OEM)"},
            {"id": "7", "name": "质量"},
            {"id": "8", "name": "介质"},
            {"id": "9", "name": "产品维护"},
        ],
    },
    {
        "key": "questionPriority",
        "name": "优先级",
        "type": "select",
        "required": True,
        "options": [{"id": "1", "name": "高"}, {"id": "2", "name": "中"}, {"id": "3", "name": "低"}],
    },
    {
        "key": "quesSever",
        "name": "严重程度",
        "type": "select",
        "required": True,
        "options": [
            {"id": "1", "name": "致命"},
            {"id": "2", "name": "严重"},
            {"id": "3", "name": "一般"},
            {"id": "4", "name": "提示"},
        ],
    },
    {"key": "genyinfenxi", "name": "产品型号", "type": "text", "required": True, "default_value": "NA"},
    {"key": "attribute1", "name": "产品类别", "type": "text", "required": True, "default_value": "NA"},
    {"key": "attribute2", "name": "固件版本", "type": "text", "required": True},
)

_FIELDS_BY_KEY = {field["key"]: field for field in STATIC_FIELDS}


def required_keys() -> list[str]:
    return [
        field["key"]
        for field in STATIC_FIELDS
        if field["required"] and field.get("default_value") is None
    ]


def normalize_options(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ident = item.get("_id") or item.get("id") or item.get("key") or ""
        name = item.get("text") or item.get("name") or item.get("value") or ""
        if ident:
            out.append({"id": str(ident), "name": str(name)})
    return out


def build_options(
    template_meta: dict[str, Any] | None = None,
    question_types: list[dict[str, Any]] | None = None,
    projects: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, str]]]:
    options: dict[str, list[dict[str, str]]] = {}
    for field in STATIC_FIELDS:
        if field.get("options"):
            options[field["key"]] = list(field["options"])
    for key, items in (template_meta or {}).items():
        normalized = normalize_options(items)
        if normalized:
            options[str(key)] = normalized
    if question_types:
        normalized = normalize_options(question_types)
        if normalized:
            options["questionCgrId"] = normalized
    if projects:
        options["project_id"] = [
            {
                "id": str(item.get("id") or ""),
                "name": (str(item.get("code") or "") + " | " + str(item.get("name") or "")).strip(" |"),
            }
            for item in projects
            if item.get("id")
        ]
    return options


def base64_bytes(value: str) -> int:
    text = str(value or "")
    if not text:
        return 0
    padding = 2 if text.endswith("==") else (1 if text.endswith("=") else 0)
    return max(0, len(text) * 3 // 4 - padding)


def validate_attachments(items: Any) -> tuple[bool, str, int]:
    attachments = items if isinstance(items, list) else []
    if len(attachments) > MAX_ATTACHMENTS:
        return False, f"附件最多 {MAX_ATTACHMENTS} 个", 0
    total = 0
    for item in attachments:
        if not isinstance(item, dict):
            return False, "附件格式非法", 0
        if not item.get("name") or not (item.get("content_base64") or item.get("contentBase64")):
            return False, "附件缺少 name 或 content_base64", 0
        size = base64_bytes(item.get("content_base64") or item.get("contentBase64") or "")
        if size > MAX_EACH_BYTES:
            return False, "单个附件超过 10MB", 0
        total += size
    if total > MAX_TOTAL_BYTES:
        return False, "附件合计超过 20MB", 0
    return True, "", total


def validate_create(
    args: dict[str, Any],
    options: dict[str, list[dict[str, str]]] | None,
    *,
    project_required: bool = True,
) -> dict[str, Any]:
    """返回 {ok, missing_required, invalid_options, error}."""
    values = {**DEFAULTS, **(args or {})}
    has_project = bool(
        str(values.get("project_id") or "").strip()
        or str(values.get("project_code") or "").strip()
    )
    missing = [
        key
        for key in required_keys()
        if not (key == "project_id" and has_project)
        and (values.get(key) is None or str(values.get(key)).strip() == "")
    ]
    if project_required and not has_project and "project_id" not in missing:
        missing.insert(0, "project_id")
    if not str(values.get("name") or "").strip() and "name" not in missing:
        missing.append("name")

    invalid: list[dict[str, Any]] = []
    for key, items in (options or {}).items():
        if not isinstance(items, list) or not items:
            continue
        value = values.get(key)
        if value is None or value == "":
            continue
        allowed = {str(item.get("id")) for item in items}
        if str(value) not in allowed:
            invalid.append({"key": key, "value": value})

    ok, error, _total = validate_attachments(args.get("attachments"))
    if not ok:
        return {
            "ok": False,
            "missing_required": missing,
            "invalid_options": invalid,
            "error": error,
        }
    return {
        "ok": not missing and not invalid,
        "missing_required": missing,
        "invalid_options": invalid,
        "error": "",
    }


def describe_create_meta(
    options: dict[str, list[dict[str, str]]],
    projects: list[dict[str, Any]],
    *,
    remote_options: bool,
) -> dict[str, Any]:
    fields = []
    for field in STATIC_FIELDS:
        item = {
            "key": field["key"],
            "name": field["name"],
            "type": field["type"],
            "required": bool(field["required"] and field.get("default_value") is None),
            "default_value": field.get("default_value") or "",
            "options": options.get(field["key"], []),
            "refCode": field.get("refCode") or "",
        }
        fields.append(item)
    hints = [
        "建单必须关联项目: 先用 plm_list_projects 取 project_id (或 project_code); 缺项目会拒绝建单",
        "问题类型 questionCgrId 必须是当前字典 id; 否则不会生成问题单号, 建单被拒绝",
        "下一步处理人 raisePerson 用 plm_search_members 查询; 提单后会反查确认处理人已写入",
        "必填属性必须合规 (下拉字段只能用 options 中的 id); genyinfenxi / attribute1 省略时默认 NA",
        "plm_create_question 会先预占 WSD 问题单号并做重复校验; 提交前可用 plm_preview_question 校验",
    ]
    if not remote_options:
        hints.append("本次未取到 PLM 在线字典, 下拉 options 为内置兜底值, 建单前请重试 plm_get_create_meta")
    return {
        "required": required_keys(),
        "defaults": DEFAULTS,
        "options": options,
        "projects": [
            {
                "id": str(item.get("id") or ""),
                "code": str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "principal": str(item.get("principal") or ""),
            }
            for item in projects
            if item.get("id")
        ],
        "fields": fields,
        "hints": hints,
        "remote_options": remote_options,
    }


def field_name(key: str) -> str:
    field = _FIELDS_BY_KEY.get(key)
    return str(field.get("name") if field else key)


def attachment_payloads(items: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        content = item.get("content_base64") or item.get("contentBase64") or ""
        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, TypeError):
            data = b""
        out.append({"name": str(item.get("name") or "attachment"), "content": data})
    return out
