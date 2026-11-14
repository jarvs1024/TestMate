"""PLM (YonBIP) 记录到 MCP 稳定输出结构的纯函数."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlparse

DEFAULT_BASE = "https://plm.twsc.com.cn"

EXT_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "svg": "image/svg+xml",
    "txt": "text/plain",
    "log": "text/plain",
    "csv": "text/csv",
    "json": "application/json",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

FIELD_KEYS = (
    "code",
    "name",
    "ques_status",
    "raisePerson",
    "owner",
    "creator",
    "questionPriority",
    "quesSever",
    "questionCgrId",
    "quesBelongArea",
    "QuesmoduleSel",
    "projectJD",
    "questionTdArea",
    "genyinfenxi",
    "attribute1",
    "attribute2",
    "discoveryTime",
    "resolutionTime",
    "creationtime",
    "modifyTime",
    "stateId",
    "priority",
    "severity",
    "projectId",
    "dept_id",
    "kaifamokuai",
    "xiangmujieduan",
    "shifouyonglifaxian",
    "ceshitexing",
    "wentileibie",
    "shifoukaifaziti",
    "replay_step1",
    "huiguiceshishuoming1",
    "Quetestabilit",
    "associatedObjectCode",
    "associatedObjectName",
    "confirmPerson",
    "quesClosetime",
)

_GROUP_RE = re.compile(r"mdf_[0-9a-fA-F-]{36}")
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR_RE = r"""\b{}\s*=\s*(['"])([\s\S]*?)\1"""


def html_to_text(html: Any) -> str:
    if html is None or html == "":
        return ""
    text = str(html)
    text = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, value in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(entity, value)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_ms(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(value if value >= 1e12 else value * 1000)
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except ValueError:
        return 0


def parse_size(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    match = re.match(r"^([\d.]+)\s*(bytes|KB|MB|GB)?$", text, re.IGNORECASE)
    if not match:
        return int(float(text)) if text.replace(".", "", 1).isdigit() else 0
    number = float(match.group(1))
    unit = (match.group(2) or "bytes").upper()
    factor = {"GB": 1024**3, "MB": 1024**2, "KB": 1024}.get(unit, 1)
    return int(number * factor)


def person_of(record: dict[str, Any], key: str) -> dict[str, str]:
    raw = record.get(key)
    if isinstance(raw, dict):
        ident = raw.get("id") or raw.get("_id") or raw.get("uid") or ""
        name = raw.get("name") or raw.get("text") or ""
    else:
        ident = raw or record.get(f"{key}_id") or ""
        name = ""
    name = name or record.get(f"{key}_name") or record.get(f"{key}_userName") or ""
    return {"id": str(ident or ""), "name": str(name or "")}


def person_named(record: dict[str, Any], key: str) -> dict[str, str]:
    person = person_of(record, key)
    if not person["name"] and person["id"]:
        for fallback in ("owner", "raisePerson"):
            other = person_of(record, fallback)
            if other["id"] == person["id"] and other["name"]:
                person["name"] = other["name"]
                break
    return person


def _readable(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if re.fullmatch(r"\d+", text) else text


# 问题状态 (ques_status) 字典; 列表页「问题状态」列即此字段, 与流程态 (lctemplate_attribute_id) 不同.
QUESTION_STATUS_NAMES = {
    "12": "问题提交",
    "13": "提交审核",
    "10": "根因分析",
    "2": "测试复现",
    "3": "修正方案",
    "4": "修正审核",
    "6": "回归测试",
    "8": "确认关闭",
}


def status_of(record: dict[str, Any]) -> str:
    code = str(record.get("ques_status") or "").strip()
    return str(
        record.get("ques_status_name")
        or QUESTION_STATUS_NAMES.get(code)
        or record.get("stateId")
        or record.get("lctemplate_attribute_id_name")
        or code
        or ""
    )



def status_id_of(record: dict[str, Any]) -> str:
    return str(record.get("lctemplate_attribute_id") or record.get("ques_status") or "")


def status_code_of(record: dict[str, Any]) -> str:
    return str(record.get("lctemplate_attribute_id_code") or "")


def priority_of(record: dict[str, Any]) -> str:
    return str(
        record.get("questionPriority_name")
        or _readable(record.get("priority"))
        or record.get("questionPriority")
        or ""
    )


def severity_of(record: dict[str, Any]) -> str:
    return str(
        record.get("quesSever_name")
        or _readable(record.get("severity"))
        or record.get("quesSever")
        or ""
    )


def base_of(ctx: dict[str, Any] | None) -> str:
    if ctx and ctx.get("base"):
        return str(ctx["base"])
    if ctx and ctx.get("url"):
        parsed = urlparse(str(ctx["url"]))
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return DEFAULT_BASE


def normalize_search_item(record: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": record.get("id") or record.get("_id") or "",
        "code": record.get("code") or "",
        "title": record.get("name") or record.get("title") or "",
        "status": status_of(record),
        "status_id": status_id_of(record),
        "status_code": status_code_of(record),
        "raise_person": person_of(record, "raisePerson"),
        "priority": priority_of(record),
        "severity": severity_of(record),
        "updated_at": to_ms(
            record.get("modifyTime")
            or record.get("modifiedTime")
            or record.get("modifiedtime")
            or record.get("ts")
        ),
        "url": (ctx or {}).get("url") or "",
    }


def field_display(record: dict[str, Any], key: str) -> str:
    label = record.get(f"{key}_name")
    value = record.get(key)
    if label is not None and label != "":
        return str(label)
    if isinstance(value, str) and re.search(r"<[a-z][\s\S]*>", value, re.IGNORECASE):
        return html_to_text(value)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or value)
    return "" if value is None else str(value)


def fields_of(record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in FIELD_KEYS:
        value = record.get(key)
        if value is None or value == "":
            continue
        display = field_display(record, key)
        if key == "ques_status":
            display = status_of(record)
        elif key == "questionPriority":
            display = priority_of(record)
        elif key == "quesSever":
            display = severity_of(record)
        out.append({"key": key, "name": key, "value": value, "display": display})
    return out


def _attr(tag: str, name: str) -> str:
    match = re.search(_ATTR_RE.format(re.escape(name)), tag, re.IGNORECASE)
    return match.group(2) if match else ""


def normalize_attachment(record: dict[str, Any], base: str | None = None) -> dict[str, Any]:
    root = (base or DEFAULT_BASE).rstrip("/")
    suffix = str(record.get("suffix") or record.get("fileExtension") or "").lstrip(".").lower()
    filename = str(record.get("filename") or record.get("fileName") or record.get("name") or "")
    name = filename
    if filename and suffix and f".{suffix}" not in filename.lower():
        name = f"{filename}.{suffix}"
    file_id = str(
        record.get("attachmentId")
        or record.get("fileId")
        or record.get("id")
        or record.get("shadowLinkCode")
        or ""
    )
    url = str(record.get("url") or record.get("bucketUrl") or record.get("filePath") or "")
    if url.startswith("/"):
        url = root + url
    if not url and file_id:
        url = f"{root}/iuap-apcom-file/rest/v1/file/{file_id}/download"
    mime = str(record.get("mimeType") or record.get("mime") or EXT_MIME.get(suffix, ""))
    return {
        "file_id": file_id,
        "name": name or file_id,
        "size": parse_size(record.get("filesize") or record.get("fileSize") or record.get("size")),
        "mime": mime,
        "url": url,
        "created_at": to_ms(record.get("creationtime") or record.get("ctime") or record.get("created_at")),
        "is_image": mime.startswith("image/"),
        "inline": bool(record.get("inline")),
    }


def inline_images(html: Any, base: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in _IMG_RE.finditer(str(html or "")):
        tag = match.group(0)
        src = _attr(tag, "src")
        if not src:
            continue
        alt = _attr(tag, "alt")
        bucket = re.search(r"/yms-def-bucket/([^?#]+)", src)
        storage_key = ""
        if bucket:
            storage_key = unquote(bucket.group(1))
        from_src = unquote(src.split("?")[0].split("/")[-1] or "")
        name = alt or from_src or "image"
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        out.append(
            normalize_attachment(
                {
                    "fileId": _attr(tag, "fid") or storage_key or from_src or name,
                    "name": name,
                    "size": int(_attr(tag, "size") or 0),
                    "mimeType": EXT_MIME.get(suffix, ""),
                    "url": src,
                    "inline": True,
                },
                base,
            )
        )
    return out


def attachment_groups(record: dict[str, Any]) -> list[dict[str, str]]:
    groups: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, raw in (record or {}).items():
        if not isinstance(raw, str):
            continue
        for group in _GROUP_RE.findall(raw):
            if group in seen:
                continue
            seen.add(group)
            groups.append({"field": str(key), "group_id": group})
    return groups


def attachments_of(record: dict[str, Any], base: str | None = None) -> list[dict[str, Any]]:
    items = record.get("accessoryList")
    if not isinstance(items, list):
        items = record.get("attachments")
    items = items if isinstance(items, list) else []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items + inline_images(record.get("qusDescribe") or record.get("description"), base):
        if not isinstance(item, dict):
            continue
        normalized = normalize_attachment(item, base)
        key = normalized["url"] or normalized["file_id"] or normalized["name"]
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(normalized)
    return out


def normalize_question(
    record: dict[str, Any],
    ctx: dict[str, Any] | None = None,
    *,
    include_raw: bool = False,
) -> dict[str, Any]:
    html = record.get("qusDescribe") or record.get("description") or ""
    base = base_of(ctx)
    out = {
        "id": record.get("id") or record.get("_id") or "",
        "code": record.get("code") or "",
        "title": record.get("name") or record.get("title") or "",
        "url": (ctx or {}).get("url") or "",
        "status": status_of(record),
        "status_id": status_id_of(record),
        "status_code": status_code_of(record),
        "raise_person": person_of(record, "raisePerson"),
        "creator": person_named(record, "creator"),
        "priority": priority_of(record),
        "severity": severity_of(record),
        "description": {"html": html, "text": html_to_text(html)},
        "fields": fields_of(record),
        "attachments": attachments_of(record, base),
        "comment_count": int(record.get("commentCount") or record.get("comment_count") or 0),
        "created_at": to_ms(record.get("creationtime") or record.get("createTime")),
        "updated_at": to_ms(
            record.get("modifyTime") or record.get("modifiedTime") or record.get("modifiedtime")
        ),
    }
    if include_raw:
        out["raw"] = sanitize_raw(record)
    return out


def normalize_comment(record: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    content = record.get("content") or record.get("body") or ""
    files = record.get("fileList") or record.get("files") or record.get("attachments") or []
    base = base_of(ctx)
    return {
        "id": record.get("id") or record.get("_id") or record.get("commentId") or "",
        "author": record.get("creator_userName")
        or record.get("creatorName")
        or record.get("userName")
        or record.get("creator")
        or "",
        "author_id": record.get("yhtUserId") or record.get("creator") or record.get("userId") or "",
        "content": html_to_text(content),
        "content_html": content if isinstance(content, str) else "",
        "created_at": to_ms(
            record.get("ctime")
            or record.get("creationtime")
            or record.get("createdAt")
            or record.get("createTime")
        ),
        "attachments": [
            normalize_attachment(item, base) for item in (files if isinstance(files, list) else [])
            if isinstance(item, dict)
        ],
    }


_SENSITIVE = re.compile(
    r"^(token|cookie|cookies|xsrf|x-xsrf-token|csrf|x-csrf-token|authorization|set-cookie)$",
    re.IGNORECASE,
)


def sanitize_raw(value: Any, depth: int = 0) -> Any:
    if value is None or not isinstance(value, (dict, list)):
        return value
    if depth > 8:
        return None
    if isinstance(value, list):
        return [sanitize_raw(item, depth + 1) for item in value]
    out: dict[str, Any] = {}
    for key, item in value.items():
        if _SENSITIVE.match(str(key)):
            continue
        out[key] = sanitize_raw(item, depth + 1)
    return out


def step_pairs(step_text: Any, expected_text: Any) -> list[dict[str, Any]]:
    steps = _split_steps(step_text)
    expected = _split_steps(expected_text)
    return [
        {
            "step": steps[index] if index < len(steps) else "",
            "expected": expected[index] if index < len(expected) else "",
        }
        for index in range(max(len(steps), len(expected)))
    ]


def _split_steps(value: Any) -> list[str]:
    text = html_to_text(value)
    if not text:
        return []
    parts = re.split(r"\n+|(?<=[。;；])\s*(?=\d+[.、)])|(?=\d+[.、)])", text)
    return [part.strip() for part in parts if part and part.strip()]
