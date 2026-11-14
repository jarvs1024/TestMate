"""PingCode 域工具适配层: 结构化输出、错误收敛与幂等写入."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

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

logger = logging.getLogger(__name__)

PROVIDER = "pingcode"
DEFAULT_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
IDEMPOTENCY_TTL = 600
UPLOAD_SCOPE_ATTACHMENT = 1
UPLOAD_SCOPE_INLINE = 3
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
        message = str(exc)
        if re.search(r"HTTP 5\d{2}", message):
            raise McpRuntimeError(
                "integration_unavailable",
                f"PingCode 内部服务异常 ({message})，请稍后重试",
            ) from exc
        raise McpRuntimeError(
            "integration_unavailable", f"PingCode 暂不可达: {message}"
        ) from exc


def _localize_error_message(message: str) -> str:
    text = str(message or "").strip()
    lower = text.lower()
    if "内部服务异常" in text or "internal server error" in lower:
        return "PingCode 内部服务异常，请稍后重试"
    if "test library not found" in lower:
        return "未找到用例库: 请确认 library_id（可调用 pingcode_case_list_libraries 获取）"
    if "not found project" in lower:
        return "未找到项目: 请确认 project_id（可调用 pingcode_common_list_projects 获取）"
    if "missing fileid" in lower:
        return "缺少文件标识 fileId"
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    return f"PingCode 返回错误: {text}" if text else "PingCode 返回业务错误"


def _business_failure(exc: client.PingCodeBusinessError, *, what: str, hint: str) -> McpRuntimeError:
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    message = str(exc)
    if status == 404 or code == 404 or "not found" in message.lower():
        return McpRuntimeError("not_found", f"未找到{what}; {hint}")
    return McpRuntimeError("pingcode_error", _localize_error_message(message))


async def _request(ctx: McpContext, method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await _raw(ctx, method, path, **kwargs)
    except client.PingCodeBusinessError as exc:
        raise McpRuntimeError(
            "pingcode_error", _localize_error_message(str(exc))
        ) from exc


def _base_url() -> str:
    return settings.PINGCODE_BASE_URL.rstrip("/")


def _work_item_url(work_item_id: str, identifier: str) -> str:
    if not work_item_id:
        return ""
    return f"{_base_url()}/pjm/workitems/{work_item_id}?#{identifier or ''}"


async def _get_json(ctx: McpContext, path: str, params: dict[str, Any] | None = None) -> Any:
    return await _request(ctx, "GET", path, params=params)


async def _identity(ctx: McpContext) -> dict[str, Any] | None:
    """真实登录的 PingCode 用户; 凭据里的 username 只是登录账号."""
    payload: Any = None
    for attempt in (1, 2):
        try:
            payload = await _get_json(ctx, "/api/typhon/account/me")
            break
        except Exception:  # 身份读取失败不影响配置状态展示
            if attempt == 2:
                logger.warning("pingcode.identity_failed", exc_info=True)
                return None
            # 进程刚启动时的首次外连偶发 ReadError, 重试一次即可恢复
            await asyncio.sleep(0.5)
    record = _record_of(payload)
    me = record.get("me") if isinstance(record.get("me"), dict) else record
    uid = str(me.get("uid") or me.get("_id") or "")
    display_name = str(me.get("display_name") or me.get("name") or "")
    if not uid and not display_name:
        logger.warning("pingcode.identity_empty_payload")
        return None
    return {
        "uid": uid,
        "name": str(me.get("name") or ""),
        "display_name": display_name,
        "email": str(me.get("email") or ""),
        "mobile": str(me.get("mobile") or ""),
    }


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
        "user": await _identity(ctx),
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
    try:
        payload = await _raw(
            ctx, "GET", f"/api/agile/projects/{project_id}/work-item-types", params={"is_addable": 1}
        )
    except client.PingCodeBusinessError as exc:
        raise _business_failure(
            exc,
            what=f"项目 {project_id}",
            hint="请调用 pingcode_common_list_projects 获取项目 _id",
        ) from exc
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


async def _resolve_project(ctx: McpContext, project_id: str) -> dict[str, Any]:
    payload = await _get_json(
        ctx, "/api/agile/projects/select-options", {"can_create_work_item": 1}
    )
    for project in _list_of(payload):
        if str(project.get("_id") or "") == str(project_id):
            return {
                "template_type": str(project.get("template_type") or "waterfall"),
                "is_local_configure": project.get("is_local_configure") == 1,
            }
    raise McpRuntimeError(
        "invalid_arguments",
        f"项目 {project_id} 不在当前账号可提单项目列表中，"
        "无法确定项目字段模板。请先调用 pingcode_common_list_projects 获取项目 _id。",
    )


async def _ensure_work_item_type(
    ctx: McpContext, project_id: str, work_item_type_id: str
) -> None:
    types = (await list_work_item_types(ctx, project_id))["items"]
    wanted = str(work_item_type_id)
    for item in types:
        if wanted in {str(item.get("id") or ""), str(item.get("type_id") or "")}:
            return
    listing = ", ".join(
        f"{item.get('name')}({item.get('id') or item.get('type_id')})"
        for item in types[:10]
        if item.get("name")
    )
    raise McpRuntimeError(
        "invalid_arguments",
        f"工单类型 {work_item_type_id} 不在项目 {project_id} 的可选类型中; "
        f"可选: {listing or '无'}; 可调用 pingcode_issue_list_types 查询",
    )


async def get_property_schema(
    ctx: McpContext,
    project_id: str,
    work_item_type_id: str,
    project_template_type: str | None = None,
    *,
    allow_global_fallback: bool = True,
    validate_type: bool = False,
) -> dict[str, Any]:
    if validate_type:
        await _ensure_work_item_type(ctx, project_id, work_item_type_id)
    project = None
    if project_template_type:
        template_type = project_template_type
    else:
        project = await _resolve_project(ctx, project_id)
        template_type = project["template_type"]
    base_params = {
        "scope[project_template_type]": template_type,
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
        # is_local_configure=0 的项目本来就共用全局模板, 取全局不算错配;
        # 项目自带模板却 404 才是真异常, 严格模式下直接报错而不是拿全局必填项误导调用方.
        if not allow_global_fallback and (project is None or project["is_local_configure"]):
            raise McpRuntimeError(
                "project_schema_unavailable",
                f"项目 {project_id} 的工单字段模板不可用，无法按项目校验必填项。"
                "请确认 project_id 与 work_item_type_id 正确"
                "（项目可调用 pingcode_common_list_projects 获取）。",
            ) from exc
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
        "template_type": template_type,
        "is_local_configure": None if project is None else project["is_local_configure"],
        "fields": _schema_fields(properties),
    }


async def get_issue_schema(
    ctx: McpContext,
    project_id: str,
    work_item_type_id: str,
    project_template_type: str | None = None,
) -> dict[str, Any]:
    return await get_property_schema(
        ctx,
        project_id,
        work_item_type_id,
        project_template_type,
        validate_type=True,
    )


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


def _updated_at_seconds(value: Any) -> int:
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return seconds // 1000 if seconds >= 1_000_000_000_000 else seconds


async def _scan_work_items(
    ctx: McpContext,
    params: dict[str, Any],
    *,
    type_id: str | None,
    assignee_id: str | None,
    updated_after: int | None = None,
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
    if updated_after is not None:
        filtered = [
            item
            for item in filtered
            if _updated_at_seconds(item.get("updated_at")) >= updated_after
        ]
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
    try:
        after = int(updated_after) if updated_after is not None else None
    except (TypeError, ValueError):
        raise McpRuntimeError(
            "invalid_arguments",
            f"updated_after 必须是 Unix 秒时间戳，当前值: {updated_after!r}",
        ) from None

    if type_id or assignee_id or after is not None:
        scanned = await _scan_work_items(
            ctx,
            params,
            type_id=type_id,
            assignee_id=assignee_id,
            updated_after=after,
        )
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

    try:
        payload = await _raw(ctx, "GET", f"/api/agile/work-items/{work_item_id}")
    except client.PingCodeBusinessError as exc:
        raise _business_failure(
            exc,
            what=f"工单 id={work_item_id}",
            hint="请改用 identifier（如 TF2-114），或先调用 pingcode_issue_search 获取 id",
        ) from exc
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


# ── testhub 用例库 ──────────────────────────────────────────

_TESTHUB_DEFAULT_PAGE_SIZE = 20
_TESTHUB_MAX_PAGE_SIZE = 100
_CASE_ATTRIBUTE_KEYS = (
    "created_by", "created_at", "created_time", "creation_date",
    "updated_by", "updated_at", "updated_time", "modify_date",
    "assignee", "assignee_id", "executor", "maintainer",
    "state", "status", "state_id", "state_type", "priority", "type",
    "case_type", "maintenance", "suite_id", "suite_name", "module_id",
    "module", "case_number",
)


def _paged_of(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    value = _value_of(payload)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)], {}
    if isinstance(value, dict):
        for key in ("value", "values", "items", "list", "cases", "rows", "testCases"):
            item = value.get(key)
            if isinstance(item, list):
                return [x for x in item if isinstance(x, dict)], value
        return [], value
    return [], {}


def _total_of(meta: dict[str, Any], size: int) -> int:
    for key in ("count", "total", "total_count", "recordCount"):
        value = meta.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return size


_PERSON_PROPERTY_KEYS = {"created_by", "updated_by"}
_PERSON_SPLIT = re.compile(r"[,，、\s]+")


def _member_value(uid: str) -> dict[str, Any]:
    # 人员字段值必须是 {id, type:1}; 裸 uid 会被服务端拒为 Unknown member type.
    return {"id": uid, "type": 1}


async def _team_roster(ctx: McpContext) -> dict[str, list[str]] | None:
    try:
        payload = await _get_json(ctx, "/api/typhon/team")
    except Exception:  # noqa: BLE001 - 花名册拉不到时按 uid 直传
        return None
    record = _record_of(payload)
    members = record.get("members")
    if not isinstance(members, list):
        return None
    roster: dict[str, list[str]] = {}
    for member in members:
        if not isinstance(member, dict):
            continue
        uid = str(member.get("uid") or member.get("id") or member.get("_id") or "")
        labels = [
            label
            for label in (
                str(member.get("display_name") or ""),
                str(member.get("name") or ""),
            )
            if label
        ]
        if uid and labels:
            roster[uid] = labels
    return roster or None


async def _person_values(ctx: McpContext, raw: Any, field: str) -> list[dict[str, Any]]:
    """人名 (显示名/登录名) 或 uid, 逗号/空格分隔 → 人员条件值数组."""
    tokens = [token for token in _PERSON_SPLIT.split(str(raw or "").strip()) if token]
    if not tokens:
        raise McpRuntimeError("invalid_arguments", f"{field} 不能为空")
    roster = await _team_roster(ctx)
    if not roster:
        return [_member_value(uid) for uid in dict.fromkeys(tokens)]
    by_name: dict[str, list[str]] = {}
    for uid, labels in roster.items():
        for label in labels:
            by_name.setdefault(label, []).append(uid)
    uids: list[str] = []
    missing: list[str] = []
    for token in tokens:
        if token in roster:
            uids.append(token)
        elif token in by_name:
            uids.extend(by_name[token])
        else:
            missing.append(token)
    if missing:
        raise McpRuntimeError(
            "invalid_arguments", f"{field} 找不到成员: {', '.join(missing)}"
        )
    return [_member_value(uid) for uid in dict.fromkeys(uids)]


def _case_filters(raw: Any) -> list[dict[str, Any]]:
    """筛选条件透传网页筛选器字段条件, 边界做结构校验."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise McpRuntimeError("invalid_arguments", "filters 必须是数组")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise McpRuntimeError("invalid_arguments", f"filters[{index}] 必须是对象")
        key = str(item.get("property_key") or "").strip()
        if not key:
            raise McpRuntimeError("invalid_arguments", f"filters[{index}].property_key 必填")
        try:
            operation = int(item.get("operation"))
        except (TypeError, ValueError) as exc:
            raise McpRuntimeError(
                "invalid_arguments", f"filters[{index}].operation 必须是数字 (6=属于)"
            ) from exc
        value = item.get("value")
        if value is None:
            values: list[Any] = []
        elif isinstance(value, list):
            values = value
        else:
            values = [value]
        if key in _PERSON_PROPERTY_KEYS:
            values = [
                _member_value(entry.strip())
                if isinstance(entry, str) and entry.strip()
                else entry
                for entry in values
            ]
        try:
            logic = int(item.get("logic")) if item.get("logic") is not None else 1
        except (TypeError, ValueError):
            logic = 1
        out.append(
            {
                "logic": logic,
                "property_key": key,
                "operation": operation,
                "value": values,
                "id": str(item.get("id") or f"{index}"),
            }
        )
    return out


