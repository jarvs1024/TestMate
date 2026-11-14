"""PLM MCP 域: 15 个工具 schema/scope、只读适配、严格建单与幂等 (mock 上游)."""
from __future__ import annotations

import base64
import json
import json as jsonlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.db.session import AsyncSessionLocal
from app.integrations import crypto
from app.integrations.plm import client as plm_client
from app.integrations.plm import session_manager
from app.mcp.common.context import McpContext, Principal
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.plm import adapter
from app.mcp.plm.server import build_plm_server
from app.models.integration import IntegrationCredential
from app.models.user import User, UserRole
from tests._mcp_protocol import call_tool, list_tools

PUBLIC_BASE = "http://test"
ENDPOINT = "/mcp/plm"
TOKEN = "plm-token"

TOOL_REQUIRED = {
    "plm_common_whoami": set(),
    "plm_common_list_projects": set(),
    "plm_common_search_members": set(),
    "plm_issue_get_create_meta": set(),
    "plm_issue_search": set(),
    "plm_issue_get": set(),
    "plm_issue_list_comments": {"id"},
    "plm_issue_list_attachments": set(),
    "plm_issue_download_attachment": set(),
    "plm_case_search": set(),
    "plm_case_get": {"identifier"},
    "plm_case_catalog_tree": set(),
    "plm_issue_preview": set(),
    "plm_issue_create": {"confirm"},
    "plm_issue_add_comment": {"id", "content", "confirm"},
}

GROUP_ID = "mdf_11111111-1111-1111-1111-111111111111"


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def eval(self, script, numkeys, *args):
        return [1, "ok"]

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class _Verifier(TokenVerifier):
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def verify_token(self, token):
        if token != TOKEN:
            return None
        return AccessToken(
            token=token,
            client_id=self.principal.client_id,
            scopes=sorted(self.principal.scopes),
            subject=str(self.principal.user.id),
            claims={"principal": self.principal},
        )


