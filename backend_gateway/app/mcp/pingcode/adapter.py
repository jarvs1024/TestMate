"""PingCode 域工具适配层: 结构化输出、错误收敛与幂等写入."""
from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.core.config import settings
from app.integrations import credentials
from app.integrations.pingcode import client
from app.integrations.pingcode import token_manager
from app.integrations.redis import redis_client
from app.mcp.common.context import McpContext
from app.mcp.common.errors import McpRuntimeError
from app.mcp.pingcode import normalize
from app.mcp.pingcode.templates import render_description

PROVIDER = "pingcode"
MAX_BYTES = 20 * 1024 * 1024
IDEMPOTENCY_TTL = 600
_SCAN_PAGE = 100
_SCAN_LIMIT = 5000

_NOT_CONFIGURED_MESSAGE = "尚未配置 PingCode 账号，请在个人中心「平台认证」中配置"


def _user_id(ctx: McpContext) -> int:
    return int(ctx.principal.user.id)


def _value_of(payload: Any) -> Any:
    # 与 PingCodeClient 同规则: data 只有 value 一个键时才解包, 否则保留 references/count.
    if isinstance(payload, dict) and set(payload) == {"value"}:
        return payload["value"]
    return payload


def _record_of(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("value"), dict):
        return payload["value"]
    value = _value_of(payload)
    return value if isinstance(value, dict) else {}