def _short_case_id(value: Any) -> str:
    text = str(value or "").strip()
    return text.rsplit("-", 1)[-1] if "-" in text else text


def _case_identifier(item: dict[str, Any]) -> str:
    return str(item.get("whole_identifier") or item.get("identifier") or item.get("code") or "")


def _case_steps(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw = item.get("steps") or item.get("case_steps") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for index, step in enumerate(raw):
        if not isinstance(step, dict):
            continue
        raw_index = step.get("index")
        if raw_index in (None, ""):
            raw_index = step.get("step_index")
        if raw_index in (None, ""):
            raw_index = step.get("order")
        if raw_index in (None, ""):
            raw_index = index + 1
        try:
            number = int(raw_index)
        except (TypeError, ValueError):
            number = raw_index
        out.append(
            {
                "index": number,
                "description": step.get("description")
                or step.get("step_description")
                or step.get("name")
                or "",
                "expected_value": step.get("expected_value")
                or step.get("expected")
                or step.get("expected_result")
                or "",
            }
        )
    return out


def _normalize_test_case(item: dict[str, Any], *, steps: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item.get("_id") or item.get("id") or "",
        "identifier": _case_identifier(item),
        "title": item.get("title") or item.get("name") or "",
        "precondition": item.get("precondition") or item.get("preconditions") or "",
    }
    if steps:
        out["steps"] = _case_steps(item)
    return out


def _case_attributes(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in _CASE_ATTRIBUTE_KEYS
        if item.get(key) not in (None, "")
    }


async def _first_json(
    ctx: McpContext, candidates: list[tuple[str, dict[str, Any] | None]]
) -> Any:
    """按候选端点顺序尝试; 全部失败时抛出最后一个错误."""
    last: Exception | None = None
    for path, params in candidates:
        try:
            return await _get_json(ctx, path, params)
        except Exception as exc:  # noqa: BLE001 - 逐候选降级, 最后统一抛出
            last = exc
    if last is not None:
        raise last
    raise McpRuntimeError("not_found", "没有可用的接口端点")


async def list_test_case_libraries(ctx: McpContext) -> dict[str, Any]:
    payload = await _first_json(
        ctx,
        [
            ("/api/testhub/test-libraries", {"pi": 0, "ps": 100}),
            ("/api/testhub/test-libraries", {"ps": 100}),
            ("/api/testhub/libraries", {"ps": 100}),
        ],
    )
    raw_items, meta = _paged_of(payload)
    items = [
        {
            "id": str(item.get("_id") or item.get("id") or ""),
            "name": item.get("name") or "",
            "identifier": str(item.get("short_id") or item.get("identifier") or ""),
            "project_id": str(item.get("project_id") or ""),
            "description": item.get("description") or "",
            "case_count": item.get("case_count")
            if item.get("case_count") is not None
            else item.get("test_case_count"),
        }
        for item in raw_items
        if item.get("_id") or item.get("id")
    ]
    return {"total": _total_of(meta, len(items)), "items": items}


async def _fetch_case_page(
    ctx: McpContext,
    *,
    library_id: str,
    keyword: str,
    identifier: str,
    page: int,
    page_size: int,
    filters: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    search_keyword = (
        str(identifier).strip().rsplit("-", 1)[-1]
        if identifier
        else str(keyword or "").strip()
    )
    body = {
        "pi": max(0, page - 1),
        "criteria": {
            "search": {"keywords": search_keyword, "scopes": ["identifier", "title"]},
            "mode": 1,
            "conditions": filters,
            "sort_by": "position",
            "sort_direction": 1,
        },
        "scope": {"include_sub_suite": 1, "suite_id": "", "link_library_id": ""},
        "ps": page_size,
    }
    try:
        payload = await _raw(
            ctx,
            "POST",
            f"/api/testhub/test-libraries/{quote(str(library_id), safe='')}/test-cases",
            json=body,
        )
    except client.PingCodeBusinessError as exc:
        raise _business_failure(
            exc,
            what=f"用例库 {library_id}",
            hint="请调用 pingcode_case_list_libraries 获取 library_id",
        ) from exc
    raw_items, meta = _paged_of(payload)
    return raw_items, _total_of(meta, len(raw_items))


async def search_test_cases(
    ctx: McpContext,
    *,
    library_id: str,
    keyword: str = "",
    identifier: str = "",
    page: int = 1,
    page_size: int = _TESTHUB_DEFAULT_PAGE_SIZE,
    filters: Any = None,
    created_by: str = "",
    updated_by: str = "",
) -> dict[str, Any]:
    if not library_id:
        raise McpRuntimeError(
            "invalid_arguments",
            "library_id 必填: 先用 pingcode_case_list_libraries 查询用例库 _id",
        )
    page = max(1, int(page or 1))
    page_size = min(_TESTHUB_MAX_PAGE_SIZE, max(1, int(page_size or _TESTHUB_DEFAULT_PAGE_SIZE)))
    conditions = _case_filters(filters)
    for field, raw in (("created_by", created_by), ("updated_by", updated_by)):
        if not raw:
            continue
        conditions.append(
            {
                "logic": 1,
                "property_key": field,
                "operation": 6,
                "value": await _person_values(ctx, raw, field),
                "id": f"person-{len(conditions)}",
            }
        )
    raw_items, total = await _fetch_case_page(
        ctx,
        library_id=str(library_id),
        keyword=keyword,
        identifier=identifier,
        page=page,
        page_size=page_size,
        filters=conditions,
    )
    items = [_normalize_test_case(item, steps=False) for item in raw_items]
    return {
        "library_id": str(library_id),
        "total": total,
        "count": len(items),
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total if total else len(items) >= page_size,
        "items": items,
    }


async def _library_states(ctx: McpContext, library_id: str) -> dict[str, dict[str, Any]]:
    try:
        payload = await _get_json(
            ctx, "/api/testhub/test-case/states", {"library_id": library_id}
        )
    except Exception:  # noqa: BLE001 - 名字解析失败不影响用例详情
        return {}
    items = _list_of(payload)
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("_id") or item.get("id") or "")
        if not ident:
            continue
        out[ident] = {
            "name": str(item.get("name") or ""),
            "state_type": item.get("state_type"),
        }
    return out


def _flatten_suite_nodes(nodes: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(nodes, list):
        return out
    for node in nodes:
        if not isinstance(node, dict):
            continue
        out.append(node)
        out.extend(_flatten_suite_nodes(node.get("children")))
    return out


async def _library_suites(ctx: McpContext, library_id: str) -> dict[str, str]:
    encoded = quote(str(library_id), safe="")
    try:
        payload = await _first_json(
            ctx,
            [
                (f"/api/testhub/test-libraries/{encoded}/direct/suites", None),
                (f"/api/testhub/test-libraries/{encoded}/suites", None),
            ],
        )
    except Exception:  # noqa: BLE001 - 同状态解析, 失败保留 suite_id
        return {}
    return {
        str(node.get("_id") or node.get("id") or ""): str(node.get("name") or "")
        for node in _flatten_suite_nodes(_list_of(payload))
        if node.get("_id") or node.get("id")
    }


async def get_test_case(
    ctx: McpContext,
    *,
    identifier: str,
    library_id: str,
    include_raw: bool = False,
) -> dict[str, Any]:
    wanted = str(identifier or "").strip()
    if not wanted:
        raise McpRuntimeError("invalid_arguments", "identifier 必填, 如 HIMA3361-8077")
    if not library_id:
        raise McpRuntimeError(
            "invalid_arguments",
            "library_id 必填: 先用 pingcode_case_list_libraries 查询用例库 _id",
        )
    full_form = "-" in wanted
    page_size = 100
    for page in range(1, 11):
        raw_items, total = await _fetch_case_page(
            ctx,
            library_id=str(library_id),
            keyword="",
            identifier=wanted,
            page=page,
            page_size=page_size,
            filters=[],
        )
        for item in raw_items:
            full = _case_identifier(item)
            matched = (
                full.upper() == wanted.upper()
                if full_form
                else _short_case_id(full) == wanted
            )
            if not matched:
                continue
            out = _normalize_test_case(item)
            attributes = _case_attributes(item)
            state_id = item.get("state_id")
            if state_id:
                states = await _library_states(ctx, str(library_id))
                state = states.get(str(state_id), {})
                out["state"] = {
                    "id": state_id,
                    "name": state.get("name", ""),
                    "state_type": item.get("state_type", state.get("state_type")),
                }
            suite_id = item.get("suite_id")
            if suite_id:
                suites = await _library_suites(ctx, str(library_id))
                out["suite"] = {"id": suite_id, "name": suites.get(str(suite_id), "")}
            if include_raw:
                out["attributes"] = attributes
                out["raw"] = item
            elif attributes:
                out["attributes"] = attributes
            out["library_id"] = str(library_id)
            return out
        if len(raw_items) < page_size or (total and page * page_size >= total):
            break
    raise McpRuntimeError(
        "not_found", f"未找到用例 {wanted} (library {library_id})"
    )


async def get_test_case_properties(ctx: McpContext, *, library_id: str) -> dict[str, Any]:
    if not library_id:
        raise McpRuntimeError(
            "invalid_arguments",
            "library_id 必填: 先用 pingcode_case_list_libraries 查询用例库 _id",
        )
    try:
        payload = await _raw(
            ctx,
            "GET",
            "/api/testhub/test-case/view/properties",
            params={"library_id": library_id},
        )
    except client.PingCodeBusinessError as exc:
        raise _business_failure(
            exc,
            what=f"用例库 {library_id}",
            hint="请调用 pingcode_case_list_libraries 获取 library_id",
        ) from exc
    raw_fields = _list_of(payload)
    fields: list[dict[str, Any]] = []
    for prop in raw_fields:
        if not isinstance(prop, dict):
            continue
        item: dict[str, Any] = {
            "key": str(prop.get("property_key") or prop.get("key") or "").replace("properties.", ""),
            "name": prop.get("name") or "",
        }
        if prop.get("type") is not None:
            item["type"] = prop.get("type")
        if prop.get("is_system") is not None:
            item["is_system"] = bool(prop.get("is_system"))
        options = prop.get("options")
        if isinstance(options, list) and options:
            item["options"] = [
                {"id": str(option.get("_id") or option.get("id") or ""), "text": option.get("text") or ""}
                for option in options
                if isinstance(option, dict)
            ]
        if item["key"]:
            fields.append(item)
    return {"library_id": str(library_id), "fields": fields}


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


def _download_name(target: str, file_id: str | None, name: str | None) -> str:
    if name:
        return name
    parsed = urlparse(target)
    query = parse_qs(parsed.query)
    for key in ("name", "filename", "fileName"):
        if query.get(key):
            return query[key][0]
    base = parsed.path.rsplit("/", 1)[-1]
    if base and "." in base:
        return base
    ident = file_id or (query.get("fileId") or query.get("file_id") or [""])[0]
    return f"attachment-{ident}" if ident else (base or "attachment")


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

    limit = min(int(max_bytes or DEFAULT_DOWNLOAD_BYTES), MAX_DOWNLOAD_BYTES)
    try:
        content_type, data = await _download_bytes(target, access_token, limit)
    except McpRuntimeError as exc:
        if file_id and not url and exc.code == "download_failed":
            raise McpRuntimeError(
                "download_failed",
                f"{_localize_error_message(exc.message)}; "
                "附件请先调用 pingcode_issue_list_attachments 获取带 token 的 url 后传 url; "
                "file_id 仅适用于描述里以 /atlas/files/public/ 引用的内联截图",
            ) from exc
        raise
    result: dict[str, Any] = {
        "content_type": content_type,
        "bytes": len(data),
        "name": _download_name(target, file_id, name),
    }
    if content_type.startswith("image/"):
        result["base64"] = base64.b64encode(data).decode("ascii")
        return result
    result["url"] = target
    result["token"] = access_token
    return result


def _read_upload_source(
    path: str | None, content_base64: str | None
) -> tuple[bytes, str]:
    if bool(path) == bool(content_base64):
        raise McpRuntimeError(
            "invalid_arguments", "path 与 content_base64 必须且只能提供一个"
        )
    if path:
        target = Path(path).expanduser()
        if not target.is_file():
            raise McpRuntimeError("file_not_found", f"文件不存在或不是普通文件: {path}")
        try:
            return target.read_bytes(), target.name
        except OSError as exc:
            raise McpRuntimeError("file_not_found", f"读取文件失败: {path}") from exc
    try:
        return base64.b64decode(content_base64 or "", validate=True), ""
    except (binascii.Error, ValueError) as exc:
        raise McpRuntimeError("invalid_arguments", "content_base64 不是合法的 base64") from exc


async def _upload_token(ctx: McpContext, scope: int, size: int) -> str:
    payload = await _request(
        ctx,
        "GET",
        "/api/typhon/secret/file/upload-token",
        params={"scope": scope, "size": size},
    )
    if isinstance(payload, str) and payload:
        return payload
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            return value["value"]
    raise McpRuntimeError("pingcode_error", "获取上传令牌失败")


async def _link_attachment(
    ctx: McpContext, work_item_id: str, file_id: str
) -> dict[str, Any]:
    payload = await _request(
        ctx,
        "POST",
        f"/api/agile/work-items/{work_item_id}/attachment",
        json={"file_id": file_id},
    )
    raw = _record_of(payload)
    return {
        "file_id": file_id,
        "attachment_id": str(raw.get("_id") or raw.get("attachment_id") or ""),
        "ok": True,
    }


async def upload_attachment(
    ctx: McpContext,
    *,
    confirm: bool,
    path: str | None = None,
    content_base64: str | None = None,
    name: str | None = None,
    purpose: str = "attachment",
    work_item_id: str | None = None,
    client_request_id: str | None = None,
) -> dict[str, Any]:
    if confirm is not True:
        raise McpRuntimeError(
            "confirmation_required", "写操作需要显式 confirm=true 确认后才会提交"
        )
    if purpose not in ("attachment", "inline"):
        raise McpRuntimeError("invalid_arguments", "purpose 只支持 attachment 或 inline")
    if purpose == "inline" and work_item_id:
        raise McpRuntimeError(
            "invalid_arguments", "purpose=inline 时不能关联工单，内联图请直接用返回的 public_url"
        )
    if bool(path) == bool(content_base64):
        raise McpRuntimeError(
            "invalid_arguments", "path 与 content_base64 必须且只能提供一个"
        )

    key = (
        f"mcp:pingcode:upload:{_user_id(ctx)}:{client_request_id}"
        if client_request_id
        else ""
    )
    if key:
        async with redis_client() as redis:
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)

    content, default_name = _read_upload_source(path, content_base64)
    if len(content) > MAX_UPLOAD_BYTES:
        raise McpRuntimeError("attachment_too_large", "附件超过 100MB 上限")
    filename = (Path(name).name if name else default_name) or "upload.bin"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    scope = UPLOAD_SCOPE_INLINE if purpose == "inline" else UPLOAD_SCOPE_ATTACHMENT

    token = await _upload_token(ctx, scope, len(base64.b64encode(content)))
    payload = await token_manager.upload_file(
        _user_id(ctx),
        "/atlas/file/upload",
        token=token,
        scope=scope,
        filename=filename,
        content=content,
        content_type=content_type,
    )
    raw = _record_of(payload)
    file_id = str(raw.get("_id") or raw.get("id") or "")
    if not file_id:
        raise McpRuntimeError("pingcode_error", "上传成功但未返回文件 id")

    result: dict[str, Any] = {
        "ok": True,
        "file_id": file_id,
        "name": filename,
        "bytes": len(content),
        "content_type": content_type,
        "purpose": purpose,
        "scope": scope,
    }
    if purpose == "inline":
        result["public_url"] = f"{_base_url()}/atlas/files/public/{file_id}"
    elif work_item_id:
        linked = await _link_attachment(ctx, work_item_id, file_id)
        result["attachment_id"] = linked["attachment_id"]
        result["work_item_id"] = work_item_id

    if key:
        async with redis_client() as redis:
            await redis.set(
                key, json.dumps(result, ensure_ascii=False, default=str), ex=IDEMPOTENCY_TTL
            )
    return result


def _strip_html(html: str) -> str:
    return normalize.html_to_text(html)


async def preview_work_item(
    ctx: McpContext,
    *,
    project_id: str,
    work_item_type_id: str,
    properties: dict[str, Any] | None = None,
    project_template_type: str | None = None,
    description_template: str | None = None,
    description_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = await get_property_schema(
        ctx,
        project_id,
        work_item_type_id,
        project_template_type,
        allow_global_fallback=False,
    )
    props = dict(properties or {})
    if description_template:
        if description_template != "standard":
            raise McpRuntimeError(
                "invalid_arguments", "description_template 只支持 standard"
            )
        props["description"] = render_description(description_fields or {})
    props = _coerce_properties(props, schema["fields"])
    _fill_required_defaults(schema["fields"], props)

    injected = {"project_id", "type"}
    if props.get("participants") is not None or props.get("assignee") is not None:
        injected.add("participants")
    missing_fields, invalid_fields = _collect_create_errors(
        schema["fields"], props, injected=injected
    )
    result: dict[str, Any] = {
        "ok": not missing_fields and not invalid_fields,
        "missing_required": [item["key"] for item in missing_fields],
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
        "payload": {
            "project_id": project_id,
            "work_item_type_id": work_item_type_id,
            "project_template_type": schema["template_type"],
            "properties": props,
            "description_text": _strip_html(props.get("description", "")),
        },
    }
    if missing_fields or invalid_fields:
        result["error"] = _describe_create_errors(missing_fields, invalid_fields)
    return result


_MULTI_VALUE_TYPES = {16, 20}
_SELECT_TYPES = {6, 16, 20}
_INJECTED_KEYS = {"project_id", "type", "participants"}


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


def _is_empty_prop(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def _fill_required_defaults(fields: list[dict[str, Any]], props: dict[str, Any]) -> None:
    """对齐 AiTestX: 隐藏必填项补默认值, 可见必填项仍由调用方提供."""
    for field in fields:
        if not field.get("required"):
            continue
        key = str(field.get("key") or "")
        name = str(field.get("name") or key)
        if not key or key in _INJECTED_KEYS or not _is_empty_prop(props.get(key)):
            continue
        if key == "start" or name == "开始时间":
            props[key] = int(time.time())
        elif name == "是否用例发现":
            option = next(
                (item for item in field.get("options") or [] if item.get("text") == "用例发现"),
                None,
            )
            if option and option.get("_id"):
                props[key] = option["_id"]
        elif name == "重现步骤":
            props[key] = "<p>见描述详情</p>" if field.get("type") == 2 else "见描述详情"
        elif key == "description" or name == "描述":
            default = field.get("default_value")
            if isinstance(default, str) and default.strip():
                props[key] = default


_FIELD_HINTS = {
    2: "富文本 HTML 字符串",
    4: "Unix 秒时间戳或 {date, with_time}",
    6: "选项 _id，先用 pingcode_issue_get_schema 查询合法选项",
    9: "成员 uid，先用 pingcode_common_list_members 查询",
    16: "选项 _id 数组，先用 pingcode_issue_get_schema 查询合法选项",
    20: "选项 _id 数组，先用 pingcode_issue_get_schema 查询合法选项",
}
_MISSING = object()


def _option_summary(options: list[dict[str, Any]], limit: int = 12) -> str:
    parts = [f"{item.get('_id')}={item.get('text')}" for item in options[:limit]]
    if len(options) > limit:
        parts.append(f"共{len(options)}项")
    return ", ".join(parts)


def _field_requirement(
    field: dict[str, Any], *, value: Any = _MISSING
) -> dict[str, Any]:
    key = str(field.get("key") or "")
    kind = field.get("type")
    item: dict[str, Any] = {
        "key": key,
        "name": field.get("name") or key,
        "type": kind,
    }
    options = field.get("options") or []
    if options:
        item["options"] = [
            {"_id": option.get("_id"), "text": option.get("text")}
            for option in options
            if option.get("_id")
        ]
    else:
        item["hint"] = _FIELD_HINTS.get(kind, "任意非空文本")
    if value is not _MISSING:
        item["value"] = value
    return item


def _collect_create_errors(
    fields: list[dict[str, Any]],
    props: dict[str, Any],
    *,
    injected: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    missing: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    injected_keys = _INJECTED_KEYS | set(injected)
    for field in fields:
        key = str(field.get("key") or "")
        if not key or key in injected_keys:
            continue
        value = props.get(key)
        if field.get("required") and _is_empty_prop(value):
            missing.append(_field_requirement(field))
            continue
        options = field.get("options") or []
        if (
            _is_empty_prop(value)
            or field.get("type") not in _SELECT_TYPES
            or not options
        ):
            continue
        allowed = {str(item.get("_id")) for item in options if item.get("_id")}
        values = value if isinstance(value, list) else [value]
        bad = [str(item) for item in values if str(item) not in allowed]
        if bad:
            invalid.append(_field_requirement(field, value="/".join(bad)))
    return missing, invalid


def _describe_create_errors(
    missing: list[dict[str, Any]], invalid: list[dict[str, Any]]
) -> str:
    parts: list[str] = []
    if missing:
        entries = []
        for item in missing:
            text = f"{item['name']}({item['key']})"
            if item.get("options"):
                text += f" 可选: {_option_summary(item['options'])}"
            else:
                text += f", {item.get('hint') or '任意非空文本'}"
            entries.append(text)
        parts.append("缺少必填 " + "; ".join(entries))
    if invalid:
        entries = []
        for item in invalid:
            text = f"{item['name']}({item['key']}={item['value']})"
            if item.get("options"):
                text += f" 合法: {_option_summary(item['options'])}"
            entries.append(text)
        parts.append("选项非法 " + "; ".join(entries))
    return "; ".join(parts)


def _raise_create_errors(
    missing: list[dict[str, Any]], invalid: list[dict[str, Any]]
) -> None:
    if not missing and not invalid:
        return
    raise McpRuntimeError(
        "invalid_arguments",
        "创建工单参数不合法: "
        + _describe_create_errors(missing, invalid)
        + "。请先调用 pingcode_issue_get_schema 获取必填字段与选项 _id。",
    )


def _member_uid(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("uid") or value.get("id")
    return value.strip() if isinstance(value, str) else ""


async def create_work_item(
    ctx: McpContext,
    *,
    project_id: str,
    work_item_type_id: str,
    properties: dict[str, Any] | None = None,
    confirm: bool,
    client_request_id: str,
    project_template_type: str | None = None,
    description_template: str | None = None,
    description_fields: dict[str, Any] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    if confirm is not True:
        raise McpRuntimeError(
            "confirmation_required", "写操作需要显式 confirm=true 确认后才会提交"
        )
    file_ids: list[str] = []
    for item in attachments or []:
        if isinstance(item, str) and item.strip() and item.strip() not in file_ids:
            file_ids.append(item.strip())
    if attachments and not file_ids:
        raise McpRuntimeError("invalid_arguments", "attachments 必须是 file_id 字符串数组")
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
    _fill_required_defaults(fields, props)
    missing, invalid = _collect_create_errors(fields, props)
    if not _member_uid(props.get("assignee")):
        detail = _describe_create_errors(missing, invalid)
        parts = [detail] if detail else []
        parts.append("创建工单必须指定负责人 assignee，为空时禁止创建")
        parts.append(
            "请先调用 pingcode_common_list_members 获取成员 uid 后填入 assignee"
        )
        raise McpRuntimeError("assignee_required", "。".join(parts))
    _raise_create_errors(missing, invalid)

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
    if file_ids:
        linked = []
        for file_id in file_ids:
            try:
                linked.append(await _link_attachment(ctx, work_item_id, file_id))
            except McpRuntimeError as exc:
                linked.append({"file_id": file_id, "ok": False, "error": str(exc)})
        result["attachments"] = linked
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
