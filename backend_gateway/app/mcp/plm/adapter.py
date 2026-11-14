"""PLM 域工具适配层: 只读查询、严格建单校验与写入幂等.

接口契约对齐 AiTestX 浏览器扩展 (content/plm-bridge.js + background/sw.js) 的实测路径:
- 问题单列表/详情: POST /yonbip-mm-plmrd/bill/list (zlib + enable-deflate), GET /bill/detail
- 字典: GET /yonbip-mm-plmrd/pub/ref/getRefMeta + POST /bill/ref/getRefData (deflate)
- 模板元数据: POST /mdf-node/meta
- 建单: questionCgr/allowCreateQuestion → getLcDetail → getCode (WSD 单号) → 查重 → bill/save
- 附件: jssdk/version → createFileUploadTask → DES-CBC 解密 PUT → saveFileUploadBusiness
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import html
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.config import settings
from app.integrations import credentials
from app.integrations.plm import client, session_manager
from app.integrations.redis import redis_client
from app.mcp.common.context import McpContext
from app.mcp.common.errors import McpRuntimeError
from app.mcp.plm import normalize, schema, templates

PROVIDER = "plm"
DEFAULT_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
IDEMPOTENCY_TTL = 600

DEFAULT_ORG_ID = "2517880124330737675"  # 研发中心 (AiTestX 实测兜底)
DEFAULT_ORG_NAME = "研发中心"
DEFAULT_DEPT_ID = "2495850824752693252"  # 产品测试部
DEFAULT_DEPT_NAME = "产品测试部"
DEFAULT_QUESTION_CODE = "13"  # 提交审核
DEFAULT_QUESTION_STATE_NAME = "提交审核"
TENANT_ID = "impwzqgp"

QUESTION_SERVICE = "plm_base_question_manage"
QUESTION_BILL = "baseQuestion"
QUESTION_LIST = "baseQuestionList"
QUESTION_TEMPLATE_ID = "2500051156724088846"
PROJECT_TEMPLATE_ID = "2573710034846351369"
PROJECT_REF_CODE = schema.PROJECT_REF
QUESTION_TYPE_REF_CODE = schema.QUESTION_TYPE_REF
MEMBER_REF_CODE = schema.MEMBER_REF
BILL_ENTITY_ID = "2500051156724088840"
BUSTYPE = "2500724255420841990"

TEST_CASE_SERVICE = "imp_gds_doc"
TEST_CASE_BILL = "178cbfe6-e700-4667-8116-711341ab6f97"
TEST_CASE_DETAIL_BILL = "40deda4a-a9ea-460f-93f4-21e3fa85914d"
TEST_CASE_FILTERS_ID = "1654391937173688320"
TEST_CASE_TPLID = "2482853480615641099"
TEST_CASE_TREE_NAME = "gds.documentClassify.documentClassify"
DEFAULT_TREE_DEPTH = 3
MAX_TREE_DEPTH = 6
MAX_TREE_NODES = 1000

MAX_PAGE_SIZE = 100
MAX_SCAN_PAGES = 20
_WSD_RE = re.compile(r"^WSD\d{8,}$")

# PLM 问题单关单说明富文本 (AiTestX sw.js 硬编码值, /save 时 item238si 字段必带)
ITEM238SI_HTML = (
    '<p><span style="color:#c0392b">问题关闭说明： 状态选择“</span>'
    '<span style="color:#003ba5"><span style="font-size:16px">确认'
    '<span style="background-color:#ffffff">关闭</span></span></span>'
    '<span style="color:#c0392b">”或者经过“</span>'
    '<span style="color:#003ba5"><span style="font-size:16px">'
    '<span style="background-color:#ffffff">根因分析：选非新增问题</span></span></span>'
    '<span style="color:#c0392b">”、“</span>'
    '<span style="color:#003ba5"><span style="font-size:16px">'
    '<span style="background-color:#ffffff">回归测试：测试通过</span></span></span>'
    '<span style="color:#c0392b">”，提交给发起人关闭</span></p>'
    '<p><span style="color:#c0392b">标准流程:     问题单提交-&gt;提交审核-&gt;根因分析-'
    '<span style="font-size:16px"><span style="background-color:#ffffff">&gt;</span></span>'
    '测试复现-&gt;修正方案-&gt;修正审核-&gt;回归测试-&gt;确认关闭</span>'
    '<span style="color:#003ba5">（ 问题单所有状态流转可按实际业务发生用户选择提交即可，'
    '仅限制”确认关闭“无法流转其他状态；例如：”问题单提交“可流转至任何状态 。）</span></p>'
)

_NOT_CONFIGURED_MESSAGE = "尚未配置 PLM 账号，请在个人中心「平台认证」中绑定"


def _user_id(ctx: McpContext) -> int:
    return int(ctx.principal.user.id)


def _base_url() -> str:
    return settings.PLM_BASE_URL.rstrip("/")


def _clamp(value: Any, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(1, number))


# ── 错误收敛 ────────────────────────────────────────────────
async def _session(ctx: McpContext) -> client.PlmSession:
    try:
        return await session_manager.ensure_session(_user_id(ctx))
    except session_manager.IntegrationNotConfigured as exc:
        raise McpRuntimeError(
            "integration_not_configured", str(exc) or _NOT_CONFIGURED_MESSAGE
        ) from exc
    except session_manager.IntegrationReauthRequired as exc:
        raise McpRuntimeError(
            "integration_reauth_required",
            str(exc) or "PLM 登录态已失效，请在个人中心重新绑定账号",
        ) from exc
    except client.PlmUnavailable as exc:
        raise McpRuntimeError("integration_unavailable", f"PLM 暂不可达: {exc}") from exc


async def _raw(ctx: McpContext, method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await session_manager.request(_user_id(ctx), method, path, **kwargs)
    except session_manager.IntegrationNotConfigured as exc:
        raise McpRuntimeError(
            "integration_not_configured", str(exc) or _NOT_CONFIGURED_MESSAGE
        ) from exc
    except session_manager.IntegrationReauthRequired as exc:
        raise McpRuntimeError(
            "integration_reauth_required",
            str(exc) or "PLM 登录态已失效，请在个人中心重新绑定账号",
        ) from exc
    except client.PlmSessionExpired as exc:
        raise McpRuntimeError(
            "integration_reauth_required", "PLM 登录态已失效，请稍后重试或重新绑定"
        ) from exc
    except client.PlmUnavailable as exc:
        raise McpRuntimeError("integration_unavailable", f"PLM 暂不可达: {exc}") from exc


async def _request(ctx: McpContext, method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await _raw(ctx, method, path, **kwargs)
    except client.PlmBusinessError as exc:
        raise McpRuntimeError("plm_error", str(exc) or "PLM 返回业务错误") from exc


# ── 会话上下文 ──────────────────────────────────────────────
def _org_id(session: client.PlmSession) -> str:
    return str(session.org_id or session.cookies.get("orgId") or DEFAULT_ORG_ID)


def _tenant_id(session: client.PlmSession) -> str:
    return str(session.tenant_id or session.cookies.get("tenantid") or "")


def _xsrf(session: client.PlmSession) -> str:
    return str(session.cookies.get("XSRF-TOKEN") or "")


def _biz_user_id(session: client.PlmSession) -> str:
    """PLM 业务 userId: cookie 与 JWT 中的 19 位数字 (AiTestX 从页面 getUserInfo 取)."""
    cookies = session.cookies or {}
    at = str(cookies.get("at") or "")
    if re.fullmatch(r"\d{10,}", at):
        return at
    for name in ("yht_usertoken_diwork", "yht_username_diwork"):
        try:
            raw = unquote(str(cookies.get(name) or ""))
        except (ValueError, TypeError):
            raw = str(cookies.get(name) or "")
        match = re.search(r"(\d{10,})", raw)
        if match:
            return match.group(1)
    token = str(cookies.get("yht_access_token") or "")
    parts = token.split(".")
    if len(parts) == 3:
        try:
            decoded = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
            payload = json.loads(decoded)
        except (ValueError, binascii.Error):
            payload = None
        if isinstance(payload, dict):
            for key in ("userId", "user_id", "sub", "id"):
                value = str(payload.get(key) or "")
                if re.fullmatch(r"\d{10,}", value):
                    return value
    return ""


def _question_url(question_id: str) -> str:
    if not question_id:
        return ""
    return (
        f"{_base_url()}/mdf-node/meta/voucher/{QUESTION_BILL}"
        "?domainKey=IMP-BASE"
        f"&serviceCode={QUESTION_SERVICE}"
        f"&id={quote(question_id, safe='')}"
        "&locale=zh_CN"
    )


# ── 问题单列表 / 详情 ────────────────────────────────────────
def _updated_filter(value: Any) -> str:
    try:
        seconds = int(value) - 1
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")


async def _question_list(ctx: McpContext, *, simple_vos: list[dict], page: int, page_size: int) -> dict[str, Any]:
    body = {
        "billnum": QUESTION_LIST,
        "sbillno": QUESTION_LIST,
        "serviceCode": QUESTION_SERVICE,
        "terminalType": "1",
        "page": {"pageSize": page_size, "pageIndex": page},
        "condition": {"commonVOs": [], "simpleVOs": simple_vos, "isExtend": True},
    }
    payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/bill/list",
        params={"serviceCode": QUESTION_SERVICE, "terminalType": "1"},
        json=body,
        deflate=True,
    )
    data = payload if isinstance(payload, dict) else {}
    records = [
        item
        for item in (data.get("recordList") or data.get("records") or [])
        if isinstance(item, dict)
    ]
    total = data.get("recordCount")
    if not isinstance(total, (int, float)):
        total = data.get("total")
    return {
        "total": int(total) if isinstance(total, (int, float)) else len(records),
        "records": records,
    }


def _search_vos(
    *,
    keyword: str = "",
    code: str = "",
    question_id: str = "",
    status: str = "",
    raise_person_id: str = "",
    updated_after: Any = None,
) -> list[dict[str, Any]]:
    simple: list[dict[str, Any]] = []
    if question_id:
        simple.append({"field": "id", "op": "eq", "value1": str(question_id)})
    if code:
        simple.append({"field": "code", "op": "eq", "value1": str(code)})
    if keyword:
        simple.append({"field": "name", "op": "like", "value1": str(keyword)})
    if status:
        text = str(status).strip()
        field = "lctemplate_attribute_id" if re.fullmatch(r"\d{6,}", text) else "stateId"
        simple.append({"field": field, "op": "eq", "value1": text})
    if raise_person_id:
        simple.append({"field": "raisePerson", "op": "eq", "value1": str(raise_person_id)})
    if updated_after:
        formatted = _updated_filter(updated_after)
        if formatted:
            simple.append({"field": "modifiedtime", "op": "gt", "value1": formatted})
    return simple


async def _find_question(
    ctx: McpContext, *, question_id: str = "", code: str = ""
) -> dict[str, Any] | None:
    if not question_id and not code:
        return None
    payload = await _question_list(
        ctx,
        simple_vos=_search_vos(code=code, question_id=question_id),
        page=1,
        page_size=1,
    )
    wanted_id = str(question_id or "")
    wanted_code = str(code or "")
    for record in payload["records"]:
        if wanted_id and str(record.get("id") or record.get("_id") or "") == wanted_id:
            return record
        if wanted_code and str(record.get("code") or "") == wanted_code:
            return record
    return None


async def _question_detail(ctx: McpContext, question_id: str) -> dict[str, Any]:
    session = await _session(ctx)
    params = {
        "id": question_id,
        "billnum": QUESTION_BILL,
        "locale": "zh_CN",
        "type": "",
        "serviceCode": QUESTION_SERVICE,
        "sbillno": QUESTION_LIST,
        "orgId": _org_id(session),
        "terminalType": "1",
    }
    payload = await _request(ctx, "GET", "/yonbip-mm-plmrd/bill/detail", params=params)
    record = payload if isinstance(payload, dict) else {}
    if not record.get("code") and not record.get("name"):
        raise McpRuntimeError("plm_error", "PLM 问题单详情为空")
    return record


def _group_id(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return re.findall(r"mdf_[0-9a-fA-F-]{36}", value)


async def _attachment_group_files(
    ctx: McpContext, *, question_id: str, code: str
) -> list[dict[str, Any]]:
    session = await _session(ctx)
    org_id = _org_id(session)
    params = {
        "pageSize": "9999",
        "verifyState": "0",
        "billCode": code or "",
        "billNo": QUESTION_BILL,
        "billId": question_id,
        "serviceCode": QUESTION_SERVICE,
        "domainKey": "IMP-BASE",
        "orgId": org_id,
        "authId": QUESTION_SERVICE,
        "locale": "zh_CN",
        "fromDevice": "web",
    }
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in normalize.attachment_groups(
        await _question_detail(ctx, question_id)
    ):
        path = (
            "/iuap-apcom-file/rest/v1/file/yonbip-mm-plmrd+mdf/"
            f"{quote(group['group_id'], safe='')}/files"
        )
        try:
            payload = await _request(ctx, "GET", path, params=params)
        except McpRuntimeError:
            continue
        data = payload
        if isinstance(data, dict):
            data = data.get("list") or data.get("records") or []
        for raw in data if isinstance(data, list) else []:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("fileKey") or raw.get("path") or raw.get("fileId") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            file_url = str(raw.get("filePath") or "")
            if file_url and not re.match(r"^https?://", file_url, re.IGNORECASE) or not file_url and key:
                file_url = f"{_base_url()}/yms-def-bucket/{key.lstrip('/')}"
            item = dict(raw)
            item.update({"field": group["field"], "url": file_url, "filePath": file_url})
            items.append(item)
    return items


def _with_files(
    record: dict[str, Any], files: list[dict[str, Any]]
) -> dict[str, Any]:
    if not files:
        return record
    merged = dict(record)
    merged["accessoryList"] = files
    return merged


# ── 字典 (refbook) ──────────────────────────────────────────
async def _ref_meta(ctx: McpContext, ref_code: str) -> dict[str, Any]:
    session = await _session(ctx)
    params = {
        "serviceCode": QUESTION_SERVICE,
        "refCode": ref_code,
        "sourceBillnum": QUESTION_BILL,
        "billnum": QUESTION_BILL,
        "terminalType": "1",
        "locale": "zh_CN",
        "sbillno": QUESTION_LIST,
        "orgId": _org_id(session),
    }
    payload = await _request(ctx, "GET", "/yonbip-mm-plmrd/pub/ref/getRefMeta", params=params)
    return payload if isinstance(payload, dict) else {}


async def _init_filter_solution(ctx: McpContext, *, ref_code: str, filter_id: str, domain: str) -> str:
    session = await _session(ctx)
    params = {
        "locale": "zh_CN",
        "serviceCode": QUESTION_SERVICE,
        "sbillno": QUESTION_LIST,
        "orgId": _org_id(session),
        "refCode": ref_code,
        "sourceBillnum": QUESTION_BILL,
        "terminalType": "1",
        "filterId": filter_id,
        "domain": domain,
    }
    try:
        payload = await _request(ctx, "GET", "/mdf-node/client/getInitFilterInfo", params=params)
    except McpRuntimeError:
        return ""
    inner = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(inner, dict):
        return ""
    body = inner.get("data") if isinstance(inner.get("data"), dict) else inner
    scheme = body.get("schemeInfoVO") if isinstance(body.get("schemeInfoVO"), dict) else {}
    solution = str(scheme.get("schemeId") or body.get("solutionId") or body.get("defaultSchemeId") or "")
    if solution:
        return solution
    schemes = body.get("schemes") or scheme.get("schemes")
    for item in schemes if isinstance(schemes, list) else []:
        if isinstance(item, dict) and item.get("isDefault"):
            return str(item.get("solutionId") or item.get("schemeId") or item.get("id") or "")
    return ""


def _ref_payload_fields(ref_code: str) -> tuple[str, str, str]:
    if ref_code == QUESTION_TYPE_REF_CODE:
        return "questionCgrId.name", "questionCgrId", "questionCgrId_name"
    if ref_code == MEMBER_REF_CODE:
        return "raisePerson.name", "raisePerson", "raisePerson_name"
    return "", "", ""


def _flatten_ref(nodes: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        ident = node.get("id") or node.get("_id")
        if ident:
            out.append(
                {
                    "id": str(ident),
                    "name": str(node.get("name") or node.get("text") or ""),
                    "code": str(node.get("code") or ""),
                    "level": int(node.get("level") or 0),
                    "is_end": bool(node.get("isEnd")),
                }
            )
        out.extend(_flatten_ref(node.get("children")))
    return out


async def _ref_data(
    ctx: McpContext, ref_code: str, *, keyword: str, page_size: int, field: str = "name"
) -> list[dict[str, Any]]:
    session = await _session(ctx)
    meta = await _ref_meta(ctx, ref_code)
    entity = meta.get("refEntity") if isinstance(meta.get("refEntity"), dict) else {}
    grid_meta = meta.get("gridMeta") if isinstance(meta.get("gridMeta"), dict) else {}
    viewmodel = grid_meta.get("viewmodel") if isinstance(grid_meta.get("viewmodel"), dict) else {}
    def_tpl = str(viewmodel.get("defTplId") or "")
    if not def_tpl:
        raise McpRuntimeError("plm_error", f"PLM 字典 {ref_code} 未返回 defTplId")
    filter_id = str(entity.get("cFilterId") or "")
    domain = str(entity.get("outDomain") or "")
    is_member = ref_code == MEMBER_REF_CODE
    if is_member and not filter_id:
        raise McpRuntimeError("plm_error", "PLM 用户字典未返回 cFilterId")
    solution_id = (
        await _init_filter_solution(
            ctx, ref_code=ref_code, filter_id=filter_id, domain=domain or "ucf-staff-center"
        )
        if is_member and filter_id
        else ""
    )
    datasource, real_datasource, key = _ref_payload_fields(ref_code)
    if is_member:
        condition = {
            "commonVOs": [
                {"itemName": "schemeName", "value1": "默认方案"},
                {"itemName": "isDefault", "value1": True},
                {"itemName": "name", "value1": keyword} if field == "name" else {"itemName": field, "value1": keyword},
            ],
            "filtersId": filter_id,
            "solutionId": solution_id,
        }
    else:
        condition = {
            "isExtend": True,
            "simpleVOs": [
                {"field": "dr", "op": "eq", "value1": 0},
                {"field": "state", "op": "eq", "value1": "1"},
            ],
        }
    body = {
        "page": {"pageSize": page_size, "pageIndex": 1, "totalCount": 1},
        "refCode": ref_code,
        "tplid": def_tpl,
        "fullname": "plm-base.question.question",
        "datasource": datasource,
        "realDatasource": real_datasource,
        "key": key,
        "bSelfDefine": False,
        "billnum": QUESTION_BILL,
        "isMasterOrg": False,
        "masterOrgValue": _org_id(session),
        "billEntityId": BILL_ENTITY_ID,
        "data": "{}",
        "serviceCode": QUESTION_SERVICE,
        "dataType": "grid" if is_member else "tree",
        "condition": condition,
    }
    params = {
        "serviceCode": QUESTION_SERVICE,
        "refCode": ref_code,
        "sourceBillnum": QUESTION_BILL,
        "terminalType": "1",
        "sbillno": QUESTION_LIST,
        "orgId": _org_id(session),
        "locale": "zh_CN",
    }
    payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/bill/ref/getRefData",
        params=params,
        json=body,
        deflate=True,
    )
    data = payload if isinstance(payload, dict) else {}
    nodes = data.get("recordList")
    if not isinstance(nodes, list) and isinstance(payload, list):
        nodes = payload
    return _flatten_ref(nodes)


async def _projects(ctx: McpContext, *, page_size: int = 50) -> list[dict[str, Any]]:
    session = await _session(ctx)
    biz_user = _biz_user_id(session)
    body = {
        "page": {"pageSize": page_size, "pageIndex": 1, "totalCount": 1},
        "refCode": PROJECT_REF_CODE,
        "tplid": PROJECT_TEMPLATE_ID,
        "condition": {
            "isExtend": True,
            "simpleVOs": [
                {"field": "dr", "op": "eq", "value1": 0},
                {"field": "id", "op": "nin", "value1": []},
            ],
        },
        "fullname": "plm-base.question.question",
        "datasource": "association_object",
        "realDatasource": "association_object",
        "key": "association_object",
        "bSelfDefine": False,
        "billnum": QUESTION_BILL,
        "isMasterOrg": False,
        "masterOrgValue": _org_id(session),
        "billEntityId": BILL_ENTITY_ID,
        "data": json.dumps({"owner": biz_user} if biz_user else {}, ensure_ascii=False),
        "busiObj": "QGMaturity",
        "query": {"busiObj": "QGMaturity"},
        "serviceCode": QUESTION_SERVICE,
        "dataType": "grid",
    }
    params = {
        "serviceCode": QUESTION_SERVICE,
        "refCode": PROJECT_REF_CODE,
        "sourceBillnum": QUESTION_BILL,
        "terminalType": "1",
        "busiObj": "QGMaturity",
        "sbillno": QUESTION_LIST,
        "orgId": _org_id(session),
        "locale": "zh_CN",
    }
    payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/bill/ref/getRefData",
        params=params,
        json=body,
        deflate=True,
    )
    data = payload if isinstance(payload, dict) else {}
    out: list[dict[str, Any]] = []
    for item in data.get("recordList") or []:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or item.get("_id") or "")
        if not ident:
            continue
        out.append(
            {
                "id": ident,
                "code": str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "principal": str(item.get("principal_name") or ""),
            }
        )
    return out


async def _template_options(ctx: McpContext) -> dict[str, list[dict[str, str]]]:
    session = await _session(ctx)
    org_id = _org_id(session)
    body = {
        "billNo": QUESTION_BILL,
        "noCache": False,
        "type": "bill",
        "query": {
            "locale": "zh_CN",
            "serviceCode": QUESTION_SERVICE,
            "sbillno": QUESTION_LIST,
            "orgId": org_id,
        },
        "tplid": QUESTION_TEMPLATE_ID,
        "newBillMeta": True,
    }
    payload = await _request(
        ctx,
        "POST",
        "/mdf-node/meta",
        params={
            "terminalType": "1",
            "serviceCode": QUESTION_SERVICE,
            "locale": "zh_CN",
            "sbillno": QUESTION_LIST,
            "orgId": org_id,
        },
        json=body,
    )
    view = {}
    if isinstance(payload, dict):
        viewmeta = payload.get("viewmeta") if isinstance(payload.get("viewmeta"), dict) else {}
        view = viewmeta.get("view") if isinstance(viewmeta.get("view"), dict) else {}
    options: dict[str, list[dict[str, str]]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("cControlType") == "optionwidget" and node.get("cFieldName"):
            field = str(node["cFieldName"])
            raw = node.get("enumArray")
            if isinstance(raw, str) and raw.startswith("["):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = []
            if isinstance(raw, list) and raw and field not in options:
                options[field] = [
                    {"id": str(item.get("key")), "name": str(item.get("value") or "")}
                    for item in raw
                    if isinstance(item, dict) and item.get("key") is not None
                ]
        for value in node.values():
            walk(value)

    walk(view.get("containers"))
    return options


async def _create_options(ctx: McpContext) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, Any]], bool]:
    """返回 (options, projects, remote_options); 在线字典失败时退回静态兜底."""
    template_meta: dict[str, list[dict[str, str]]] = {}
    question_types: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    remote = False
    try:
        template_meta = await _template_options(ctx)
        remote = bool(template_meta)
    except McpRuntimeError:
        template_meta = {}
    try:
        question_types = await _ref_data(ctx, QUESTION_TYPE_REF_CODE, keyword="", page_size=50)
        remote = remote or bool(question_types)
    except McpRuntimeError:
        question_types = []
    try:
        projects = await _projects(ctx)
    except McpRuntimeError:
        projects = []
    options = schema.build_options(template_meta, question_types, projects)
    return options, projects, remote


async def _member_by_code(ctx: McpContext, code: str) -> dict[str, str]:
    if not code:
        return {}
    items = await _ref_data(ctx, MEMBER_REF_CODE, keyword=code, page_size=50, field="code")
    return next((item for item in items if item["code"] == code), {})


# ── 只读工具 ────────────────────────────────────────────────
async def whoami(ctx: McpContext) -> dict[str, Any]:
    record = await credentials.get(ctx.session, _user_id(ctx), PROVIDER)
    if record is None:
        return {"configured": False, "provider": PROVIDER}
    try:
        member = await _member_by_code(ctx, record.username)
    except McpRuntimeError:
        member = {}
    return {
        "configured": True,
        "provider": PROVIDER,
        "username": record.username,
        "user": {
            "id": member.get("id", ""),
            "code": member.get("code") or record.username,
            "name": member.get("name", ""),
        },
        "status": record.status,
        "last_login_at": record.last_login_at,
        "last_error": record.last_error,
    }


async def list_projects(ctx: McpContext, *, keyword: str = "", page_size: int = 50) -> dict[str, Any]:
    size = _clamp(page_size, 50, 50)
    items = await _projects(ctx, page_size=size)
    if keyword:
        wanted = str(keyword).strip().lower()
        items = [
            item
            for item in items
            if wanted in item["code"].lower() or wanted in item["name"].lower()
        ]
    return {"count": len(items), "items": items}


async def get_create_meta(
    ctx: McpContext, *, project_keyword: str = "", page_size: int = 50
) -> dict[str, Any]:
    options, projects, remote = await _create_options(ctx)
    if project_keyword:
        wanted = str(project_keyword).strip().lower()
        projects = [
            item
            for item in projects
            if wanted in item["code"].lower() or wanted in item["name"].lower()
        ]
    size = _clamp(page_size, 50, 50)
    return schema.describe_create_meta(options, projects[:size], remote_options=remote)


async def search_members(
    ctx: McpContext, *, keyword: str = "", page_size: int = 30
) -> dict[str, Any]:
    size = _clamp(page_size, 30, 50)
    items = await _ref_data(ctx, MEMBER_REF_CODE, keyword=keyword, page_size=size)
    return {
        "count": len(items),
        "items": [
            {"id": item["id"], "name": item["name"], "code": item["code"]}
            for item in items
        ],
    }


async def search_questions(
    ctx: McpContext,
    *,
    keyword: str = "",
    code: str = "",
    status: str = "",
    raise_person_id: str = "",
    updated_after: Any = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = _clamp(page, 1, 100000)
    size = _clamp(page_size, 20, MAX_PAGE_SIZE)
    payload = await _question_list(
        ctx,
        simple_vos=_search_vos(
            keyword=keyword,
            code=code,
            status=status,
            raise_person_id=raise_person_id,
            updated_after=updated_after,
        ),
        page=page,
        page_size=size,
    )
    items = [
        normalize.normalize_search_item(
            record, {"base": _base_url(), "url": _question_url(str(record.get("id") or ""))}
        )
        for record in payload["records"]
    ]
    total = payload["total"]
    return {
        "total": total,
        "count": len(items),
        "page": page,
        "page_size": size,
        "has_more": page * size < total,
        "items": items,
    }


async def get_question(
    ctx: McpContext,
    *,
    id: str | None = None,
    code: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    if not id and not code:
        raise McpRuntimeError("invalid_arguments", "id 或 code 至少提供一个")
    record = await _find_question(ctx, question_id=str(id or ""), code=str(code or ""))
    detail_fallback = False
    if record is None:
        if not id or code:
            raise McpRuntimeError("not_found", f"未找到问题单 {code or id}")
        record = await _question_detail(ctx, str(id))
        detail_fallback = True
    question_id = str(record.get("id") or record.get("_id") or id or "")
    question_code = str(record.get("code") or code or "")
    files = await _attachment_group_files(ctx, question_id=question_id, code=question_code)
    record = _with_files(record, files)
    try:
        template_meta = await _template_options(ctx)
    except McpRuntimeError:
        template_meta = {}
    out = normalize.normalize_question(
        record,
        {"base": _base_url(), "url": _question_url(question_id)},
        include_raw=include_raw,
        options=schema.build_options(template_meta),
    )
    if detail_fallback:
        out["detail_fallback"] = True
    return out


async def list_comments(
    ctx: McpContext,
    *,
    id: str,
    code: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    session = await _session(ctx)
    page = _clamp(page, 1, 1000)
    size = _clamp(page_size, 20, MAX_PAGE_SIZE)
    params: dict[str, Any] = {
        "fromDevice": "web",
        "pageSize": size * page,
        "billNo": QUESTION_BILL,
        "serviceCode": QUESTION_SERVICE,
        "domainKey": "IMP-BASE",
        "orgId": _org_id(session),
    }
    if code:
        params["billCode"] = code
    tenant = _tenant_id(session)
    if tenant:
        params["tenantId"] = tenant
    payload = await _request(
        ctx,
        "GET",
        f"/iuap-apcom-file/rest/v1/comment/yonbip-mm-plmrd+YonSuite/"
        f"{quote(str(id), safe='')}/comments",
        params=params,
    )
    data = payload
    if isinstance(data, dict):
        for key in ("recordList", "list", "records", "items", "commentList"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = []
    raw_items = data if isinstance(data, list) else []
    total = len(raw_items)
    start = (page - 1) * size
    items = [
        normalize.normalize_comment(item, {"base": _base_url()})
        for item in raw_items[start : start + size]
        if isinstance(item, dict)
    ]
    return {"total": total, "count": len(items), "page": page, "page_size": size, "items": items}


async def list_attachments(
    ctx: McpContext, *, id: str | None = None, code: str | None = None
) -> dict[str, Any]:
    if not id and not code:
        raise McpRuntimeError("invalid_arguments", "id 或 code 至少提供一个")
    record = await _find_question(ctx, question_id=str(id or ""), code=str(code or ""))
    if record is None:
        if not id or code:
            raise McpRuntimeError("not_found", f"未找到问题单 {code or id}")
        record = await _question_detail(ctx, str(id))
    question_id = str(record.get("id") or record.get("_id") or id or "")
    question_code = str(record.get("code") or code or "")
    files = await _attachment_group_files(ctx, question_id=question_id, code=question_code)
    record = _with_files(record, files)
    return {
        "question_id": question_id,
        "code": question_code,
        "count": len(normalize.attachments_of(record, _base_url())),
        "items": normalize.attachments_of(record, _base_url()),
    }


async def _download_candidates(ctx: McpContext, file_id: str) -> list[str]:
    base = _base_url()
    urls: list[str] = []
    if "/" in file_id:
        urls.append(base + "/yms-def-bucket/" + "/".join(quote(seg, safe="") for seg in file_id.split("/") if seg))
    else:
        try:
            payload = await _request(
                ctx,
                "POST",
                "/iuap-apcom-file/rest/v1/file/infos",
                json={"fileIds": [file_id]},
            )
        except McpRuntimeError:
            payload = None
        items = payload.get("list") if isinstance(payload, dict) else payload
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("download") or item.get("url") or item.get("filePath") or item.get("fileKey") or "")
            if not raw:
                continue
            if raw.startswith("/"):
                urls.append(base + raw)
            elif re.match(r"^https?://", raw, re.IGNORECASE):
                urls.append(raw)
            else:
                urls.append(base + "/yms-def-bucket/" + raw.lstrip("/"))
        urls.append(f"{base}/iuap-apcom-file/rest/v1/file/{quote(file_id, safe='')}/download")
        urls.append(f"{base}/iuap-apcom-file/rest/v1/file/download?fileId={quote(file_id, safe='')}")
    seen: set[str] = set()
    return [url for url in urls if url and not (url in seen or seen.add(url))]


def _download_name(target: str, file_id: str | None, name: str | None) -> str:
    if name:
        return name
    parsed = urlparse(target)
    query = parse_qs(parsed.query)
    for key in ("name", "filename", "fileName"):
        values = query.get(key) or []
        if values and values[0]:
            return unquote(values[0])
    base = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
    if base and "." in base:
        return unquote(base)
    ident = file_id or base
    for key in ("fileId", "file_id", "id"):
        values = query.get(key) or []
        if values and values[0]:
            ident = file_id or values[0]
            break
    return f"attachment-{ident or 'file'}"


async def download_attachment(
    ctx: McpContext,
    *,
    url: str | None = None,
    file_id: str | None = None,
    name: str | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    limit = min(int(max_bytes or DEFAULT_DOWNLOAD_BYTES), MAX_DOWNLOAD_BYTES)
    allowed = (urlparse(_base_url()).hostname or "").lower()
    candidates: list[str] = []
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() != allowed:
            raise McpRuntimeError("invalid_arguments", "附件地址必须与 PLM 同源")
        candidates.append(url)
    if file_id:
        candidates.extend(await _download_candidates(ctx, str(file_id)))
    if not candidates:
        raise McpRuntimeError("invalid_arguments", "url 或 file_id 至少提供一个")

    tried: list[str] = []
    last_error: McpRuntimeError | None = None
    for target in candidates:
        try:
            content, mime, detected = await _fetch_for(ctx, target, limit)
        except McpRuntimeError as exc:
            if exc.code == "attachment_too_large":
                raise
            tried.append(f"{urlparse(target).path} -> {exc.message}")
            last_error = exc
            continue
        actual = name or detected or _download_name(target, file_id, None)
        result: dict[str, Any] = {
            "content_type": mime,
            "bytes": len(content),
            "name": actual,
        }
        if mime.startswith("image/"):
            result["base64"] = base64.b64encode(content).decode("ascii")
            return result
        result["url"] = target
        return result
    detail = "; ".join(tried[-4:]) if tried else (last_error.message if last_error else "无可用地址")
    message = f"PLM 文件下载失败: {detail}"
    if file_id and not url:
        message += (
            "; file_id 仅适用于附件列表中可解析出下载地址的文件，"
            "内联截图请改用 plm_issue_list_attachments 返回的 url 直接下载"
        )
    raise McpRuntimeError("download_failed", message)


async def _fetch_for(ctx: McpContext, url: str, max_bytes: int) -> tuple[bytes, str, str]:
    try:
        content, mime, name = await session_manager.download(_user_id(ctx), url)
    except client.PlmSessionExpired as exc:
        raise McpRuntimeError(
            "integration_reauth_required", "PLM 登录态已失效，请稍后重试或重新绑定"
        ) from exc
    except client.PlmBusinessError as exc:
        raise McpRuntimeError("download_failed", str(exc)) from exc
    except client.PlmUnavailable as exc:
        raise McpRuntimeError("download_failed", f"PLM 文件服务不可达: {exc}") from exc
    if len(content) > max_bytes:
        raise McpRuntimeError("attachment_too_large", "附件超过大小上限")
    return content, mime, name


# ── 用例库 ──────────────────────────────────────────────────
async def _test_case_list(
    ctx: McpContext,
    *,
    simple_vos: list[dict[str, Any]],
    page: int,
    page_size: int,
    catalog_ids: list[str] | None = None,
) -> dict[str, Any]:
    vos = list(simple_vos)
    if catalog_ids:
        # PLM 的 ids+path 目录过滤分页会错位 (窗口重复/遗漏), 改用目录子树 id 集合过滤
        vos.append({"field": "doc_classfiy_id", "op": "in", "value1": catalog_ids})
    body = {
        "page": {"pageSize": page_size, "pageIndex": page},
        "billnum": TEST_CASE_BILL,
        "condition": {
            "commonVOs": [],
            "filtersId": TEST_CASE_FILTERS_ID,
            "simpleVOs": vos,
            "isExtend": True,
        },
        "bEmptyWithoutFilterTree": True,
        "locale": "zh_CN",
        "type": "test",
        "serviceCode": TEST_CASE_SERVICE,
        "libId": "",
        "libCatalogId": "",
        "partParam": {
            "libId": "",
            "libCatalogId": "",
            "ownedProject": "",
            "ownedProduct": "",
            "ownedOrg": "",
            "containChildren": False,
        },
        "ownDomain": "IMP-GDS",
        "tplid": TEST_CASE_TPLID,
    }
    payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/bill/list",
        params={
            "locale": "zh_CN",
            "type": "test",
            "serviceCode": TEST_CASE_SERVICE,
            "libId": "",
            "libCatalogId": "",
            "terminalType": "1",
        },
        json=body,
    )
    data = payload if isinstance(payload, dict) else {}
    records = [
        item
        for item in (data.get("recordList") or data.get("records") or [])
        if isinstance(item, dict)
    ]
    total = data.get("recordCount")
    if not isinstance(total, (int, float)):
        total = data.get("total")
    return {
        "total": int(total) if isinstance(total, (int, float)) else len(records),
        "records": records,
    }


async def _test_case_tree(ctx: McpContext) -> list[dict[str, Any]]:
    payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/bill/querytree",
        params={
            "domainKey": "IMP-BASE",
            "serviceCode": TEST_CASE_SERVICE,
            "locale": "zh_CN",
            "terminalType": "1",
        },
        json={
            "billnum": TEST_CASE_BILL,
            "treename": TEST_CASE_TREE_NAME,
            "tplid": TEST_CASE_TPLID,
        },
    )
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    nodes = payload.get("data") or payload.get("recordList") or payload.get("tree") or []
    if isinstance(nodes, dict):
        nodes = nodes.get("children") or nodes.get("recordList") or nodes.get("data") or []
    return [item for item in nodes if isinstance(item, dict)] if isinstance(nodes, list) else []


def _flatten_catalog(nodes: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        out.append(node)
        out.extend(_flatten_catalog(node.get("children")))
    return out


def _catalog_index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for node in _flatten_catalog(nodes):
        node_id = str(node.get("id") or "")
        if node_id:
            index[node_id] = node
    return index


def _catalog_label(node: dict[str, Any], index: dict[str, dict[str, Any]]) -> str:
    names: list[str] = []
    seen: set[str] = set()
    current: dict[str, Any] | None = node
    while current is not None:
        node_id = str(current.get("id") or "")
        if node_id in seen:
            break
        seen.add(node_id)
        name = str(current.get("name") or "")
        if name:
            names.append(name)
        parent = str(current.get("parent") or "")
        if not parent or parent in {"0", node_id}:
            break
        current = index.get(parent)
    return " / ".join(reversed(names))


def _prune_catalog(
    node: dict[str, Any],
    *,
    depth: int,
    max_depth: int,
    keyword: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    if state["total"] >= MAX_TREE_NODES:
        state["truncated"] = True
        return None
    state["total"] += 1
    name = str(node.get("name") or "")
    item: dict[str, Any] = {
        "id": str(node.get("id") or ""),
        "name": name,
        "code": str(node.get("code") or ""),
        "parent": str(node.get("parent") or ""),
        "path": str(node.get("path") or ""),
        "level": int(node.get("level") or depth),
        "has_children": bool(node.get("children")),
    }
    matched = bool(keyword) and keyword in name.lower()
    if matched:
        item["matched"] = True
    children = node.get("children")
    children = children if isinstance(children, list) else []
    if matched:
        return item
    if keyword and (not children or depth >= max_depth):
        state["total"] -= 1
        return None
    if not children or depth >= max_depth:
        return item
    kept: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        pruned = _prune_catalog(
            child, depth=depth + 1, max_depth=max_depth, keyword=keyword, state=state
        )
        if pruned is not None:
            kept.append(pruned)
    if keyword and not kept:
        state["total"] -= 1
        return None
    if kept:
        item["children"] = kept
    return item


async def list_case_catalogs(
    ctx: McpContext,
    *,
    catalog_id: str = "",
    keyword: str = "",
    max_depth: int = DEFAULT_TREE_DEPTH,
) -> dict[str, Any]:
    depth = _clamp(max_depth, DEFAULT_TREE_DEPTH, MAX_TREE_DEPTH)
    nodes = await _test_case_tree(ctx)
    roots: list[dict[str, Any]] = nodes
    wanted = str(catalog_id or "").strip()
    if wanted:
        node = _catalog_index(nodes).get(wanted)
        if node is None:
            raise McpRuntimeError(
                "not_found",
                f"未找到用例目录 {wanted}; 先用 plm_case_catalog_tree 查看可用目录 id",
            )
        roots = [node]
    text = str(keyword or "").strip().lower()
    state: dict[str, Any] = {"total": 0, "truncated": False}
    results = [
        item
        for item in (
            _prune_catalog(node, depth=1, max_depth=depth, keyword=text, state=state)
            for node in roots
        )
        if item is not None
    ]
    return {
        "total": state["total"],
        "depth": depth,
        "truncated": state["truncated"],
        "roots": results,
    }


async def _resolve_case_catalog(
    ctx: McpContext, *, catalog_id: str = "", catalog_name: str = ""
) -> dict[str, Any] | None:
    wanted_id = str(catalog_id or "").strip()
    name = str(catalog_name or "").strip()
    if not wanted_id and not name:
        return None
    nodes = await _test_case_tree(ctx)
    index = _catalog_index(nodes)
    if wanted_id:
        node = index.get(wanted_id)
        if node is None:
            raise McpRuntimeError(
                "catalog_not_found",
                f"未找到用例目录 {wanted_id}; 先用 plm_case_catalog_tree 查询目录 id",
            )
        return node
    wanted = name.lower()
    flattened = _flatten_catalog(nodes)
    exact = [node for node in flattened if str(node.get("name") or "").lower() == wanted]
    if len(exact) == 1:
        return exact[0]
    candidates = exact or [
        node for node in flattened if wanted in str(node.get("name") or "").lower()
    ]
    if not candidates:
        raise McpRuntimeError(
            "catalog_not_found",
            f"未找到用例目录「{name}」; 先用 plm_case_catalog_tree 按关键字查询目录 id",
        )
    if len(candidates) == 1:
        return candidates[0]
    listing = "; ".join(
        f"{_catalog_label(node, index)} ({node.get('id')})" for node in candidates[:10]
    )
    raise McpRuntimeError(
        "ambiguous_catalog",
        f"目录名「{name}」匹配到 {len(candidates)} 个节点: {listing}; 请改用唯一 catalog_id",
    )


def _case_item(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id") or record.get("_id") or "",
        "identifier": record.get("code") or "",
        "title": record.get("name") or "",
        "catalog": str(record.get("doc_classfiy_id_name") or ""),
    }


def _case_search_result(payload: dict[str, Any], page: int, size: int) -> dict[str, Any]:
    items = [_case_item(record) for record in payload["records"]]
    total = payload["total"]
    return {
        "total": total,
        "count": len(items),
        "page": page,
        "page_size": size,
        "has_more": page * size < total,
        "items": items,
    }


def _numeric_case_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", value))


async def _numeric_case_matches(
    ctx: McpContext,
    short: str,
    *,
    keyword: str = "",
    catalog_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """纯数字编号按 -编号 后缀扫描; PLM 的 code like 是子串匹配, 需再按后缀精确过滤."""
    simple: list[dict[str, Any]] = [
        {"field": "newest_flag", "op": "eq", "value1": 1},
        {"field": "code", "op": "like", "value1": f"-{short}"},
    ]
    if keyword:
        simple.append({"field": "name", "op": "like", "value1": str(keyword)})
    suffix = f"-{short.upper()}"
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    truncated = False
    for page in range(1, 6):
        payload = await _test_case_list(
            ctx,
            simple_vos=simple,
            page=page,
            page_size=MAX_PAGE_SIZE,
            catalog_ids=catalog_ids,
        )
        for record in payload["records"]:
            code = str(record.get("code") or "")
            if not code.upper().endswith(suffix):
                continue
            key = str(record.get("id") or record.get("_id") or code)
            if key in seen:
                continue
            seen.add(key)
            matches.append(record)
        if page * MAX_PAGE_SIZE >= payload["total"]:
            break
        if page == 5:
            truncated = True
    return matches, truncated


async def search_test_cases(
    ctx: McpContext,
    *,
    keyword: str = "",
    identifier: str = "",
    category: str = "",
    catalog_id: str = "",
    catalog_name: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = _clamp(page, 1, 1000)
    size = _clamp(page_size, 20, MAX_PAGE_SIZE)
    catalog = await _resolve_case_catalog(
        ctx, catalog_id=catalog_id, catalog_name=catalog_name or category
    )
    catalog_ids = (
        [str(node["id"]) for node in _flatten_catalog([catalog]) if node.get("id")]
        if catalog is not None
        else None
    )
    simple: list[dict[str, Any]] = [{"field": "newest_flag", "op": "eq", "value1": 1}]
    wanted = str(identifier or "").strip()
    if wanted:
        simple.append({"field": "code", "op": "eq", "value1": wanted})
    if keyword:
        simple.append({"field": "name", "op": "like", "value1": str(keyword)})
    payload = await _test_case_list(
        ctx, simple_vos=simple, page=page, page_size=size, catalog_ids=catalog_ids
    )
    if wanted and payload["total"] == 0 and _numeric_case_identifier(wanted):
        matches, truncated = await _numeric_case_matches(
            ctx, wanted, keyword=keyword, catalog_ids=catalog_ids
        )
        start = (page - 1) * size
        result = _case_search_result(
            {"records": matches[start : start + size], "total": len(matches)}, page, size
        )
        if truncated:
            result["truncated"] = True
        return result
    return _case_search_result(payload, page, size)


def _test_case_attributes(record: dict[str, Any]) -> dict[str, Any]:
    source = {
        "created_by": record.get("creator_userName") or record.get("creator_name") or "",
        "created_at": record.get("creationtime") or record.get("createTime") or "",
        "updated_at": record.get("pubts") or record.get("modifyTime") or "",
        "owner": record.get("own_by_name") or "",
        "revision": record.get("revision") or "",
        "use_case_type": record.get("UseCaseType") or "",
        "importance": record.get("ImportanceLevel") or "",
        "use_case_status": (
            str(record.get("usecasestatus")) if record.get("usecasestatus") is not None else ""
        ),
        "lifecycle_state": record.get("lctemplate_attribute_id_name") or "",
        "automatable": record.get("ifAutomable") or "",
        "category": record.get("doc_classfiy_id_name") or "",
        "category_path": record.get("doc_classfiy_id_name_tree") or "",
        "document_type": record.get("DocumentF") or "",
    }
    return {key: value for key, value in source.items() if value}


async def _test_case_detail(ctx: McpContext, record_id: str) -> dict[str, Any]:
    session = await _session(ctx)
    params = {
        "locale": "zh_CN",
        "type": "test",
        "serviceCode": TEST_CASE_SERVICE,
        "libId": "",
        "libCatalogId": "",
        "businessStepCode": "",
        "sbillno": TEST_CASE_BILL,
        "orgId": _org_id(session),
        "terminalType": "1",
        "billnum": TEST_CASE_DETAIL_BILL,
        "id": record_id,
        "isOnlyCount": "true",
        "pageDetail": "true",
    }
    payload = await _request(ctx, "GET", "/yonbip-mm-plmrd/bill/detail", params=params)
    return payload if isinstance(payload, dict) else {}


async def get_test_case(
    ctx: McpContext, *, identifier: str, include_raw: bool = False
) -> dict[str, Any]:
    wanted = str(identifier or "").strip()
    if not wanted:
        raise McpRuntimeError("invalid_arguments", "identifier 必填, 如 HIMA3361-8077")
    base_vos = [{"field": "newest_flag", "op": "eq", "value1": 1}]
    payload = await _test_case_list(
        ctx,
        simple_vos=base_vos + [{"field": "code", "op": "eq", "value1": wanted}],
        page=1,
        page_size=3,
    )
    record = payload["records"][0] if payload["records"] else None
    if record is None and _numeric_case_identifier(wanted):
        matches, _truncated = await _numeric_case_matches(ctx, wanted)
        if len(matches) == 1:
            record = matches[0]
        elif matches:
            listing = ", ".join(str(item.get("code") or "") for item in matches[:10])
            raise McpRuntimeError(
                "ambiguous_identifier",
                f"编号 {wanted} 匹配到 {len(matches)} 个用例: {listing}; "
                f"请改传完整编号 (如 {matches[0].get('code') or ''})",
            )
    if record is None:
        raise McpRuntimeError("not_found", f"未找到用例 {wanted}")
    detail = await _test_case_detail(ctx, str(record.get("id") or record.get("_id") or ""))
    out: dict[str, Any] = {
        "identifier": str(record.get("code") or wanted),
        "title": str(detail.get("name") or record.get("name") or ""),
        "precondition": normalize.html_to_text(detail.get("Precondition") or ""),
        "steps": normalize.step_pairs(detail.get("Step02") or "", detail.get("ExpectedResult1") or ""),
    }
    attributes = _test_case_attributes(detail)
    if attributes:
        out["attributes"] = attributes
    if include_raw:
        out["raw"] = normalize.sanitize_raw(detail)
    return out


# ── 建单校验 ────────────────────────────────────────────────
def _resolve_project(
    projects: list[dict[str, Any]], project_id: str, project_code: str
) -> dict[str, Any] | None:
    if project_id:
        for item in projects:
            if item["id"] == str(project_id):
                return item
    if project_code:
        wanted = str(project_code).strip().upper()
        for item in projects:
            if item["code"].strip().upper() == wanted:
                return item
    return None


def _create_values(args: dict[str, Any]) -> dict[str, Any]:
    values = {**schema.DEFAULTS, **args}
    return values


def _validate_or_raise(
    args: dict[str, Any], options: dict[str, list[dict[str, str]]], error: str
) -> None:
    result = schema.validate_create(args, options)
    if result["ok"]:
        return
    parts = [schema.describe_rejection(result, options)]
    if error:
        parts.append(error)
    raise McpRuntimeError(
        "invalid_arguments",
        "建单参数不合法: "
        + "。".join(item for item in parts if item)
        + "。请先调用 plm_issue_get_create_meta 获取必填字段与选项 id。",
    )


async def _preview_payload(
    ctx: McpContext, args: dict[str, Any]
) -> tuple[
    dict[str, Any],
    dict[str, str] | None,
    dict[str, list[dict[str, str]]],
    bool,
    dict[str, Any],
]:
    options, projects, remote = await _create_options(ctx)
    project = _resolve_project(
        projects, str(args.get("project_id") or ""), str(args.get("project_code") or "")
    )
    result = schema.validate_create(args, options)
    template = _description_template(args)
    description_html = _description_html(args)
    values = _create_values(args)
    values["description"] = description_html
    payload = {
        "project_id": project["id"] if project else (args.get("project_id") or ""),
        "project_code": project["code"] if project else (args.get("project_code") or ""),
        "project_name": project["name"] if project else "",
        "project_resolved": project is not None,
        "description_template": template,
        "description_text": normalize.html_to_text(description_html),
        "values": values,
        "attachments": len(args.get("attachments") or []),
    }
    return result, project, options, remote, payload


async def preview_question(ctx: McpContext, **args: Any) -> dict[str, Any]:
    result, project, options, remote, payload = await _preview_payload(ctx, args)
    hints: list[str] = []
    problems: list[str] = []
    rejection = schema.describe_rejection(result, options)
    if rejection:
        problems.append(rejection)
    if result["error"]:
        problems.append(result["error"])
    if project is None:
        problems.append(
            "关联项目未匹配: 先用 plm_common_list_projects 确认 project_id / project_code, 缺项目会拒绝建单"
        )
        hints.append("关联项目不在当前账号可见项目列表中: 先用 plm_common_list_projects 取 project_id / project_code")
    if not remote:
        hints.append("未取到 PLM 在线字典, 下拉选项为内置兜底值; 建单前请重试 plm_issue_get_create_meta")
    return {
        "ok": bool(result["ok"] and project is not None),
        "missing_required": result["missing_required"],
        "invalid_options": result["invalid_options"],
        "missing_fields": [
            schema.requirement_detail(key, options) for key in result["missing_required"]
        ],
        "invalid_fields": [
            schema.requirement_detail(item["key"], options, value=item["value"])
            for item in result["invalid_options"]
        ],
        "error": "; ".join(problems),
        "hints": hints,
        "payload": payload,
    }


# ── 附件上传 ────────────────────────────────────────────────
def _upload_query(org_id: str, bill_field: str = "问题附件") -> dict[str, str]:
    return {
        "authId": QUESTION_SERVICE,
        "buttonPrefix": "iuapfile-public",
        "billNo": QUESTION_BILL,
        "dynamicAuthToken": "",
        "servicePrefix": BUSTYPE,
        "domainApp": "IMP-BASE+mdf",
        "fromDevice": "web",
        "verifyState": "0",
        "billId": "",
        "serviceCode": QUESTION_SERVICE,
        "domainKey": "IMP-BASE",
        "transtype": BUSTYPE,
        "orgId": org_id,
        "authFix": "",
        "authfix": "",
        "billName": "问题管理",
        "billField": bill_field,
        "locale": "zh_CN",
        "sbillno": QUESTION_LIST,
    }


def _key_iv(value: str) -> tuple[bytes, bytes]:
    dash = value.rfind("-")
    if dash <= 0:
        raise McpRuntimeError("plm_error", "PLM 附件 jssdk 返回的 KeyIvParameter 非法")
    key = value[:dash].encode("utf-8")[:8]
    iv = value[dash + 1 :].encode("utf-8")[:8]
    if len(key) != 8 or len(iv) != 8:
        raise McpRuntimeError("plm_error", "PLM 附件加密参数长度不足")
    return key, iv


def _des_decrypt(key_iv_value: str, ciphertext: str) -> dict[str, Any]:
    key, iv = _key_iv(key_iv_value)
    try:
        raw = base64.b64decode(ciphertext)
    except (binascii.Error, ValueError) as exc:
        raise McpRuntimeError("plm_error", "PLM 附件密文不是合法 base64") from exc
    decryptor = Cipher(algorithms.TripleDES(key * 3), modes.CBC(iv)).decryptor()
    plain = decryptor.update(raw) + decryptor.finalize()
    pad = plain[-1] if plain else 0
    if pad and pad <= 8:
        plain = plain[:-pad]
    try:
        info = json.loads(plain.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise McpRuntimeError("plm_error", "PLM 附件密文解密失败") from exc
    return info if isinstance(info, dict) else {}


async def _bill_add_slot(ctx: McpContext, org_id: str) -> str:
    session = await _session(ctx)
    xsrf = _xsrf(session)
    headers = {"X-XSRF-TOKEN": xsrf} if xsrf else {}
    payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/bill/add",
        params={
            "terminalType": "1",
            "locale": "zh_CN",
            "serviceCode": QUESTION_SERVICE,
            "tenantId": TENANT_ID,
            "sbillno": QUESTION_LIST,
            "orgId": org_id,
            "billnum": QUESTION_BILL,
        },
        json={"billnum": QUESTION_BILL, "data": "{}"},
        headers=headers,
        ajax=False,
    )
    return str((payload or {}).get("attachmentId") or "") if isinstance(payload, dict) else ""


async def _upload_once(
    ctx: McpContext, *, name: str, content: bytes, business_id: str, org_id: str
) -> dict[str, Any]:
    params = {**_upload_query(org_id), "addTag": "false"}
    sdk = await _request(
        ctx, "GET", "/iuap-apcom-file/rest/v1/jssdk/version", params=params
    )
    key_iv = ""
    if isinstance(sdk, dict):
        key_iv = str(sdk.get("KeyIvParameter") or "")
        if not key_iv and isinstance(sdk.get("data"), dict):
            key_iv = str(sdk["data"].get("KeyIvParameter") or "")
    if not key_iv:
        raise McpRuntimeError("plm_error", "PLM 附件 jssdk 未返回 KeyIvParameter")

    suffix = name.rsplit(".", 1)[-1] if "." in name else ""

    create = await _request(
        ctx,
        "POST",
        "/iuap-apcom-file/rest/v2/file/createFileUploadTask",
        params=params,
        json={
            "businessId": business_id,
            "businessType": "IMP-BASE+mdf",
            "fileMd5Hex": hashlib.md5(content).hexdigest(),
            "fileName": name,
            "fileSize": len(content),
            "fileSuffix": suffix,
            "isTemp": 0,
            "columnId": "",
            "groupId": "",
            "usePrivateBucket": True,
            "delayDeleteTime": -1,
        },
    )
    data = create if isinstance(create, dict) else {}
    cache_id = str(data.get("cacheId") or "")
    ciphertext = str(data.get("ciphertext") or "")
    if data.get("state") != 2 or not cache_id or not ciphertext:
        raise McpRuntimeError(
            "plm_error",
            f"PLM 附件 createFileUploadTask 返回异常 (state={data.get('state')})",
        )

    target = _des_decrypt(key_iv, ciphertext)
    put_url = str(target.get("url") or "")
    if not put_url:
        raise McpRuntimeError("plm_error", "PLM 附件上传地址缺失")
    put_headers = target.get("headers") if isinstance(target.get("headers"), dict) else {}
    status = await session_manager.upload(
        _user_id(ctx), put_url, content, {str(k): str(v) for k, v in put_headers.items()}
    )
    if status >= 400:
        raise McpRuntimeError("plm_error", f"PLM 附件上传失败 (HTTP {status})")

    saved = await _request(
        ctx,
        "POST",
        "/iuap-apcom-file/rest/v2/file/saveFileUploadBusiness",
        params=params,
        json={"cacheId": cache_id},
    )
    files = saved.get("data") if isinstance(saved, dict) else []
    file_obj = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    file_id = str(file_obj.get("id") or "")
    if not file_id:
        raise McpRuntimeError("plm_error", "PLM 附件保存未返回文件 id")
    return {"file_id": file_id, "file": file_obj, "business_id": business_id, "name": name}


def _human_size(value: int) -> str:
    if value < 1024:
        return f"{value} bytes"
    for unit in ("KB", "MB", "GB"):
        value_float = value / 1024
        if value_float < 1024:
            return f"{value_float:.2f}{unit}"
        value = int(value_float)
    return f"{value} bytes"


def _format_time(value: Any) -> str:
    if isinstance(value, (int, float)) and value:
        moment = datetime.fromtimestamp(value / (1000 if value >= 1e12 else 1))
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip())
        except ValueError:
            return value.strip()
    else:
        moment = datetime.now()
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _accessory_entries(uploaded: list[dict[str, Any]], slots: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(uploaded):
        file_obj = item["file"]
        name = str(item["name"])
        base_name = re.sub(r"\.[^.]+$", "", name) or str(file_obj.get("fileName") or "")
        suffix = str(file_obj.get("fileExtension") or "").lstrip(".") or (
            name.rsplit(".", 1)[-1] if "." in name else ""
        )
        slot = slots[index] if index < len(slots) else ""
        entries.append(
            {
                "_status": "Insert",
                "attachmentId": slot,
                "ttt_id": f"rowId_{index + 1}",
                "hasDefaultInit": True,
                "filename": base_name,
                "suffix": suffix,
                "filesize": _human_size(int(file_obj.get("fileSize") or len(name))),
                "creator_userName": str(file_obj.get("userName") or ""),
                "creator": str(file_obj.get("yhtUserId") or ""),
                "url": str(file_obj.get("filePath") or ""),
                "md5": str(file_obj.get("md5Hex") or ""),
                "shadowLinkCode": str(file_obj.get("sign") or "")[:24],
                "creationtime": _format_time(file_obj.get("ctime")),
            }
        )
    return entries


# ── 建单 ────────────────────────────────────────────────────
async def _reserve_code(ctx: McpContext, question_type_id: str) -> dict[str, Any]:
    """按 PLM UI 流程预占 WSD 单号; 处理人/项目/类型不合规时不会走到这里."""
    try:
        await _request(
            ctx,
            "POST",
            "/yonbip-mm-plmrd/questionCgr/allowCreateQuestion",
            params={"terminalType": "1"},
            json={"id": question_type_id},
            ajax=False,
        )
    except McpRuntimeError:
        pass  # PLM 该步校验较松, 失败也继续

    detail: dict[str, Any] = {}
    for attempt in range(2):
        try:
            payload = await _request(
                ctx,
                "POST",
                "/yonbip-mm-plmrd/questionCgr/getLcDetail",
                params={"terminalType": "1"},
                json={"id": question_type_id},
                ajax=False,
            )
        except McpRuntimeError:
            payload = None
        inner = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(inner, dict) and inner.get("schId"):
            detail = inner
            break
        if attempt == 0:
            await asyncio.sleep(0.5)
    if not detail.get("schId"):
        raise McpRuntimeError(
            "plm_error",
            f"PLM 未能返回问题类型流程 (questionCgrId={question_type_id or '空'}, getLcDetail schId 为空)。"
            "请用 plm_issue_get_create_meta 重新确认有效的问题类型 id。",
        )

    code_payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/questionCgr/getCode",
        params={"terminalType": "1"},
        json={"userId": str(detail["schId"])},
        ajax=False,
    )
    code_data = code_payload if isinstance(code_payload, dict) else {}
    code = str(code_data.get("code") or "")
    bill_id = str(code_data.get("id") or "")
    if not _WSD_RE.match(code) or not bill_id:
        raise McpRuntimeError(
            "plm_error",
            f"PLM 未生成合规问题单号 (questionCgrId={question_type_id or '空'}, code={code or '空'})。"
            "请用 plm_issue_get_create_meta 重新获取有效的问题类型 id 后重试。",
        )
    return {
        "code": code,
        "id": bill_id,
        "sch_id": str(detail.get("schId") or ""),
        "lct_id": str(detail.get("lctId") or ""),
        "lct_name": str(detail.get("lctId_name") or ""),
        "begin_state_id": str(detail.get("begin_state_id") or ""),
        "begin_state_name": str(detail.get("begin_state_name") or detail.get("begin_state_id_name") or ""),
    }


DESCRIPTION_TEMPLATES = ("standard", "custom")


def _description_template(args: dict[str, Any]) -> str:
    template = str(args.get("description_template") or "standard").strip()
    if template not in DESCRIPTION_TEMPLATES:
        raise McpRuntimeError(
            "invalid_arguments",
            f"description_template 不支持 {template}; "
            "合法值: standard (默认标准 10 段模板)、custom (自定义 description)",
        )
    return template


def _description_html(args: dict[str, Any]) -> str:
    template = _description_template(args)
    if template == "standard":
        fields = args.get("description_fields")
        if fields is not None and not isinstance(fields, dict):
            raise McpRuntimeError("invalid_arguments", "description_fields 必须是对象")
        return templates.render_description(fields)
    raw = str(args.get("description") or args.get("qusDescribe") or "").strip()
    if raw:
        return raw
    return f"<p>{html.escape(str(args.get('name') or ''))}</p>"


def _build_save_fields(
    args: dict[str, Any],
    *,
    project: dict[str, Any],
    question_type_name: str,
    reserved: dict[str, Any],
    raise_person: str,
    raise_person_name: str,
    biz_user: str,
    slots: list[str],
    uploaded: list[dict[str, Any]],
    description_html: str,
) -> dict[str, Any]:
    now = datetime.now()
    values = _create_values(args)
    raise_name = raise_person_name or ""
    owned_org = str(args.get("ownedorg") or DEFAULT_ORG_ID)
    owned_org_name = str(args.get("ownedorg_name") or DEFAULT_ORG_NAME)
    dept_id = str(args.get("dept_id") or DEFAULT_DEPT_ID)
    dept_name = str(args.get("dept_id_name") or DEFAULT_DEPT_NAME)
    creator = biz_user or raise_person
    attachment_id = slots[0] if slots else ""
    business_id = uploaded[0]["business_id"] if uploaded else ""

    fields: dict[str, Any] = {
        "name": str(args.get("name") or ""),
        "code": reserved["code"],
        "id": reserved["id"],
        "qusDescribe": description_html,
        "reviewerPerson": raise_person,
        "reviewerPerson_name": raise_name,
        "raisePerson": raise_person,
        "raisePerson_name": raise_name,
        "owner": raise_person,
        "owner_name": raise_name,
        "creator": creator,
        "creator_userName": raise_name,
        "modifier": creator,
        "modifier_userName": raise_name,
        "assignPerson": raise_person,
        "assignPerson_name": raise_name,
        "solvePerson": raise_person,
        "solvePerson_name": raise_name,
        "confirmPerson": raise_person,
        "confirmPerson_name": raise_name,
        "TESTPEOPLE": raise_person,
        "TESTPEOPLE_name": raise_name,
        "ownedorg": owned_org,
        "ownedorg_name": owned_org_name,
        "created_org": owned_org,
        "created_org_name": owned_org_name,
        "createorg": owned_org,
        "createorg_name": owned_org_name,
        "createOrg": owned_org,
        "createOrg_name": owned_org_name,
        "dept_id": dept_id,
        "dept_id_name": dept_name,
        "sch_id": reserved["sch_id"],
        "wfId": "",
        "lctemplate_id": reserved["lct_id"],
        "lctemplate_id_name": reserved["lct_name"],
        "lctemplate_id_code": "Question_Template_Use",
        "lctemplate_attribute_id": reserved["begin_state_id"],
        "lctemplate_attribute_id_name": reserved["begin_state_name"],
        "lctemplate_attribute_id_code": "Draft",
        "ques_status": DEFAULT_QUESTION_CODE,
        "ques_status_name": DEFAULT_QUESTION_STATE_NAME,
        "quesDefineCharacter": {},
        "quesProcessType": "questionClose,questionSubmit",
        "questionCgrId": str(args.get("questionCgrId") or ""),
        "questionCgrId_name": question_type_name,
        "quesBelongArea": values.get("quesBelongArea") or "",
        "QuesmoduleSel": values.get("QuesmoduleSel") or "",
        "questionPriority": values.get("questionPriority") or "",
        "quesSever": values.get("quesSever") or "",
        "questestfile": "Y",
        "projectJD": values.get("projectJD") or "",
        "associatedObjectCode": project["code"],
        "associatedObjectName": project["name"],
        "questionTdArea": values.get("questionTdArea") or "",
        "genyinfenxi": values.get("genyinfenxi") or "NA",
        "attribute1": values.get("attribute1") or "NA",
        "attribute2": values.get("attribute2") or "",
        "discoveryTime": now.strftime("%Y-%m-%d"),
        "resolutionTime": (now + timedelta(days=15)).strftime("%Y-%m-%d"),
        "bustype": BUSTYPE,
        "verifystate": 0,
        "que_procetype": "1",
        "wfstate": 0,
        "item238si": ITEM238SI_HTML,
        "attachmentId": attachment_id,
        "holdFile": "",
        "resumeFile": "",
        "que_files1": business_id,
        "que_files2": "",
        "que_files3": "",
        "solveAccessoryList": "",
        "tenant": TENANT_ID,
        "ytenant": TENANT_ID,
        "tenantid": TENANT_ID,
        "_status": "Insert",
        "isWfControlled": False,
        "associationObjectList": [
            {
                "object_type": 0,
                "object_id": project["id"],
                "code": project["code"],
                "name": project["name"],
                "type": "1",
                "_status": "Insert",
            }
        ],
        "informGroupList": [],
        "accessoryList": _accessory_entries(uploaded, slots) if len(uploaded) > 1 else [],
        "historyRedList": [],
        "question_questionTagList": [],
    }
    return fields


async def _save(ctx: McpContext, fields: dict[str, Any], org_id: str) -> dict[str, Any]:
    headers = {
        "Referer": (
            f"{_base_url()}/mdf-node/meta/voucherlist/{QUESTION_LIST}"
            "?domainKey=IMP-BASE&locale=zh_CN"
            f"&serviceCode={QUESTION_SERVICE}&tenantId={TENANT_ID}"
        )
    }
    payload = await _request(
        ctx,
        "POST",
        "/yonbip-mm-plmrd/bill/save",
        params={
            "cmdname": "cmdSave",
            "businessActName": "问题管理-保存",
            "terminalType": "1",
            "serviceCode": QUESTION_SERVICE,
            "sbillno": QUESTION_LIST,
            "orgId": org_id,
        },
        json={"billnum": QUESTION_BILL, "data": json.dumps(fields, ensure_ascii=False)},
        headers=headers,
        ajax=False,
    )
    return payload if isinstance(payload, dict) else {}


async def _upload_attachments(
    ctx: McpContext, attachments: list[dict[str, Any]], org_id: str
) -> tuple[list[str], list[dict[str, Any]]]:
    business_id = "mdf_" + str(uuid.uuid4())
    slots: list[str] = []
    uploaded: list[dict[str, Any]] = []
    for index, item in enumerate(attachments):
        if index:
            await asyncio.sleep(0.2)
        slot = await _bill_add_slot(ctx, org_id)
        if not slot:
            raise McpRuntimeError("plm_error", f"附件 {item['name']} 未取得 PLM 附件槽位")
        try:
            result = await _upload_once(
                ctx,
                name=item["name"],
                content=item["content"],
                business_id=business_id,
                org_id=org_id,
            )
        except McpRuntimeError as exc:
            raise McpRuntimeError(
                "plm_error", f"附件 {item['name']} 上传失败: {exc.message}"
            ) from exc
        slots.append(slot)
        uploaded.append(result)
    return slots, uploaded


async def create_question(
    ctx: McpContext,
    *,
    confirm: bool,
    client_request_id: str | None = None,
    **args: Any,
) -> dict[str, Any]:
    if confirm is not True:
        raise McpRuntimeError(
            "confirmation_required", "写操作需要显式 confirm=true 确认后才会提交"
        )
    if client_request_id:
        key = f"mcp:plm:create:{_user_id(ctx)}:{client_request_id}"
        async with redis_client() as redis:
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)

    options, projects, remote = await _create_options(ctx)
    project = _resolve_project(
        projects, str(args.get("project_id") or ""), str(args.get("project_code") or "")
    )
    if project is None:
        wanted = ", ".join(
            part
            for part in (
                f"project_id={args.get('project_id')}" if args.get("project_id") else "",
                f"project_code={args.get('project_code')}" if args.get("project_code") else "",
            )
            if part
        )
        reason = (
            f"传入的 {wanted} 未匹配到当前账号可见项目"
            if wanted
            else "project_id / project_code 均为空"
        )
        raise McpRuntimeError(
            "invalid_arguments",
            f"必须关联项目: {reason}。"
            "请先调用 plm_common_list_projects 获取项目 id 或 code 后再建单。",
        )
    args = {**args, "project_id": project["id"]}
    _validate_or_raise(args, options, "")
    description_html = _description_html(args)

    question_type_id = str(args.get("questionCgrId") or "")
    question_type_name = next(
        (item["name"] for item in options.get("questionCgrId", []) if item["id"] == question_type_id),
        "",
    )
    raise_person = str(args.get("raisePerson") or "")
    if not raise_person:
        raise McpRuntimeError("raisePerson_required", "提单必须指定下一步处理人 raisePerson")

    session = await _session(ctx)
    org_id = _org_id(session)
    biz_user = _biz_user_id(session)

    reserved = await _reserve_code(ctx, question_type_id)
    existing = await _find_question(ctx, code=reserved["code"])
    if existing is not None:
        raise McpRuntimeError(
            "plm_duplicate_code",
            f"问题单号 {reserved['code']} 已存在, 已中止提交以避免重复提单",
        )

    attachments = schema.attachment_payloads(args.get("attachments"))
    slots: list[str] = []
    uploaded: list[dict[str, Any]] = []
    if attachments:
        slots, uploaded = await _upload_attachments(ctx, attachments, org_id)

    fields = _build_save_fields(
        args,
        project=project,
        question_type_name=question_type_name,
        reserved=reserved,
        raise_person=raise_person,
        raise_person_name=str(args.get("raisePerson_name") or ""),
        biz_user=biz_user,
        slots=slots,
        uploaded=uploaded,
        description_html=description_html,
    )
    received = await _save(ctx, fields, org_id)

    verified = await _verify_saved(ctx, reserved["code"], raise_person)
    if not verified["found"]:
        raise McpRuntimeError(
            "plm_verify_failed",
            f"PLM /save 返回成功但问题单 {reserved['code']} 未落库"
            f" (原因: {verified['reason']}), 请人工确认后再重试",
        )
    if not verified["handler_ok"]:
        raise McpRuntimeError(
            "plm_verify_failed",
            f"问题单 {reserved['code']} 已创建但处理人未写入 (期望 {raise_person}), "
            "请到 PLM 核对后再决定是否补录",
        )

    saved_id = str(verified["record"].get("id") or reserved["id"])
    result = {
        "ok": True,
        "id": saved_id,
        "code": reserved["code"],
        "url": _question_url(saved_id),
        "project": {"id": project["id"], "code": project["code"], "name": project["name"]},
        "raise_person": verified["record"].get("raisePerson") or raise_person,
        "status": normalize.status_of(verified["record"]),
        "attachments": len(uploaded),
        "verified": True,
        "remote_options": remote,
        "save_response": received,
    }
    if client_request_id:
        key = f"mcp:plm:create:{_user_id(ctx)}:{client_request_id}"
        async with redis_client() as redis:
            await redis.set(
                key, json.dumps(result, ensure_ascii=False, default=str), ex=IDEMPOTENCY_TTL
            )
    return result


async def _verify_saved(
    ctx: McpContext, code: str, raise_person: str
) -> dict[str, Any]:
    payload = await _question_list(
        ctx, simple_vos=_search_vos(code=code), page=1, page_size=10
    )
    record = next(
        (item for item in payload["records"] if str(item.get("code") or "") == code), None
    )
    if record is None:
        return {"found": False, "handler_ok": False, "reason": "/bill/list 查不到该单号", "record": {}}
    actual = normalize.person_of(record, "raisePerson")
    handler_ok = not raise_person or actual["id"] == raise_person
    reason = "" if handler_ok else f"处理人={actual['id'] or '空'}"
    return {"found": True, "handler_ok": handler_ok, "reason": reason, "record": record}


# ── 评论 ────────────────────────────────────────────────────
async def add_comment(
    ctx: McpContext, *, id: str, content: str, confirm: bool, code: str = ""
) -> dict[str, Any]:
    if confirm is not True:
        raise McpRuntimeError(
            "confirmation_required", "写操作需要显式 confirm=true 确认后才会提交"
        )
    text = str(content or "").strip()
    if not text:
        raise McpRuntimeError("invalid_arguments", "评论内容 content 不能为空")
    session = await _session(ctx)
    org_id = _org_id(session)
    xsrf = _xsrf(session)
    headers: dict[str, str] = {
        "domain-key": "IMP-BASE",
        "Referer": (
            f"{_base_url()}/mdf-node/meta/voucher/{QUESTION_BILL}/{quote(str(id), safe='')}"
            f"?domainKey=IMP-BASE&locale=zh_CN&serviceCode={QUESTION_SERVICE}"
        ),
    }
    if xsrf:
        headers["X-XSRF-TOKEN"] = xsrf
    payload = await _request(
        ctx,
        "POST",
        f"/iuap-apcom-file/rest/v1/comment/yonbip-mm-plmrd+YonSuite/"
        f"{quote(str(id), safe='')}/add",
        params={
            "verifyState": "0",
            "billCode": code or "",
            "billNo": QUESTION_BILL,
            "billId": id,
            "serviceCode": QUESTION_SERVICE,
            "domainKey": "IMP-BASE",
            "transtype": BUSTYPE,
            "orgId": org_id,
            "authId": QUESTION_SERVICE,
            "authFix": "",
            "dynamicAuthIdPrefix": BUSTYPE,
            "authfix": "",
            "buttonAuthId": f"{QUESTION_SERVICE}_ecsuite666",
            "billName": "问题管理",
            "billField": "",
            "fromDevice": "web",
            "buttonPrefix": f"{QUESTION_SERVICE}_ecsuite666",
            "servicePrefix": BUSTYPE,
            "locale": "zh_CN",
            "businessStepCode": "",
            "sbillno": QUESTION_LIST,
        },
        json={
            "v": "1.0",
            "qzId": "",
            "content": text,
            "notifyList": [],
            "fileIds": [],
            "sendMsg": False,
        },
        headers=headers,
        ajax=False,
    )
    data = payload if isinstance(payload, dict) else {}
    return {"ok": True, "id": str(data.get("id") or ""), "question_id": id}