def _list_of(payload: Any) -> list[dict[str, Any]]:
    value = _value_of(payload)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("value", "values", "items", "list"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    return []


def _references_of(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        for source in (payload, payload.get("value")):
            if isinstance(source, dict) and isinstance(source.get("references"), dict):
                return source["references"]
    return {}


async def _raw(ctx: McpContext, method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await token_manager.request(_user_id(ctx), method, path, **kwargs)
    except token_manager.IntegrationNotConfigured as exc:
        raise McpRuntimeError(
            "integration_not_configured", str(exc) or _NOT_CONFIGURED_MESSAGE
        ) from exc
    except token_manager.IntegrationReauthRequired as exc:
        raise McpRuntimeError(
            "integration_reauth_required",
            str(exc) or "PingCode 登录态已失效，请在个人中心重新绑定账号",
        ) from exc
    except client.PingCodeSessionExpired as exc:
        raise McpRuntimeError(
            "integration_reauth_required", "PingCode 登录态已失效，请稍后重试或重新绑定"
        ) from exc
    except client.PingCodeUnavailable as exc:
        raise McpRuntimeError(
            "integration_unavailable", f"PingCode 暂不可达: {exc}"
        ) from exc


async def _request(ctx: McpContext, method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await _raw(ctx, method, path, **kwargs)
    except client.PingCodeBusinessError as exc:
        raise McpRuntimeError(
            "pingcode_error", str(exc) or "PingCode 返回业务错误"
        ) from exc


def _base_url() -> str:
    return settings.PINGCODE_BASE_URL.rstrip("/")


def _work_item_url(work_item_id: str, identifier: str) -> str:
    if not work_item_id:
        return ""
    return f"{_base_url()}/pjm/workitems/{work_item_id}?#{identifier or ''}"


async def _get_json(ctx: McpContext, path: str, params: dict[str, Any] | None = None) -> Any:
    return await _request(ctx, "GET", path, params=params)


async def whoami(ctx: McpContext) -> dict[str, Any]:
    record = await credentials.get(ctx.session, _user_id(ctx), PROVIDER)
    if record is None:
        return {"configured": False, "provider": PROVIDER}
    return {
        "configured": True,
        "provider": PROVIDER,
        "username": record.username,
        "status": record.status,
        "last_login_at": record.last_login_at,
        "last_error": record.last_error,
    }


async def list_projects(ctx: McpContext) -> dict[str, Any]:
    payload = await _get_json(
        ctx, "/api/agile/projects/select-options", {"can_create_work_item": 1}
    )
    items = [
        {
            "id": project.get("_id"),
            "identifier": project.get("identifier") or "",
            "name": project.get("name") or "",
            "template_type": project.get("template_type") or "",
            "is_local_configure": project.get("is_local_configure") == 1,
        }
        for project in _list_of(payload)
    ]
    return {"items": items}


async def _project_id_by_identifier(ctx: McpContext, identifier: str) -> str:
    wanted = str(identifier or "").strip().upper()
    payload = await _get_json(
        ctx, "/api/agile/projects/select-options", {"can_create_work_item": 1}
    )
    for project in _list_of(payload):
        if str(project.get("identifier") or "").strip().upper() == wanted:
            return str(project.get("_id") or "")
    raise McpRuntimeError("not_found", f"未找到项目 {identifier}")


async def list_work_item_types(ctx: McpContext, project_id: str) -> dict[str, Any]:
    payload = await _get_json(
        ctx, f"/api/agile/projects/{project_id}/work-item-types", {"is_addable": 1}
    )
    items = []
    for item in _list_of(payload):
        required = []
        for binding in item.get("required_property_bindings") or []:
            key = binding.get("key") or binding.get("property_key") if isinstance(binding, dict) else None
            if key:
                required.append(key)
        items.append(
            {
                "id": item.get("_id"),
                "type_id": item.get("type_id") or item.get("_id"),
                "name": item.get("name") or "",
                "required_keys": required,
            }
        )
    return {"items": items}


def _schema_fields(properties: Any) -> list[dict[str, Any]]:
    fields = []
    for prop in properties if isinstance(properties, list) else []:
        if not isinstance(prop, dict):
            continue
        validators = prop.get("validators") if isinstance(prop.get("validators"), dict) else {}
        fields.append(
            {
                "key": prop.get("key"),
                "name": prop.get("name") or prop.get("key") or "",
                "type": prop.get("type"),
                "required": bool(validators.get("is_required")),
                "options": prop.get("options") or [],
                "default_value": prop.get("default_value"),
            }
        )
    return fields


async def get_property_schema(
    ctx: McpContext,
    project_id: str,
    work_item_type_id: str,
    project_template_type: str | None = None,
) -> dict[str, Any]:
    base_params = {
        "scope[project_template_type]": project_template_type or "waterfall",
        "scope[work_item_type]": work_item_type_id,
    }
    used_global = False
    try:
        payload = await _raw(
            ctx,
            "GET",
            "/api/agile/work-item/creation-template/properties",
            params={**base_params, "scope[project_id]": project_id},
        )
    except client.PingCodeBusinessError as exc:
        if exc.status != 404 and exc.code != 404:
            raise McpRuntimeError("pingcode_error", str(exc)) from exc
        used_global = True
        payload = await _raw(
            ctx,
            "GET",
            "/api/agile/work-item/creation-template/properties",
            params=base_params,
        )
    properties = _record_of(payload).get("properties")
    return {
        "used_global_fallback": used_global,
        "fields": _schema_fields(properties),
    }


async def list_members(ctx: McpContext, project_id: str) -> dict[str, Any]:
    roles_payload = await _get_json(ctx, f"/api/agile/projects/{project_id}/roles")
    roles = _record_of(roles_payload).get("roles")
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for role in roles if isinstance(roles, list) else []:
        role_id = role.get("_id") if isinstance(role, dict) else None
        if not role_id:
            continue
        for page in range(1, 21):
            page_payload = await _get_json(
                ctx,
                f"/api/agile/projects/{project_id}/roles/{role_id}/members",
                {"page": page, "ps": 200},
            )
            batch = _list_of(page_payload)
            for member in batch:
                uid = member.get("uid") or member.get("id") or member.get("_id")
                if not uid or str(uid) in seen:
                    continue
                seen.add(str(uid))
                members.append(
                    {
                        "id": str(uid),
                        "name": member.get("display_name") or member.get("name") or "",
                    }
                )
            if len(batch) < 200:
                break
    return {"items": members}


async def _scan_work_items(
    ctx: McpContext,
    params: dict[str, Any],
    *,
    type_id: str | None,
    assignee_id: str | None,
) -> dict[str, Any]:
    collected: list[dict[str, Any]] = []
    references: dict[str, Any] = {}
    total = 0
    for page in range(0, (_SCAN_LIMIT + _SCAN_PAGE - 1) // _SCAN_PAGE):
        payload = await _get_json(
            ctx,
            "/api/agile/work-items",
            {**params, "pi": page, "ps": _SCAN_PAGE, "page_index": page, "page_size": _SCAN_PAGE},
        )
        value = _value_of(payload)
        batch = value if isinstance(value, list) else []
        if isinstance(value, dict):
            batch = value.get("value") or value.get("values") or []
            total = value.get("count") or value.get("total") or total
        collected.extend(item for item in batch if isinstance(item, dict))
        normalize.merge_references(references, _references_of(payload))
        if len(batch) < _SCAN_PAGE or (total and len(collected) >= total):
            break
    filtered = collected
    if type_id:
        filtered = [item for item in filtered if (item.get("type_id") or item.get("type")) == type_id]
    if assignee_id:
        filtered = [item for item in filtered if item.get("assignee") == assignee_id]
    return {"items": filtered, "total": len(filtered), "references": references, "scanned": len(collected)}


async def search_work_items(
    ctx: McpContext,
    *,
    project_id: str | None = None,
    project_identifier: str | None = None,
    keyword: str | None = None,
    type_id: str | None = None,
    state_id: str | None = None,
    state_ids: list[str] | None = None,
    assignee_id: str | None = None,
    updated_after: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    resolved = project_id or (
        await _project_id_by_identifier(ctx, project_identifier) if project_identifier else ""
    )
    if not resolved:
        raise McpRuntimeError("invalid_arguments", "project_id 或 project_identifier 至少提供一个")
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    filters = state_ids or ([state_id] if state_id else [])
    params: dict[str, Any] = {"project_id": resolved}
    if keyword:
        params["keywords"] = keyword
    if filters:
        params["state_ids"] = ",".join(str(item) for item in filters)
    if updated_after:
        params["updated_at"] = f">={int(updated_after)}"

    if type_id or assignee_id:
        scanned = await _scan_work_items(ctx, params, type_id=type_id, assignee_id=assignee_id)
        start = (page - 1) * page_size
        page_items = scanned["items"][start : start + page_size]
        items = [
            normalize.normalize_search_item(
                item,
                references=scanned["references"],
                url=_work_item_url(str(item.get("_id") or ""), str(item.get("whole_identifier") or "")),
            )
            for item in page_items
        ]
        return {
            "total": scanned["total"],
            "count": len(items),
            "page": page,
            "page_size": page_size,
            "has_more": start + page_size < scanned["total"],
            "filtered_client_side": True,
            "scanned": scanned["scanned"],
            "items": items,
        }

    payload = await _get_json(
        ctx,
        "/api/agile/work-items",
        {**params, "pi": page - 1, "ps": page_size, "page_index": page - 1, "page_size": page_size},
    )
    raw_items = _list_of(payload)
    value = _value_of(payload)
    total = 0
    page_count = None
    if isinstance(value, dict):
        total = value.get("count") or value.get("total") or 0
        page_count = value.get("page_count")
    references = _references_of(payload)
    items = [
        normalize.normalize_search_item(
            item,
            references=references,
            url=_work_item_url(str(item.get("_id") or ""), str(item.get("whole_identifier") or "")),
        )
        for item in raw_items
    ]
    has_more = page < page_count if page_count is not None else bool(total and page * page_size < total)
    return {
        "total": total,
        "count": len(items),
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "items": items,
    }


async def _find_work_item_id(ctx: McpContext, identifier: str) -> dict[str, Any] | None:
    payload = await _raw(
        ctx,
        "GET",
        "/api/agile/work-items/dashboard/search",
        params={"keywords": identifier, "pi": 0, "ps": 20},
    )
    wanted = str(identifier).strip().upper()
    for item in _list_of(payload):
        whole = str(item.get("whole_identifier") or item.get("identifier") or "").upper()
        if whole == wanted:
            return item
    return None


async def get_work_item(
    ctx: McpContext,
    *,
    id: str | None = None,
    identifier: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    if not id and not identifier:
        raise McpRuntimeError("invalid_arguments", "id 或 identifier 至少提供一个")

    work_item_id = id
    resolved_project = project_id or ""
    if not work_item_id:
        found = await _find_work_item_id(ctx, identifier or "")
        if found is None and not resolved_project:
            resolved_project = await _project_id_by_identifier(
                ctx, str(identifier or "").split("-")[0]
            )
        if found is None and resolved_project:
            page_payload = await _get_json(
                ctx,
                "/api/agile/work-items",
                {"project_id": resolved_project, "keywords": identifier, "pi": 0, "ps": 100},
            )
            wanted = str(identifier).strip().upper()
            for item in _list_of(page_payload):
                whole = str(item.get("whole_identifier") or "").upper()
                if whole == wanted:
                    found = item
                    break
        if found is None:
            raise McpRuntimeError("not_found", f"未找到工单 {identifier}")
        work_item_id = str(found.get("_id") or "")
        resolved_project = resolved_project or str(found.get("project_id") or "")
        if not work_item_id:
            raise McpRuntimeError("not_found", f"未找到工单 {identifier}")

    payload = await _get_json(ctx, f"/api/agile/work-items/{work_item_id}")
    raw = _record_of(payload)
    references = _references_of(payload)
    resolved_project = (
        str(raw.get("project_id") or "") or normalize.pick_property(raw, "project_id") or resolved_project
    )
    type_ref = normalize.related_of(raw, "type")
    type_id = (type_ref or {}).get("id") or raw.get("type_id") or ""

    schema: list[dict[str, Any]] = []
    if resolved_project and type_id:
        try:
            schema = (await get_property_schema(ctx, resolved_project, str(type_id)))["fields"]
        except McpRuntimeError:
            schema = []

    return normalize.normalize_work_item(
        raw,
        references=references,
        schema=schema,
        base=_base_url(),
        url=_work_item_url(str(raw.get("_id") or work_item_id), str(raw.get("whole_identifier") or "")),
    )


async def list_comments(
    ctx: McpContext,
    id: str,
    *,
    page: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    payload = await _get_json(
        ctx,
        f"/api/agile/work-items/{id}/comments",
        {"pi": max(0, int(page or 1) - 1), "ps": min(100, int(page_size or 20))},
    )
    value = _value_of(payload)
    raw_items = _list_of(payload)
    total = len(raw_items)
    if isinstance(value, dict):
        total = value.get("count") or value.get("total") or total
    references = _references_of(payload)
    names = {
        str(user.get("uid") or user.get("id") or user.get("_id")): user.get("display_name")
        or user.get("name")
        or ""
        for user in normalize.ref_array(references, "users")
    }
    items = [
        normalize.normalize_comment(item, references=references, names=names, base=_base_url())
        for item in raw_items
    ]
    return {"total": total, "items": items}


async def list_attachments(ctx: McpContext, id: str) -> dict[str, Any]:
    payload = await _get_json(ctx, f"/api/agile/work-items/{id}")
    raw = _record_of(payload)
    references = _references_of(payload)
    candidates = normalize.ref_array(references, "attachments")
    if not candidates:
        candidates = [item for item in raw.get("attachments") or [] if isinstance(item, dict)]
    items = []
    for item in candidates:
        if item.get("file_id"):
            normalized = normalize.normalize_attachment(item, _base_url())
        else:
            versions = item.get("versions") if isinstance(item.get("versions"), list) else []
            merged = {**item, **(versions[0] if versions and isinstance(versions[0], dict) else {})}
            merged["attachment_id"] = item.get("attachment_id") or item.get("_id")
            normalized = normalize.normalize_attachment(merged, _base_url())
        if normalized["file_id"]:
            items.append(normalized)
    return {"items": items}


def _allowed_host() -> str:
    return (urlparse(_base_url()).hostname or "").lower()


def _url_token(url: str) -> str:
    values = parse_qs(urlparse(url).query)
    return (values.get("token") or [""])[0]


def _with_token(url: str, token: str) -> str:
    """atlas 下载只认 query token; 补到 URL 上, 已带 token 时保持原样."""
    if not token:
        return url
    parsed = urlparse(url)
    if (parse_qs(parsed.query).get("token") or [""])[0]:
        return url
    separator = "&" if parsed.query else "?"
    return f"{url}{separator}{urlencode({'token': token})}"


async def _download_bytes(
    url: str,
    token: str,
    max_bytes: int,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, bytes]:
    # 不带 Authorization: 302 会跳到 S3 预签名地址, 多余的认证头会让 S3 返回 400.
    target = _with_token(url, token)
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, trust_env=False, transport=transport
        ) as http:
            async with http.stream("GET", target) as response:
                if response.status_code >= 400:
                    raise McpRuntimeError(
                        "download_failed", f"附件下载失败 (HTTP {response.status_code})"
                    )
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        raise McpRuntimeError("attachment_too_large", "附件超过大小上限")
    except httpx.HTTPError as exc:
        raise McpRuntimeError("download_failed", "附件下载失败") from exc
    if content_type == "application/json":
        try:
            payload = json.loads(bytes(buffer))
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            code = payload.get("code")
            if "error" in payload or (
                isinstance(code, int) and not isinstance(code, bool) and code >= 400
            ):
                message = payload.get("message") or "附件下载失败"
                raise McpRuntimeError("download_failed", str(message))
    return content_type, bytes(buffer)


async def _public_file_token(ctx: McpContext) -> str:
    try:
        payload = await _raw(ctx, "GET", "/api/typhon/secret/file/public-image-token")
    except (McpRuntimeError, client.PingCodeBusinessError):
        return ""
    if isinstance(payload, dict):
        value = payload.get("value")
        return value if isinstance(value, str) else ""
    return payload if isinstance(payload, str) else ""


async def download_attachment(
    ctx: McpContext,
    *,
    url: str | None = None,
    file_id: str | None = None,
    name: str | None = None,
    max_bytes: int | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() != _allowed_host():
            raise McpRuntimeError("invalid_arguments", "附件地址必须与 PingCode 同源")
        target = url
    elif file_id:
        target = f"{_base_url()}/atlas/files/public/{file_id}"
    else:
        raise McpRuntimeError("invalid_arguments", "url 或 file_id 至少提供一个")

    access_token = token or _url_token(target)
    if not access_token and "/atlas/files/public/" in target:
        access_token = await _public_file_token(ctx)

    limit = min(int(max_bytes or MAX_BYTES), MAX_BYTES)
    content_type, data = await _download_bytes(target, access_token, limit)
    result: dict[str, Any] = {
        "content_type": content_type,
        "bytes": len(data),
        "name": name or (urlparse(target).path.rsplit("/", 1)[-1] if target else ""),
    }
    if content_type.startswith("image/"):
        result["base64"] = base64.b64encode(data).decode("ascii")
        return result
    result["url"] = target
    result["token"] = access_token
    return result


def _strip_html(html: str) -> str:
    return normalize.html_to_text(html)


async def preview_work_item(
    ctx: McpContext,
    *,
    project_id: str,
    work_item_type_id: str,
    properties: dict[str, Any],
    project_template_type: str | None = None,
    description_template: str | None = None,
    description_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = await get_property_schema(
        ctx, project_id, work_item_type_id, project_template_type
    )
    props = dict(properties or {})
    if description_template:
        if description_template != "standard":
            raise McpRuntimeError(
                "invalid_arguments", "description_template 只支持 standard"
            )
        props["description"] = render_description(description_fields or {})
    props = _coerce_properties(props, schema["fields"])

    def injected(key: str) -> bool:
        if key == "project_id":
            return bool(project_id)
        if key == "type":
            return bool(work_item_type_id)
        if key == "participants":
            return props.get("participants") is not None or props.get("assignee") is not None
        return False

    missing = [
        field["key"]
        for field in schema["fields"]
        if field["required"]
        and not injected(field["key"])
        and props.get(field["key"]) in (None, "")
    ]
    return {
        "ok": not missing,
        "missing_required": missing,
        "payload": {
            "project_id": project_id,
            "work_item_type_id": work_item_type_id,
            "project_template_type": project_template_type or "waterfall",
            "properties": props,
            "description_text": _strip_html(props.get("description", "")),
        },
    }


_MULTI_VALUE_TYPES = {16, 20}


def _coerce_properties(
    properties: dict[str, Any], fields: list[dict[str, Any]]
) -> dict[str, Any]:
    """按字段类型规范入参: 多选必须数组, 日期必须 {date, with_time}.

    PingCode 对多选传标量、日期传裸数字都直接 400 "invalidate input data value".
    MCP 调用方从 schema 只能看到选项 _id, 很容易按单个值传, 这里统一兜住.
    """
    kinds = {field.get("key"): field.get("type") for field in fields}
    coerced = dict(properties)
    for key, value in coerced.items():
        kind = kinds.get(key)
        if kind in _MULTI_VALUE_TYPES and isinstance(value, str):
            coerced[key] = [value] if value else []
        elif (
            kind == 4
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            coerced[key] = {"date": int(value), "with_time": 0}
    return coerced


def _encode_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    if isinstance(value, dict) and value.get("uid"):
        return value["uid"]
    return value


async def create_work_item(
    ctx: McpContext,
    *,
    project_id: str,
    work_item_type_id: str,
    properties: dict[str, Any],
    confirm: bool,
    client_request_id: str,
    project_template_type: str | None = None,
    description_template: str | None = None,
    description_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if confirm is not True:
        raise McpRuntimeError(
            "confirmation_required", "写操作需要显式 confirm=true 确认后才会提交"
        )
    props = dict(properties or {})
    if description_template:
        if description_template != "standard":
            raise McpRuntimeError(
                "invalid_arguments", "description_template 只支持 standard"
            )
        props["description"] = render_description(description_fields or {})

    key = f"mcp:pingcode:create:{_user_id(ctx)}:{client_request_id}"
    async with redis_client() as redis:
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)

    # schema 拿不到时退回原样提交 —— 建单本身仍交给 PingCode 校验, 不因预检失败阻断.
    try:
        schema = await get_property_schema(
            ctx, project_id, work_item_type_id, project_template_type
        )
    except McpRuntimeError:
        fields: list[dict[str, Any]] = []
    else:
        fields = schema["fields"]
    props = _coerce_properties(props, fields)

    values = [{"key": name, "value": _encode_value(value)} for name, value in props.items()]
    inserted = {item["key"] for item in values}
    if "project_id" not in inserted:
        values.append({"key": "project_id", "value": project_id})
    if "type" not in inserted:
        values.append({"key": "type", "value": work_item_type_id})
    if "participants" not in inserted and props.get("assignee"):
        values.append({"key": "participants", "value": [_encode_value(props["assignee"])]})

    payload = await _request(
        ctx, "POST", "/api/agile/work-item", json={"property_values": values}
    )
    raw = _record_of(payload)
    work_item_id = str(raw.get("_id") or raw.get("id") or "")
    identifier = str(raw.get("whole_identifier") or raw.get("identifier") or "")
    result = {
        "id": work_item_id,
        "identifier": identifier,
        "url": _work_item_url(work_item_id, identifier),
        "raw": raw,
    }
    async with redis_client() as redis:
        await redis.set(key, json.dumps(result, ensure_ascii=False, default=str), ex=IDEMPOTENCY_TTL)
    return result


async def add_comment(
    ctx: McpContext, *, id: str, content: str, confirm: bool
) -> dict[str, Any]:
    if confirm is not True:
        raise McpRuntimeError(
            "confirmation_required", "写操作需要显式 confirm=true 确认后才会提交"
        )
    payload = await _request(
        ctx, "POST", f"/api/agile/work-items/{id}/comment", json={"content": content}
    )
    value = _record_of(payload)
    comment_id = value.get("_id") or value.get("id") or ""
    return {"ok": True, "id": str(comment_id)}