@pytest.fixture
async def user():
    async with AsyncSessionLocal() as session:
        item = User(
            username=f"plm-mcp-{uuid.uuid4().hex[:8]}",
            password_hash="unused",
            role=UserRole.tester,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


@pytest.fixture
async def bound_user(user):
    async with AsyncSessionLocal() as session:
        session.add(
            IntegrationCredential(
                user_id=user.id,
                provider="plm",
                username="demo-plm",
                secret_encrypted=crypto.encrypt_secret(
                    "secret-pass", user_id=user.id, provider="plm"
                ),
                token_encrypted=crypto.encrypt_secret(
                    "access-token", user_id=user.id, provider="plm"
                ),
                cookies_encrypted=crypto.encrypt_secret(
                    json.dumps({"orgId": "org-1", "tenantid": "tenant-1", "at": "1234567890123456789"}),
                    user_id=user.id,
                    provider="plm",
                ),
                status="ok",
                token_expires_at=None,
            )
        )
        await session.commit()
    user.username = "demo-plm"
    return user


def _session() -> plm_client.PlmSession:
    return plm_client.PlmSession(
        access_token="access-token",
        username="demo-plm",
        display_name="demo-plm",
        cookies={
            "orgId": "org-1",
            "tenantid": "tenant-1",
            "at": "1234567890123456789",
            "XSRF-TOKEN": "xsrf",
        },
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


class FakeAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.routes = {}
        self.uploads: list[dict] = []
        self.saved_fields: dict | None = None
        self.records: list[dict] = []

    async def ensure_session(self, user_id, *, force=False):
        return _session()

    async def request(self, user_id, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        handler = self.routes.get(path)
        if handler is None:
            raise AssertionError(f"unexpected request {method} {path}")
        return handler(**kwargs)

    async def upload(self, user_id, url, content, headers):
        self.uploads.append({"url": url, "content": content, "headers": headers})
        return 200

    async def download(self, user_id, url):
        handler = self.routes.get("__download__")
        assert handler is not None
        return handler(url)

    def paths(self) -> list[str]:
        return [call["path"] for call in self.calls]


@pytest.fixture
def fake_api(monkeypatch):
    api = FakeAPI()
    redis = _FakeRedis()

    @asynccontextmanager
    async def redis_factory():
        yield redis

    monkeypatch.setattr(session_manager, "ensure_session", api.ensure_session)
    monkeypatch.setattr(session_manager, "request", api.request)
    monkeypatch.setattr(session_manager, "upload", api.upload)
    monkeypatch.setattr(session_manager, "download", api.download)
    monkeypatch.setattr(adapter, "redis_client", redis_factory)
    api.redis = redis
    return api


def _install_common_routes(api: FakeAPI) -> None:
    api.routes["/yonbip-mm-plmrd/pub/ref/getRefMeta"] = lambda **_: {
        "refEntity": {"cFilterId": "filter-1", "outDomain": "ucf-staff-center"},
        "gridMeta": {"viewmodel": {"defTplId": "tpl-1"}},
    }
    api.routes["/mdf-node/client/getInitFilterInfo"] = lambda **_: [
        {"data": {"schemeInfoVO": {"schemeId": "sol-1"}}}
    ]

    def ref_data(params=None, **_):
        code = (params or {}).get("refCode")
        if code == adapter.QUESTION_TYPE_REF_CODE:
            return {"recordList": [{"id": "qt1", "name": "软件缺陷", "code": "QT"}]}
        if code == adapter.MEMBER_REF_CODE:
            return {"recordList": [{"id": "u1", "name": "张三", "code": "1001"}]}
        if code == adapter.PROJECT_REF_CODE:
            return {
                "recordList": [
                    {"id": "proj1", "code": "TIANFU", "name": "天府项目", "principal_name": "张三"}
                ]
            }
        raise AssertionError(f"unexpected refCode {code}")

    api.routes["/yonbip-mm-plmrd/bill/ref/getRefData"] = ref_data
    api.routes["/mdf-node/meta"] = lambda **_: {"viewmeta": {"view": {"containers": []}}}


def _install_question_routes(api: FakeAPI, *, existing: dict | None = None) -> None:
    q = existing or {}

    def list_route(json=None, **_):
        body = json or {}
        if body.get("billnum") != adapter.QUESTION_LIST:
            return {"recordList": [], "recordCount": 0}
        vos = (body.get("condition") or {}).get("simpleVOs") or []
        wanted = next((v.get("value1") for v in vos if v.get("field") == "code"), None)
        records = [r for r in api.records if not wanted or r.get("code") == wanted]
        if q.get("code") and not api.records:
            records = [q] if not wanted or q["code"] == wanted else []
        return {"recordList": records, "recordCount": len(records)}

    api.routes["/yonbip-mm-plmrd/bill/list"] = list_route

    def detail_route(params=None, **_):
        if (params or {}).get("billnum") == adapter.TEST_CASE_DETAIL_BILL:
            return {
                "name": "掉盘后恢复",
                "Precondition": "<p>设备已连接</p>",
                "Step02": "<p>1. 插拔</p><p>2. 上电</p>",
                "ExpectedResult1": "<p>1. 识别</p><p>2. 正常</p>",
            }
        return dict(q)

    api.routes["/yonbip-mm-plmrd/bill/detail"] = detail_route


@asynccontextmanager
async def _context(user: User, scopes=("plm:read", "plm:write")):
    async with AsyncSessionLocal() as session:
        principal = Principal(
            user=user, client_id="test-client", scopes=frozenset(scopes)
        )
        yield McpContext(principal=principal, session=session)


@asynccontextmanager
async def _server(principal: Principal):
    server = build_plm_server(
        public_base_url=PUBLIC_BASE,
        allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    server._token_verifier = _Verifier(principal)
    dispatcher = build_dispatcher({"plm": server})
    app = FastAPI()
    app.mount("/mcp", dispatcher)
    async with (
        run_mcp_lifespan(dispatcher),
        AsyncClient(transport=ASGITransport(app=app), base_url=PUBLIC_BASE) as client,
    ):
        yield client


# ── 契约: 15 个工具与严格 schema ────────────────────────────
async def test_tools_list_exposes_fifteen_strict_schemas(user):
    principal = Principal(
        user=user, client_id="test-client", scopes=frozenset({"plm:read"})
    )
    async with _server(principal) as client:
        payload = await list_tools(client, TOKEN, endpoint=ENDPOINT)

    tools = {tool["name"]: tool for tool in payload["tools"]}
    assert set(tools) == set(TOOL_REQUIRED)
    for name, required in TOOL_REQUIRED.items():
        schema = tools[name]["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, name
        assert set(schema.get("required", [])) == required, name


async def test_write_tool_requires_scope(user):
    principal = Principal(
        user=user, client_id="test-client", scopes=frozenset({"plm:read"})
    )
    async with _server(principal) as client:
        result = await call_tool(
            client,
            TOKEN,
            "plm_issue_create",
            {
                "name": "x",
                "questionCgrId": "qt1",
                "raisePerson": "u1",
                "quesBelongArea": "1",
                "QuesmoduleSel": "1",
                "projectJD": "3",
                "questionTdArea": "1",
                "questionPriority": "1",
                "quesSever": "2",
                "attribute2": "FW1",
                "confirm": True,
            },
            endpoint=ENDPOINT,
        )

    assert result.get("isError") is True
    assert "scope" in result["content"][0]["text"].lower()


async def test_create_explains_missing_required_over_protocol(bound_user, fake_api):
    _install_common_routes(fake_api)
    principal = Principal(
        user=bound_user, client_id="test-client", scopes=frozenset({"plm:read", "plm:write"})
    )
    async with _server(principal) as client:
        result = await call_tool(
            client,
            TOKEN,
            "plm_issue_create",
            {
                "name": "x",
                "project_code": "TIANFU",
                "questionCgrId": "qt1",
                "raisePerson": "u1",
                "confirm": True,
            },
            endpoint=ENDPOINT,
        )

    text = result["content"][0]["text"]
    assert result.get("isError") is True
    assert "缺少必填" in text
    assert "问题归属领域" in text
    assert "quesBelongArea" in text
    assert "attribute2" in text
    assert "1=硬件" in text


async def test_unknown_argument_is_rejected(user):
    principal = Principal(
        user=user, client_id="test-client", scopes=frozenset({"plm:read"})
    )
    async with _server(principal) as client:
        result = await call_tool(
            client, TOKEN, "plm_common_whoami", {"unexpected": True}, endpoint=ENDPOINT
        )
    assert result.get("isError") is True


# ── 只读适配 ───────────────────────────────────────────────
async def test_whoami_reports_bound_account(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.whoami(ctx)
    assert data["configured"] is True
    assert data["username"] == "demo-plm"
    assert data["status"] == "ok"


async def test_whoami_resolves_name_by_login_code(bound_user, fake_api):
    _install_common_routes(fake_api)

    def ref_data(params=None, **_):
        assert (params or {}).get("refCode") == adapter.MEMBER_REF_CODE
        return {"recordList": [{"id": "u9", "name": "贾克江", "code": "demo-plm"}]}

    fake_api.routes["/yonbip-mm-plmrd/bill/ref/getRefData"] = ref_data
    async with _context(bound_user) as ctx:
        data = await adapter.whoami(ctx)

    assert data["user"] == {"id": "u9", "code": "demo-plm", "name": "贾克江"}
    body = next(c for c in fake_api.calls if c["path"].endswith("getRefData"))["json"]
    assert body["condition"]["commonVOs"][2] == {
        "itemName": "code",
        "value1": "demo-plm",
    }


async def test_whoami_falls_back_to_login_without_name(bound_user, fake_api, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise adapter.McpRuntimeError("integration_unavailable", "PLM 暂不可达")

    monkeypatch.setattr(adapter, "_member_by_code", unavailable)
    async with _context(bound_user) as ctx:
        data = await adapter.whoami(ctx)

    assert data["username"] == "demo-plm"
    assert data["user"] == {"id": "", "code": "demo-plm", "name": ""}


async def test_whoami_reports_unbound(user):
    async with _context(user) as ctx:
        data = await adapter.whoami(ctx)
    assert data["configured"] is False



async def test_list_projects_returns_my_projects(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.list_projects(ctx)

    assert data["items"] == [
        {"id": "proj1", "code": "TIANFU", "name": "天府项目", "principal": "张三"}
    ]
    call = next(c for c in fake_api.calls if c["path"].endswith("getRefData"))
    assert call["params"]["refCode"] == adapter.PROJECT_REF_CODE
    assert json.loads(call["json"]["data"])["owner"] == "1234567890123456789"


async def test_get_create_meta_lists_required_and_options(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.get_create_meta(ctx)

    assert data["remote_options"] is True
    assert data["required"] == [
        "project_id",
        "questionCgrId",
        "raisePerson",
        "quesBelongArea",
        "QuesmoduleSel",
        "projectJD",
        "questionTdArea",
        "questionPriority",
        "quesSever",
        "attribute2",
    ]
    attribute2 = next(f for f in data["fields"] if f["key"] == "attribute2")
    assert attribute2["required"] is True
    assert data["defaults"] == {"genyinfenxi": "NA", "attribute1": "NA"}
    assert {"id": "qt1", "name": "软件缺陷"} in data["options"]["questionCgrId"]
    assert data["projects"][0]["code"] == "TIANFU"


async def test_search_members_maps_items(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.search_members(ctx, keyword="张")

    assert data["items"] == [{"id": "u1", "name": "张三", "code": "1001"}]


async def test_search_questions_builds_condition_and_normalizes(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(
        fake_api,
        existing={
            "id": "q1",
            "code": "WSD202511130001",
            "name": "偶现掉盘",
            "ques_status_name": "处理中",
            "raisePerson": "u1",
            "raisePerson_name": "张三",
            "questionPriority_name": "高",
            "quesSever_name": "严重",
            "modifyTime": 1700000000,
        },
    )
    async with _context(bound_user) as ctx:
        data = await adapter.search_questions(ctx, code="WSD202511130001")

    assert data["total"] == 1
    item = data["items"][0]
    assert item["code"] == "WSD202511130001"
    assert item["status"] == "处理中"
    assert item["raise_person"] == {"id": "u1", "name": "张三"}
    assert item["priority"] == "高"
    assert item["updated_at"] == 1700000000000
    body = next(c for c in fake_api.calls if c["path"] == "/yonbip-mm-plmrd/bill/list")["json"]
    assert body["condition"]["simpleVOs"] == [
        {"field": "code", "op": "eq", "value1": "WSD202511130001"}
    ]


async def test_search_status_uses_question_status_code(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(
        fake_api,
        existing={
            "id": "q1",
            "code": "WSD202511130001",
            "name": "偶现掉盘",
            "ques_status": "13",
            "lctemplate_attribute_id": "state1",
            "lctemplate_attribute_id_name": "草稿",
            "lctemplate_attribute_id_code": "Draft",
            "raisePerson": "u1",
            "raisePerson_name": "张三",
        },
    )
    async with _context(bound_user) as ctx:
        data = await adapter.search_questions(ctx, code="WSD202511130001")

    item = data["items"][0]
    assert item["status"] == "提交审核"
    assert item["status_id"] == "state1"
    assert item["status_code"] == "Draft"



async def test_get_question_returns_description_and_inline_image(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(
        fake_api,
        existing={
            "id": "q1",
            "code": "WSD202511130001",
            "name": "偶现掉盘",
            "qusDescribe": '<p>现象描述</p><img src="https://plm.twsc.com.cn/yms-def-bucket/x/shot.png" alt="shot.png">',
            "raisePerson": "u1",
            "raisePerson_name": "张三",
        },
    )
    async with _context(bound_user) as ctx:
        data = await adapter.get_question(ctx, code="WSD202511130001")

    assert data["code"] == "WSD202511130001"
    assert data["description"]["text"] == "现象描述"
    assert data["attachments"][0]["name"] == "shot.png"
    assert data["url"].startswith(adapter._base_url() + "/mdf-node/meta/voucher/baseQuestion")


async def test_get_question_requires_id_or_code(bound_user):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError):
            await adapter.get_question(ctx)


async def test_list_comments_normalizes(bound_user, fake_api):
    _install_common_routes(fake_api)
    fake_api.routes[
        "/iuap-apcom-file/rest/v1/comment/yonbip-mm-plmrd+YonSuite/q1/comments"
    ] = lambda **_: {
        "recordList": [
            {
                "id": "c1",
                "content": "<p>已复现</p>",
                "creator_userName": "张三",
                "ctime": 1700000000000,
            }
        ]
    }
    async with _context(bound_user) as ctx:
        data = await adapter.list_comments(ctx, id="q1")

    assert data["total"] == 1
    assert data["items"][0]["author"] == "张三"
    assert data["items"][0]["content"] == "已复现"


async def test_list_attachments_reads_file_groups(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(
        fake_api,
        existing={
            "id": "q1",
            "code": "WSD202511130001",
            "name": "带附件",
            "que_files1": GROUP_ID,
        },
    )
    fake_api.routes[
        f"/iuap-apcom-file/rest/v1/file/yonbip-mm-plmrd+mdf/{GROUP_ID}/files"
    ] = lambda **_: {
        "list": [
            {
                "fileKey": "path/a",
                "filename": "a",
                "suffix": "png",
                "filesize": "1.00KB",
            }
        ]
    }
    async with _context(bound_user) as ctx:
        data = await adapter.list_attachments(ctx, id="q1")

    assert data["count"] == 1
    assert data["items"][0]["name"] == "a.png"
    assert data["items"][0]["url"].endswith("/yms-def-bucket/path/a")


async def test_download_attachment_rejects_foreign_host(bound_user):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError):
            await adapter.download_attachment(ctx, url="https://evil.example/f")


async def test_download_attachment_inlines_image(bound_user, fake_api):
    _install_common_routes(fake_api)
    fake_api.routes["__download__"] = lambda url: (b"\x89PNG-data", "image/png", "shot.png")
    async with _context(bound_user) as ctx:
        data = await adapter.download_attachment(
            ctx,
            url=adapter._base_url() + "/yms-def-bucket/x/shot.png",
        )

    assert data["content_type"] == "image/png"
    assert base64.b64decode(data["base64"]) == b"\x89PNG-data"
    assert data["bytes"] == 9


async def test_download_attachment_resolves_file_id_from_infos_list(bound_user, fake_api):
    _install_common_routes(fake_api)
    expected = adapter._base_url() + "/yms-def-bucket/private/a.png"
    fake_api.routes["/iuap-apcom-file/rest/v1/file/infos"] = lambda **_: {
        "list": [{"id": "f1", "filePath": expected, "name": "a.png"}]
    }

    def download(url):
        assert url == expected
        return (b"\x89PNG-data", "image/png", "a.png")

    fake_api.routes["__download__"] = download
    async with _context(bound_user) as ctx:
        data = await adapter.download_attachment(ctx, file_id="f1")

    assert data["content_type"] == "image/png"
    assert base64.b64decode(data["base64"]) == b"\x89PNG-data"
    assert data["bytes"] == 9


async def test_search_test_cases_filters_newest_flag(bound_user, fake_api):
    _install_common_routes(fake_api)

    def list_route(json=None, **_):
        assert json["condition"]["simpleVOs"][0] == {
            "field": "newest_flag",
            "op": "eq",
            "value1": 1,
        }
        return {
            "recordList": [
                {"id": "c1", "code": "HIMA3361-8077", "name": "掉盘后恢复"}
            ],
            "recordCount": 1,
        }

    fake_api.routes["/yonbip-mm-plmrd/bill/list"] = list_route
    async with _context(bound_user) as ctx:
        data = await adapter.search_test_cases(ctx, identifier="HIMA3361-8077")

    assert data["items"] == [
        {
            "id": "c1",
            "identifier": "HIMA3361-8077",
            "title": "掉盘后恢复",
            "catalog": "",
        }
    ]


async def test_get_test_case_returns_steps(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(fake_api)

    def list_route(json=None, **_):
        if (json or {}).get("billnum") == adapter.TEST_CASE_BILL:
            return {
                "recordList": [
                    {"id": "c1", "code": "HIMA3361-8077", "name": "掉盘后恢复"}
                ],
                "recordCount": 1,
            }
        return {"recordList": [], "recordCount": 0}

    fake_api.routes["/yonbip-mm-plmrd/bill/list"] = list_route
    async with _context(bound_user) as ctx:
        data = await adapter.get_test_case(ctx, identifier="HIMA3361-8077")

    assert data["identifier"] == "HIMA3361-8077"
    assert data["title"] == "掉盘后恢复"
    assert data["precondition"] == "设备已连接"
    assert data["steps"][0] == {"step": "1. 插拔", "expected": "1. 识别"}


async def test_get_test_case_not_found(bound_user, fake_api):
    _install_common_routes(fake_api)
    fake_api.routes["/yonbip-mm-plmrd/bill/list"] = lambda **_: {
        "recordList": [],
        "recordCount": 0,
    }
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.get_test_case(ctx, identifier="9999")
    assert excinfo.value.code == "not_found"


# ── 用例目录树与按目录检索 ──────────────────────────────────
def _catalog_tree() -> list[dict]:
    return [
        {
            "id": "root",
            "name": "测试用例库",
            "code": "PF-00000001",
            "parent": "0",
            "path": "root|",
            "level": 1,
            "children": [
                {
                    "id": "hima",
                    "name": "Hima",
                    "code": "HIMA3361",
                    "parent": "root",
                    "path": "root|hima|",
                    "level": 2,
                    "children": [
                        {
                            "id": "sim",
                            "name": "similar_io",
                            "code": "HIMA-1",
                            "parent": "hima",
                            "path": "root|hima|sim|",
                            "level": 3,
                            "children": [
                                {
                                    "id": "trim",
                                    "name": "trim",
                                    "code": "HIMA-2",
                                    "parent": "sim",
                                    "path": "root|hima|sim|trim|",
                                    "level": 4,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "media",
                    "name": "介质筛选项目",
                    "code": "JZ",
                    "parent": "root",
                    "path": "root|media|",
                    "level": 2,
                    "children": [],
                },
                {
                    "id": "dup1",
                    "name": "trim",
                    "code": "D1",
                    "parent": "root",
                    "path": "root|dup1|",
                    "level": 2,
                    "children": [],
                },
                {
                    "id": "dup2",
                    "name": "trim",
                    "code": "D2",
                    "parent": "root",
                    "path": "root|dup2|",
                    "level": 2,
                    "children": [],
                },
            ],
        }
    ]


def _install_catalog_route(api: FakeAPI) -> None:
    api.routes["/yonbip-mm-plmrd/bill/querytree"] = lambda **_: _catalog_tree()


async def test_case_catalog_tree_returns_nested_nodes(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.list_case_catalogs(ctx, max_depth=2)

    assert data["truncated"] is False
    root = data["roots"][0]
    assert root["name"] == "测试用例库"
    assert [node["name"] for node in root["children"]] == [
        "Hima",
        "介质筛选项目",
        "trim",
        "trim",
    ]
    hima = root["children"][0]
    assert hima["has_children"] is True
    assert "children" not in hima
    call = next(
        item
        for item in fake_api.calls
        if item["path"] == "/yonbip-mm-plmrd/bill/querytree"
    )
    assert call["json"]["treename"] == adapter.TEST_CASE_TREE_NAME
    assert call["json"]["billnum"] == adapter.TEST_CASE_BILL
    assert call["params"]["domainKey"] == "IMP-BASE"


async def test_case_catalog_tree_keyword_keeps_ancestors(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.list_case_catalogs(ctx, keyword="similar", max_depth=4)

    root = data["roots"][0]
    hima = root["children"][0]
    similar = hima["children"][0]
    assert similar["name"] == "similar_io"
    assert similar["matched"] is True
    assert "children" not in similar
    assert [node["name"] for node in root["children"]] == ["Hima"]


async def test_case_catalog_tree_rejects_unknown_catalog(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.list_case_catalogs(ctx, catalog_id="missing")

    assert excinfo.value.code == "not_found"
    assert "missing" in excinfo.value.message


async def test_case_catalog_tree_truncates_large_tree(
    bound_user, fake_api, monkeypatch
):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)
    monkeypatch.setattr(adapter, "MAX_TREE_NODES", 2)
    async with _context(bound_user) as ctx:
        data = await adapter.list_case_catalogs(ctx, max_depth=4)

    assert data["truncated"] is True
    assert data["total"] <= 2


async def test_search_test_cases_filters_by_catalog_id(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)

    def list_route(json=None, **_):
        vos = json["condition"]["simpleVOs"]
        assert {"field": "doc_classfiy_id", "op": "in", "value1": ["sim", "trim"]} in vos
        assert "ids" not in json
        assert "path" not in json
        assert json["partParam"]["containChildren"] is False
        return {
            "recordList": [
                {
                    "id": "c1",
                    "code": "HIMA3361-8077",
                    "name": "掉盘后恢复",
                    "doc_classfiy_id_name": "trim",
                }
            ],
            "recordCount": 1,
        }

    fake_api.routes["/yonbip-mm-plmrd/bill/list"] = list_route
    async with _context(bound_user) as ctx:
        data = await adapter.search_test_cases(ctx, catalog_id="sim")

    assert data["items"] == [
        {
            "id": "c1",
            "identifier": "HIMA3361-8077",
            "title": "掉盘后恢复",
            "catalog": "trim",
        }
    ]


async def test_search_test_cases_resolves_catalog_name(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)

    def list_route(json=None, **_):
        vos = json["condition"]["simpleVOs"]
        assert {"field": "doc_classfiy_id", "op": "in", "value1": ["media"]} in vos
        assert "ids" not in json
        return {"recordList": [], "recordCount": 0}

    fake_api.routes["/yonbip-mm-plmrd/bill/list"] = list_route
    async with _context(bound_user) as ctx:
        await adapter.search_test_cases(ctx, catalog_name="介质筛选项目")


async def test_search_test_cases_category_is_catalog_name_alias(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)

    def list_route(json=None, **_):
        vos = json["condition"]["simpleVOs"]
        assert {"field": "doc_classfiy_id", "op": "in", "value1": ["hima", "sim", "trim"]} in vos
        return {"recordList": [], "recordCount": 0}

    fake_api.routes["/yonbip-mm-plmrd/bill/list"] = list_route
    async with _context(bound_user) as ctx:
        await adapter.search_test_cases(ctx, category="Hima")


async def test_search_test_cases_rejects_ambiguous_catalog_name(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.search_test_cases(ctx, catalog_name="trim")

    assert excinfo.value.code == "ambiguous_catalog"
    assert "dup1" in excinfo.value.message
    assert "dup2" in excinfo.value.message
    assert "catalog_id" in excinfo.value.message


async def test_search_test_cases_rejects_unknown_catalog_name(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_catalog_route(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.search_test_cases(ctx, catalog_name="不存在的目录")

    assert excinfo.value.code == "catalog_not_found"
    assert "plm_case_catalog_tree" in excinfo.value.message



# ── 建单预览与严格校验 ──────────────────────────────────────
def _create_args(**overrides):
    args = {
        "name": "联调提单",
        "project_code": "TIANFU",
        "questionCgrId": "qt1",
        "raisePerson": "u1",
        "raisePerson_name": "张三",
        "quesBelongArea": "1",
        "QuesmoduleSel": "2",
        "projectJD": "3",
        "questionTdArea": "3",
        "questionPriority": "1",
        "quesSever": "2",
        "attribute2": "FW1.0",
        "description": "<p>现象</p>",
        "description_template": "custom",
        "confirm": True,
    }
    args.update(overrides)
    return args


async def test_preview_reports_missing_and_unresolved_project(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(
            ctx, **{k: v for k, v in _create_args().items() if k != "attribute2"}
        )

    assert data["ok"] is False
    assert "attribute2" in data["missing_required"]
    assert data["payload"]["project_resolved"] is True

    async with _context(bound_user) as ctx:
        bad = await adapter.preview_question(ctx, **_create_args(project_code="NOPE"))
    assert bad["ok"] is False
    assert bad["payload"]["project_resolved"] is False
    assert bad["hints"]


async def test_preview_reports_all_required_attributes(bound_user, fake_api):
    _install_common_routes(fake_api)
    required = (
        "quesBelongArea", "QuesmoduleSel", "projectJD",
        "questionTdArea", "questionPriority", "quesSever", "attribute2",
    )
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(
            ctx, **{k: v for k, v in _create_args().items() if k not in required}
        )

    assert data["ok"] is False
    assert data["missing_required"] == list(required)


async def test_preview_explains_missing_required_fields(bound_user, fake_api):
    _install_common_routes(fake_api)
    required = (
        "quesBelongArea", "QuesmoduleSel", "projectJD",
        "questionTdArea", "questionPriority", "quesSever", "attribute2",
    )
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(
            ctx, **{k: v for k, v in _create_args().items() if k not in required}
        )

    assert data["ok"] is False
    details = {item["key"]: item for item in data["missing_fields"]}
    assert set(details) == set(required)
    assert details["projectJD"]["name"] == "项目阶段"
    assert {"id": "3", "name": "TR3"} in details["projectJD"]["options"]
    assert details["attribute2"]["name"] == "固件版本"
    assert details["attribute2"]["type"] == "text"
    assert "缺少必填" in data["error"]
    for name in ("问题归属领域", "问题模块", "项目阶段", "提单领域", "优先级", "严重程度", "固件版本"):
        assert name in data["error"]


async def test_preview_explains_invalid_option_with_allowed_ids(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(ctx, **_create_args(projectJD="TR3", quesSever="9"))

    assert data["ok"] is False
    invalid = {item["key"]: item for item in data["invalid_fields"]}
    assert invalid["projectJD"]["value"] == "TR3"
    assert {"id": "3", "name": "TR3"} in invalid["projectJD"]["options"]
    assert invalid["quesSever"]["name"] == "严重程度"
    assert "选项非法" in data["error"]
    assert "1=致命" in data["error"]


async def test_preview_accepts_project_code_without_project_id(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(ctx, **_create_args())

    assert data["ok"] is True
    assert "project_id" not in data["missing_required"]
    assert data["payload"]["project_resolved"] is True


def _standard_fields() -> dict[str, str]:
    return {
        "featureModule": "掉电测试",
        "preconditions": "设备已连接",
        "steps": "1. 上电\n2. 掉电",
        "expectedResult": "系统正常",
        "failurePhenomenon": "FBB 返回异常",
        "hostIp": "10.20.24.30",
        "caseId": "HIMA3361-8077",
    }


def _standard_args(**overrides):
    args = _create_args(description=None, description_fields=_standard_fields())
    args.pop("description_template", None)
    args.update(overrides)
    return args


async def test_preview_defaults_to_standard_description_template(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(ctx, **_standard_args())

    assert data["ok"] is True
    payload = data["payload"]
    assert payload["description_template"] == "standard"
    html = payload["values"]["description"]
    assert "1. 问题描述" in html
    assert "10. 测试日志" in html
    assert "掉电测试" in html
    assert "FBB 返回异常" in html
    assert "HIMA3361-8077" in html


async def test_preview_standard_template_uses_plm_grid_and_fonts(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(ctx, **_standard_args())

    html = data["payload"]["values"]["description"]
    assert "<colgroup>" + "<col>" * 10 + "</colgroup>" in html
    assert 'colspan="2" width="150"' in html
    assert 'colspan="8" style="background-color:#ffffff' in html
    assert 'colspan="10" style="background-color:#e5e7eb' in html
    assert "font-size:12px;line-height:1.65;" in html
    assert "font-size:11px" not in html


async def test_preview_standard_template_renders_missing_fields_as_dash(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(ctx, **_standard_args(description_fields={}))

    html = data["payload"]["values"]["description"]
    assert "10. 测试日志" in html
    assert "用例执行成功" in html
    assert "> -</td>" in html or ">-</td>" in html


async def test_preview_custom_template_keeps_raw_description(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        data = await adapter.preview_question(ctx, **_create_args())

    assert data["payload"]["description_template"] == "custom"
    assert data["payload"]["values"]["description"] == "<p>现象</p>"


async def test_preview_rejects_unknown_description_template(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.preview_question(
                ctx, **_create_args(description_template="pretty")
            )

    assert excinfo.value.code == "invalid_arguments"
    assert "standard" in str(excinfo.value)
    assert "custom" in str(excinfo.value)


async def test_create_requires_confirm(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_question(ctx, **_create_args(confirm=False))
    assert excinfo.value.code == "confirmation_required"
    assert fake_api.calls == []


async def test_create_rejects_unresolved_project(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_question(ctx, **_create_args(project_code="NOPE"))

    assert excinfo.value.code == "invalid_arguments"
    assert "必须关联项目" in str(excinfo.value)
    assert "plm_common_list_projects" in str(excinfo.value)
    assert "/yonbip-mm-plmrd/bill/save" not in fake_api.paths()


async def test_create_rejects_missing_required_attribute(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_question(
                ctx, **{k: v for k, v in _create_args().items() if k != "attribute2"}
            )

    message = str(excinfo.value)
    assert excinfo.value.code == "invalid_arguments"
    assert "attribute2" in message
    assert "固件版本" in message
    assert "/yonbip-mm-plmrd/questionCgr/getCode" not in fake_api.paths()


async def test_create_rejects_invalid_option(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_question(ctx, **_create_args(quesSever="9"))

    message = str(excinfo.value)
    assert excinfo.value.code == "invalid_arguments"
    assert "严重程度" in message
    assert "1=致命" in message
    assert "/yonbip-mm-plmrd/questionCgr/getCode" not in fake_api.paths()


async def test_create_rejects_when_plm_returns_no_code(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(fake_api)
    _install_create_routes(fake_api, code="BAD")

    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_question(ctx, **_create_args())

    assert excinfo.value.code == "plm_error"
    assert "未生成合规问题单号" in str(excinfo.value)
    assert "questionCgrId" in str(excinfo.value)
    assert "/yonbip-mm-plmrd/bill/save" not in fake_api.paths()



def _install_create_routes(api: FakeAPI, *, code: str = "WSD202511130001") -> None:
    api.routes["/yonbip-mm-plmrd/questionCgr/allowCreateQuestion"] = lambda **_: {"code": "0"}
    api.routes["/yonbip-mm-plmrd/questionCgr/getLcDetail"] = lambda **_: {
        "data": {
            "schId": "sch1",
            "lctId": "lct1",
            "lctId_name": "问题流程",
            "begin_state_id": "state1",
            "begin_state_id_name": "草稿",
        }
    }
    api.routes["/yonbip-mm-plmrd/questionCgr/getCode"] = lambda **_: {
        "code": code,
        "id": "q9",
        "scope": "org-1",
    }
    api.routes["/yonbip-mm-plmrd/bill/add"] = lambda **_: {"attachmentId": "slot-1"}

    def save_route(json=None, **_):
        fields = jsonlib.loads(json["data"])
        api.saved_fields = fields
        api.records.append(fields)
        return {"code": "0"}

    api.routes["/yonbip-mm-plmrd/bill/save"] = save_route


async def test_create_happy_path_verifies_code_and_handler(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(fake_api)
    _install_create_routes(fake_api)
    async with _context(bound_user) as ctx:
        result = await adapter.create_question(ctx, **_create_args(client_request_id="req-1"))

    assert result["ok"] is True
    assert result["code"] == "WSD202511130001"
    assert result["verified"] is True
    assert result["project"] == {"id": "proj1", "code": "TIANFU", "name": "天府项目"}
    assert result["raise_person"] == "u1"

    fields = fake_api.saved_fields
    assert fields["code"] == "WSD202511130001"
    assert fields["associationObjectList"][0]["code"] == "TIANFU"
    assert fields["associatedObjectCode"] == "TIANFU"
    assert fields["questionCgrId"] == "qt1"
    assert fields["questionCgrId_name"] == "软件缺陷"
    assert fields["raisePerson"] == "u1"
    assert fields["projectJD"] == "3"
    assert fields["attribute2"] == "FW1.0"
    assert fields["qusDescribe"] == "<p>现象</p>"


async def test_create_defaults_to_standard_description_template(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(fake_api)
    _install_create_routes(fake_api)
    async with _context(bound_user) as ctx:
        await adapter.create_question(
            ctx, **_standard_args(client_request_id="req-std")
        )

    html = fake_api.saved_fields["qusDescribe"]
    assert "1. 问题描述" in html
    assert "10. 测试日志" in html
    assert "掉电测试" in html
    assert "关键操作步骤" in html
    assert "1. 上电<br>2. 掉电" in html
    assert 'colspan="8" style="background-color:#ffffff' in html
    assert "font-size:12px;line-height:1.65;" in html


async def test_create_reports_server_assigned_id(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(fake_api)
    _install_create_routes(fake_api)

    def save_route(json=None, **_):
        fields = jsonlib.loads(json["data"])
        fields["id"] = "q-saved"
        fake_api.saved_fields = fields
        fake_api.records.append(fields)
        return {"code": "0"}

    fake_api.routes["/yonbip-mm-plmrd/bill/save"] = save_route
    async with _context(bound_user) as ctx:
        result = await adapter.create_question(ctx, **_create_args(client_request_id="req-id"))

    assert result["id"] == "q-saved"
    assert "id=q-saved" in result["url"]


async def test_create_aborts_on_duplicate_code(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(
        fake_api,
        existing={
            "id": "q9",
            "code": "WSD202511130001",
            "name": "已存在",
            "raisePerson": "u1",
        },
    )
    _install_create_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_question(ctx, **_create_args(client_request_id="req-dup"))

    assert excinfo.value.code == "plm_duplicate_code"
    assert "/yonbip-mm-plmrd/bill/save" not in fake_api.paths()


async def test_create_fails_when_verify_misses(bound_user, fake_api):
    _install_common_routes(fake_api)
    fake_api.routes["/yonbip-mm-plmrd/bill/list"] = lambda **_: {
        "recordList": [],
        "recordCount": 0,
    }
    _install_create_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_question(ctx, **_create_args(client_request_id="req-miss"))

    assert excinfo.value.code == "plm_verify_failed"


async def test_create_is_idempotent(bound_user, fake_api):
    _install_common_routes(fake_api)
    _install_question_routes(fake_api)
    _install_create_routes(fake_api)
    async with _context(bound_user) as ctx:
        first = await adapter.create_question(ctx, **_create_args(client_request_id="req-once"))
        second = await adapter.create_question(ctx, **_create_args(client_request_id="req-once"))

    assert first == second
    assert fake_api.paths().count("/yonbip-mm-plmrd/bill/save") == 1


def _des_ciphertext(key_iv: str, payload: dict) -> str:
    dash = key_iv.rfind("-")
    key = key_iv[:dash].encode()[:8]
    iv = key_iv[dash + 1 :].encode()[:8]
    padder = padding.PKCS7(64).padder()
    data = padder.update(json.dumps(payload).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.TripleDES(key * 3), modes.CBC(iv)).encryptor()
    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode()


async def test_create_uploads_attachments_with_shared_business_id(
    bound_user, fake_api
):
    _install_common_routes(fake_api)
    _install_question_routes(fake_api)
    _install_create_routes(fake_api)
    key_iv = "12345678-abcdefgh"
    fake_api.routes["/iuap-apcom-file/rest/v1/jssdk/version"] = lambda **_: {
        "KeyIvParameter": key_iv
    }
    fake_api.routes[
        "/iuap-apcom-file/rest/v2/file/createFileUploadTask"
    ] = lambda **_: {
        "cacheId": "cache-1",
        "ciphertext": _des_ciphertext(key_iv, {"url": "https://oss.example/put/1", "method": "PUT"}),
        "state": 2,
    }
    fake_api.routes[
        "/iuap-apcom-file/rest/v2/file/saveFileUploadBusiness"
    ] = lambda **_: {
        "data": [{"id": "file-1", "fileName": "shot.png", "fileSize": 8, "sign": "s" * 30}]
    }

    payload = base64.b64encode(b"\x89PNGdata").decode("ascii")
    async with _context(bound_user) as ctx:
        result = await adapter.create_question(
            ctx,
            **_create_args(
                client_request_id="req-att",
                attachments=[{"name": "shot.png", "content_base64": payload}],
            ),
        )

    assert result["attachments"] == 1
    assert fake_api.uploads[0]["url"] == "https://oss.example/put/1"
    assert fake_api.saved_fields["attachmentId"] == "slot-1"
    assert fake_api.saved_fields["que_files1"].startswith("mdf_")
    assert "/yonbip-mm-plmrd/bill/add" in fake_api.paths()


# ── 评论 ────────────────────────────────────────────────────
async def test_add_comment_requires_confirm(bound_user, fake_api):
    _install_common_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.add_comment(ctx, id="q1", content="hi", confirm=False)
    assert excinfo.value.code == "confirmation_required"
    assert fake_api.calls == []


async def test_add_comment_success(bound_user, fake_api):
    _install_common_routes(fake_api)
    path = "/iuap-apcom-file/rest/v1/comment/yonbip-mm-plmrd+YonSuite/q1/add"
    fake_api.routes[path] = lambda **_: {"code": "0", "id": "c2"}
    async with _context(bound_user) as ctx:
        data = await adapter.add_comment(ctx, id="q1", content="已确认", confirm=True)

    assert data == {"ok": True, "id": "c2", "question_id": "q1"}
    call = next(c for c in fake_api.calls if c["path"] == path)
    assert call["json"]["content"] == "已确认"


async def test_unbound_credential_maps_to_error(user, fake_api, monkeypatch):
    async def missing(user_id, *, force=False):
        raise session_manager.IntegrationNotConfigured("尚未配置 PLM 账号")

    monkeypatch.setattr(session_manager, "ensure_session", missing)
    async with _context(user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.list_projects(ctx)
    assert excinfo.value.code == "integration_not_configured"
