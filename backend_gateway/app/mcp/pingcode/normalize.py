"""PingCode 原始响应 -> MCP 输出结构 (纯函数, 与 AiTestX 的 mcp-normalize 对齐)."""
from __future__ import annotations

import re
from typing import Any

ATLAS_RE = re.compile(r"/atlas/files/public/([A-Za-z0-9_-]+)")
_LINE_BREAK_RE = re.compile(r"\r\n?|\n")

_EXT_MIME = {
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


def rich_to_text(node: Any) -> str:
    """评论 content 可能是富文本 block 数组, 不是 HTML 字符串."""
    if node is None:
        return ""
    if isinstance(node, str):
        return html_to_text(node) if re.search(r"<[a-z][\s\S]*>", node, re.I) else node
    if isinstance(node, bool):
        return "true" if node else "false"
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        return "\n".join(part for part in (rich_to_text(x) for x in node) if part)
    if isinstance(node, dict):
        value = node.get("text")
        if isinstance(value, str):
            return value
        children = node.get("children")
        if isinstance(children, list):
            return "".join(part for part in (rich_to_text(x) for x in children) if part)
        return ""
    return ""


def html_to_text(html: Any) -> str:
    if html is None or html == "":
        return ""
    if not isinstance(html, str):
        return re.sub(r"\n{3,}", "\n\n", rich_to_text(html)).strip()
    text = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(entity, char)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_atlas_refs(html: Any) -> dict[str, list[dict[str, str]]]:
    images: list[dict[str, str]] = []
    attachments: list[dict[str, str]] = []
    if not html or not isinstance(html, str):
        return {"images": images, "attachments": attachments}
    for match in re.finditer(r"""<img[^>]+src=["']([^"']+)["'][^>]*>""", html, re.I):
        hit = ATLAS_RE.search(match.group(1))
        if not hit:
            continue
        alt = re.search(r"""alt=["']([^"']*)["']""", match.group(0), re.I)
        images.append(
            {
                "url": match.group(1),
                "file_id": hit.group(1),
                "name": alt.group(1) if alt else "",
            }
        )
    for match in re.finditer(
        r"""<a[^>]+href=["']([^"']+)["'][^>]*>([\s\S]*?)</a>""", html, re.I
    ):
        hit = ATLAS_RE.search(match.group(1))
        if not hit:
            continue
        attachments.append(
            {
                "url": match.group(1),
                "file_id": hit.group(1),
                "name": html_to_text(match.group(2)) or hit.group(1),
            }
        )
    return {"images": images, "attachments": attachments}


def to_array_props(raw: dict[str, Any]) -> list[dict[str, Any]]:
    value = raw.get("property_values") or raw.get("properties")
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    out: list[dict[str, Any]] = []
    for key, item in value.items():
        if isinstance(item, dict) and not isinstance(item, list) and (
            "key" in item or "property" in item
        ):
            prop = item.get("property") if isinstance(item.get("property"), dict) else {}
            out.append({"key": item.get("key") or prop.get("key") or key, "value": item.get("value")})
        else:
            out.append({"key": key, "value": item})
    return out


def pick_property(raw: dict[str, Any], key: str) -> Any:
    for item in to_array_props(raw):
        prop = item.get("property") if isinstance(item.get("property"), dict) else {}
        if item.get("key") == key or prop.get("key") == key:
            return item.get("value")
    return None


def person_of(value: Any) -> dict[str, str] | None:
    if not value:
        return None
    if isinstance(value, str):
        return {"id": value, "name": ""}
    if not isinstance(value, dict):
        return None
    return {
        "id": str(value.get("id") or value.get("uid") or value.get("_id") or ""),
        "name": str(value.get("name") or value.get("display_name") or value.get("text") or value.get("title") or ""),
    }


def refs_of(raw: dict[str, Any]) -> dict[str, Any]:
    refs = raw.get("refs")
    return refs if isinstance(refs, dict) else {}


def related_of(raw: dict[str, Any], key: str) -> dict[str, str] | None:
    refs = refs_of(raw)
    pairs = (
        refs.get(key),
        refs.get(f"{key}_id"),
        raw.get(key),
        raw.get(f"{key}_id"),
        pick_property(raw, key),
    )
    fallback: dict[str, str] | None = None
    for value in pairs:
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            person = person_of(value)
            if person and person["name"]:
                return person
            if fallback is None and person and person["id"]:
                fallback = person
        elif fallback is None:
            fallback = {"id": str(value), "name": ""}
    return fallback


def display_of(prop: dict[str, Any] | None, value: Any) -> str:
    if value is None or value == "":
        return ""
    options = (prop or {}).get("options") or []
    if options:
        ids = value if isinstance(value, list) else [value]
        rendered = []
        for item in ids:
            option = next(
                (
                    opt
                    for opt in options
                    if str(opt.get("id") or opt.get("_id")) == str(item)
                ),
                None,
            )
            rendered.append(
                str(option.get("name") or option.get("text") or item) if option else str(item)
            )
        return ", ".join(rendered)
    if isinstance(value, list):
        return ", ".join(
            (person_of(item) or {}).get("name") or (person_of(item) or {}).get("id") or str(item)
            if isinstance(item, dict)
            else str(item)
            for item in value
        )
    if isinstance(value, dict):
        person = person_of(value)
        return (person or {}).get("name") or (person or {}).get("id") or str(value)
    return str(value)


def ref_array(refs: Any, key: str) -> list[dict[str, Any]]:
    value = (refs or {}).get(key) if isinstance(refs, dict) else None
    return value if isinstance(value, list) else []


def find_ref(refs: Any, key: str, ident: Any) -> dict[str, Any] | None:
    if ident is None or ident == "":
        return None
    for item in ref_array(refs, key):
        if not isinstance(item, dict):
            continue
        if str(item.get("_id") or item.get("uid") or item.get("id")) == str(ident):
            return item
    return None


def member_of(refs: Any, value: Any) -> dict[str, str] | None:
    ident = value.get("id") or value.get("uid") or value.get("_id") if isinstance(value, dict) else value
    member = find_ref(refs, "members", ident) or find_ref(refs, "users", ident)
    if member:
        return {
            "id": str(member.get("uid") or member.get("_id") or ident),
            "name": str(member.get("display_name") or member.get("name") or ""),
        }
    if not isinstance(value, dict):
        return None
    person = person_of(value)
    return person if person and (person["id"] or person["name"]) else None


def option_of(definition: dict[str, Any] | None, ident: Any) -> dict[str, Any] | None:
    if not definition or ident is None or ident == "":
        return None
    for option in definition.get("options") or []:
        if str(option.get("_id") or option.get("id")) == str(ident):
            return option
    return None


def refs_for(raw: dict[str, Any], ctx_refs: Any = None) -> dict[str, Any]:
    for candidate in (ctx_refs, raw.get("__references"), refs_of(raw)):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def merge_references(target: dict[str, Any], extra: Any) -> dict[str, Any]:
    if not isinstance(extra, dict):
        return target
    for key, value in extra.items():
        if not isinstance(value, list):
            target.setdefault(key, value)
            continue
        existing = target.get(key)
        if not isinstance(existing, list):
            existing = target[key] = []
        seen = {str(item.get("_id") or item.get("uid") or item.get("id")) for item in existing if isinstance(item, dict)}
        for item in value:
            ident = str(item.get("_id") or item.get("uid") or item.get("id")) if isinstance(item, dict) else ""
            if ident and ident not in seen:
                seen.add(ident)
                existing.append(item)
    return target


def _defs_of(raw: dict[str, Any], ctx_refs: Any, schema: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    refs = refs_for(raw, ctx_refs)
    props = refs.get("properties")
    if isinstance(props, list) and props:
        return props
    return schema or []


def normalize_work_item(
    raw: dict[str, Any],
    *,
    references: Any = None,
    schema: list[dict[str, Any]] | None = None,
    base: str = "",
    url: str = "",
) -> dict[str, Any]:
    refs = refs_for(raw, references)
    defs = _defs_of(raw, references, schema)
    html = raw.get("description") or raw.get("description_html") or ""
    if not isinstance(html, str):
        html = rich_to_text(html)
    refs_in_html = extract_atlas_refs(html)

    def find_def(key: str) -> dict[str, Any]:
        return next((d for d in defs if isinstance(d, dict) and d.get("key") == key), {})

    properties = []
    for pv in to_array_props(raw):
        prop = pv.get("property") if isinstance(pv.get("property"), dict) else {}
        key = pv.get("key") or prop.get("key") or ""
        definition = find_def(key)
        properties.append(
            {
                "key": key,
                "name": definition.get("name") or key,
                "type": definition.get("type"),
                "value": pv.get("value"),
                "display": display_of(definition, pv.get("value")),
            }
        )

    identifier = raw.get("whole_identifier") or (
        str(raw["identifier"]) if raw.get("identifier") is not None else ""
    )
    project_ref = find_ref(refs, "projects", raw.get("project_id")) or refs.get("project")
    type_ref = find_ref(refs, "work_item_types", raw.get("type_id"))
    state_ref = find_ref(refs, "states", raw.get("state_id"))
    assignee_ref = member_of(refs, raw.get("assignee"))
    priority_def = find_def("priority")
    priority_option = option_of(priority_def, raw.get("priority"))

    project = (
        {"id": project_ref.get("_id"), "name": project_ref.get("name") or ""}
        if isinstance(project_ref, dict)
        else related_of(raw, "project")
    )
    type_ref_norm = (
        {"id": type_ref.get("_id"), "name": type_ref.get("name") or ""}
        if isinstance(type_ref, dict)
        else related_of(raw, "type")
    )
    state = (
        {"id": state_ref.get("_id"), "name": state_ref.get("name") or ""}
        if isinstance(state_ref, dict)
        else related_of(raw, "state")
    )
    assignee = assignee_ref or related_of(raw, "assignee")
    priority = (
        {"id": str(raw.get("priority")), "name": priority_option.get("text") or priority_option.get("name") or ""}
        if priority_option
        else related_of(raw, "priority")
    )

    attachments: list[dict[str, Any]] = []
    seen_attachments: set[str] = set()
    for item in ref_array(refs, "attachments"):
        normalized = normalize_attachment(item, base)
        if not normalized["file_id"] and not normalized["attachment_id"]:
            continue
        attachments.append(normalized)
        seen_attachments.add(normalized["attachment_id"] or normalized["file_id"])
    raw_attachments = raw.get("attachments") if isinstance(raw.get("attachments"), list) else []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        att_id = item.get("attachment_id") or item.get("_id")
        if att_id and str(att_id) in seen_attachments:
            continue
        versions = item.get("versions") if isinstance(item.get("versions"), list) else []
        merged = {**item, **(versions[0] if versions and isinstance(versions[0], dict) else {})}
        merged["attachment_id"] = att_id
        normalized = normalize_attachment(merged, base)
        if not normalized["file_id"]:
            continue
        attachments.append(normalized)
        seen_attachments.add(normalized["attachment_id"] or normalized["file_id"])
    for item in refs_in_html["attachments"]:
        if any(att.get("file_id") == item["file_id"] for att in attachments):
            continue
        attachments.append(
            normalize_attachment(
                {"file_id": item["file_id"], "name": item["name"], "url": item["url"]}, base
            )
        )

    participants_value = raw.get("participants")
    if participants_value is None:
        participants_value = pick_property(raw, "participants")
    participants_raw = participants_value if isinstance(participants_value, list) else ([participants_value] if participants_value else [])
    participants: list[dict[str, str]] = []
    seen_people: set[str] = set()
    for item in participants_raw:
        person = member_of(refs, item)
        if not person:
            continue
        ident = str(person.get("id") or person.get("name"))
        if ident in seen_people:
            continue
        seen_people.add(ident)
        participants.append(person)

    return {
        "id": raw.get("_id") or raw.get("id") or "",
        "identifier": identifier,
        "title": raw.get("title") or "",
        "url": url,
        "project": {"id": (project or {}).get("id") or raw.get("project_id") or "", "name": (project or {}).get("name") or ""},
        "type": {"id": (type_ref_norm or {}).get("id") or raw.get("type_id") or "", "name": (type_ref_norm or {}).get("name") or ""},
        "state": state,
        "assignee": assignee,
        "participants": participants,
        "priority": priority,
        "created_at": raw.get("created_at") or 0,
        "updated_at": raw.get("updated_at") or 0,
        "comment_count": raw.get("comment_count") or 0,
        "attachment_count": raw.get("attachment_count") if raw.get("attachment_count") is not None else len(attachments),
        "description": {"html": html, "text": html_to_text(html)},
        "properties": properties,
        "images": refs_in_html["images"],
        "attachments": attachments,
    }


def normalize_search_item(
    raw: dict[str, Any],
    *,
    references: Any = None,
    schema: list[dict[str, Any]] | None = None,
    url: str = "",
) -> dict[str, Any]:
    refs = refs_for(raw, references)
    defs = _defs_of(raw, references, schema)

    def find_def(key: str) -> dict[str, Any]:
        return next((d for d in defs if isinstance(d, dict) and d.get("key") == key), {})

    identifier = raw.get("whole_identifier") or (
        str(raw["identifier"]) if raw.get("identifier") is not None else ""
    )
    state_ref = find_ref(refs, "states", raw.get("state_id"))
    type_ref = find_ref(refs, "work_item_types", raw.get("type_id"))
    assignee_ref = member_of(refs, raw.get("assignee"))
    priority_option = option_of(find_def("priority"), raw.get("priority"))

    state = (
        str(state_ref.get("name") or state_ref.get("_id"))
        if state_ref
        else display_of(find_def("state"), related_of(raw, "state") or raw.get("state_id"))
    )
    assignee = (
        str((assignee_ref or {}).get("name") or (assignee_ref or {}).get("id"))
        if assignee_ref
        else display_of(find_def("assignee"), related_of(raw, "assignee") or raw.get("assignee"))
    )
    type_name = (
        str((type_ref or {}).get("name") or (type_ref or {}).get("_id"))
        if type_ref
        else display_of(find_def("type"), related_of(raw, "type") or raw.get("type_id"))
    )

    return {
        "id": raw.get("_id") or raw.get("id") or "",
        "identifier": identifier,
        "title": raw.get("title") or "",
        "state": state,
        "assignee": assignee,
        "type": type_name,
        "priority": (priority_option.get("text") or priority_option.get("name"))
        if priority_option
        else display_of(find_def("priority"), raw.get("priority")),
        "comment_count": raw.get("comment_count") or 0,
        "attachment_count": raw.get("attachment_count") or 0,
        "updated_at": raw.get("updated_at") or 0,
        "url": url,
    }


def normalize_comment(
    raw: dict[str, Any],
    *,
    references: Any = None,
    names: dict[str, str] | None = None,
    base: str = "",
) -> dict[str, Any]:
    content = raw.get("content")
    if content is None:
        content = raw.get("body") or ""
    author = member_of(references, raw.get("created_by") or raw.get("author")) or person_of(
        raw.get("created_by") or raw.get("author")
    )
    if author and not author.get("name") and names:
        author["name"] = names.get(author["id"], "")
    attachments = [
        normalize_attachment(item, base)
        for item in (raw.get("attachments") if isinstance(raw.get("attachments"), list) else [])
        if isinstance(item, dict)
    ]
    return {
        "id": raw.get("_id") or raw.get("id") or "",
        "author": author,
        "created_at": raw.get("created_at") or 0,
        "content_html": content,
        "content_text": html_to_text(content),
        "attachments": attachments,
    }


def normalize_attachment(raw: dict[str, Any], base: str = "") -> dict[str, Any]:
    addition = raw.get("addition") if isinstance(raw.get("addition"), dict) else {}
    name = raw.get("title") or raw.get("name") or raw.get("filename") or ""
    ext = str(addition.get("ext") or (name.rsplit(".", 1)[-1] if "." in name else "")).lower()
    mime = (
        raw.get("mime_type")
        or addition.get("mime_type")
        or addition.get("mime")
        or raw.get("mime")
        or _EXT_MIME.get(ext, "")
    )
    file_id = raw.get("file_id") or raw.get("_id") or raw.get("id") or ""
    token = raw.get("token") or ""
    attachment_id = raw.get("attachment_id") or (raw.get("_id") if raw.get("type") is not None else "")
    url = raw.get("url") or ""
    if not url and token and base:
        url = f"{base}/atlas/file/download-url?action=download&token={token}"
    if not url and file_id and base:
        url = f"{base}/atlas/files/public/{file_id}"
    if not name and file_id:
        name = f"{file_id}.{ext}" if ext else file_id
    return {
        "attachment_id": attachment_id,
        "file_id": file_id,
        "name": name,
        "size": raw.get("size") or addition.get("size") or raw.get("filesize") or 0,
        "mime": mime,
        "url": url,
        "token": token,
        "is_image": str(mime).startswith("image/") or bool(re.match(r"^(png|jpe?g|gif|webp|bmp)$", ext)),
    }
