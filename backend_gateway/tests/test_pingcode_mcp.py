"""pingcode MCP 域: 18 个工具 schema、scope、幂等与适配输出 (mock 上游)."""
from __future__ import annotations

import base64
import json
import uuid
from contextlib import asynccontextmanager

import pytest
import httpx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.db.session import AsyncSessionLocal
from app.integrations import crypto
from app.integrations.pingcode import client as pingcode_client
from app.integrations.pingcode import token_manager
from app.mcp.common.context import McpContext, Principal
from app.mcp.common.errors import McpRuntimeError
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.pingcode import adapter, templates
from app.mcp.pingcode.server import build_pingcode_server
from app.models.integration import IntegrationCredential
from app.models.user import User, UserRole
from tests._mcp_protocol import call_tool, call_tool_data, list_tools

PUBLIC_BASE = "http://test"
ENDPOINT = "/mcp/pingcode"
READ_TOKEN = "pingcode-read-token"

TOOL_REQUIRED = {
    "pingcode_whoami": set(),
    "pingcode_list_projects": set(),
    "pingcode_list_work_item_types": {"project_id"},
    "pingcode_get_property_schema": {"project_id", "work_item_type_id"},
    "pingcode_list_members": {"project_id"},
    "pingcode_search_work_items": set(),
    "pingcode_get_work_item": set(),
    "pingcode_list_comments": {"id"},
    "pingcode_list_attachments": {"id"},
    "pingcode_list_test_case_libraries": set(),
    "pingcode_search_test_cases": {"library_id"},
    "pingcode_get_test_case": {"library_id", "identifier"},
    "pingcode_get_test_case_properties": {"library_id"},
    "pingcode_download_attachment": set(),
    "pingcode_preview_work_item": {"project_id", "work_item_type_id", "properties"},
    "pingcode_create_work_item": {
        "project_id",
        "work_item_type_id",
        "properties",
        "confirm",
        "client_request_id",
    },
    "pingcode_add_comment": {"id", "content", "confirm"},
    "pingcode_upload_attachment": {"confirm"},
}


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
        if token != READ_TOKEN:
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
            username=f"pc-mcp-{uuid.uuid4().hex[:8]}",
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
                provider="pingcode",
                username="demo-user",
                secret_encrypted=crypto.encrypt_secret(
                    "secret-pass", user_id=user.id, provider="pingcode"
                ),
                token_encrypted=crypto.encrypt_secret(
                    "jwt-token", user_id=user.id, provider="pingcode"
                ),
                cookies_encrypted=crypto.encrypt_secret(
                    "{}", user_id=user.id, provider="pingcode"
                ),
                status="ok",
                token_expires_at=None,
            )
        )
        await session.commit()
    user.username = "demo-user"
    return user


class FakeAPI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.routes = {}
        self.uploads: list[dict] = []
        self.upload_result: dict = {"_id": "file-1"}
        self.upload_error: Exception | None = None

    async def upload(self, user_id, path, *, token, scope, filename, content, content_type):
        self.uploads.append(
            {
                "user_id": user_id,
                "path": path,
                "token": token,
                "scope": scope,
                "filename": filename,
                "content": content,
                "content_type": content_type,
            }
        )
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_result

    async def request(self, user_id, method, path, *, params=None, json=None):
        self.calls.append((method, path, params, json))
        handler = self.routes.get(path)
        if handler is None:
            raise AssertionError(f"unexpected request {method} {path}")
        return handler(params=params, json=json)

    def paths(self) -> list[str]:
        return [path for _, path, _, _ in self.calls]


@pytest.fixture
def fake_api(monkeypatch):
    api = FakeAPI()
    redis = _FakeRedis()

    @asynccontextmanager
    async def redis_factory():
        yield redis

    async def forward(user_id, method, path, *, params=None, json=None):
        return await api.request(user_id, method, path, params=params, json=json)

    monkeypatch.setattr(token_manager, "request", forward)
    monkeypatch.setattr(token_manager, "upload_file", api.upload)
    monkeypatch.setattr(adapter, "redis_client", redis_factory)
    api.redis = redis
    return api


@asynccontextmanager
async def _context(user: User, scopes=("pingcode:read", "pingcode:write")):
    async with AsyncSessionLocal() as session:
        principal = Principal(
            user=user, client_id="test-client", scopes=frozenset(scopes)
        )
        yield McpContext(principal=principal, session=session)


@asynccontextmanager
async def _server(principal: Principal):
    server = build_pingcode_server(
        public_base_url=PUBLIC_BASE,
        allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    server._token_verifier = _Verifier(principal)
    dispatcher = build_dispatcher({"pingcode": server})
    app = FastAPI()
    app.mount("/mcp", dispatcher)
    async with (
        run_mcp_lifespan(dispatcher),
        AsyncClient(transport=ASGITransport(app=app), base_url=PUBLIC_BASE) as client,
    ):
        yield client


def _reference_payload() -> dict:
    return {
        "states": [{"_id": "s1", "name": "新建"}],
        "work_item_types": [{"_id": "t1", "name": "缺陷"}],
        "members": [{"uid": "u1", "display_name": "张三"}],
        "properties": [
            {
                "key": "priority",
                "name": "优先级",
                "options": [{"_id": "p1", "text": "高"}],
            }
        ],
        "attachments": [
            {
                "attachment_id": "a1",
                "file_id": "f2",
                "title": "日志.txt",
                "size": 12,
                "token": "tok",
                "addition": {"ext": "txt", "mime_type": "text/plain"},
            }
        ],
        "projects": [{"_id": "p1", "identifier": "TF2", "name": "TIANFU"}],
    }


def _detail_payload() -> dict:
    return {
        "value": {
            "_id": "w1",
            "whole_identifier": "TF2-60",
            "title": "偶现掉盘",
            "description": '<p>现象</p><img src="http://10.20.24.30/atlas/files/public/f9">',
            "project_id": "p1",
            "type_id": "t1",
            "state_id": "s1",
            "assignee": "u1",
            "priority": "p1",
            "property_values": [{"key": "priority", "value": "p1"}],
            "attachments": [
                {"attachment_id": "a1", "versions": [{"file_id": "f2"}]}
            ],
            "comment_count": 2,
            "updated_at": 1700000000,
        },
        "references": _reference_payload(),
    }


# ── 契约: 13 个工具与严格 schema ────────────────────────────
async def test_tools_list_exposes_eighteen_strict_schemas(user):
    principal = Principal(
        user=user, client_id="test-client", scopes=frozenset({"pingcode:read"})
    )
    async with _server(principal) as client:
        payload = await list_tools(client, READ_TOKEN, endpoint=ENDPOINT)

    tools = {tool["name"]: tool for tool in payload["tools"]}
    assert set(tools) == set(TOOL_REQUIRED)
    for name, required in TOOL_REQUIRED.items():
        schema = tools[name]["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, name
        assert set(schema.get("required", [])) == required, name


async def test_write_tool_requires_scope(user):
    principal = Principal(
        user=user, client_id="test-client", scopes=frozenset({"pingcode:read"})
    )
    async with _server(principal) as client:
        result = await call_tool(
            client,
            READ_TOKEN,
            "pingcode_create_work_item",
            {
                "project_id": "p1",
                "work_item_type_id": "t1",
                "properties": {"title": "x"},
                "confirm": True,
                "client_request_id": "req-1",
            },
            endpoint=ENDPOINT,
        )

    assert result.get("isError") is True
    assert "scope" in result["content"][0]["text"].lower()


async def test_unknown_argument_is_rejected(user):
    principal = Principal(
        user=user, client_id="test-client", scopes=frozenset({"pingcode:read"})
    )
    async with _server(principal) as client:
        result = await call_tool(
            client,
            READ_TOKEN,
            "pingcode_whoami",
            {"unexpected": True},
            endpoint=ENDPOINT,
        )
    assert result.get("isError") is True


# ── 适配输出 ───────────────────────────────────────────────
async def test_whoami_reports_bound_account(bound_user):
    async with _context(bound_user) as ctx:
        data = await adapter.whoami(ctx)

    assert data["configured"] is True
    assert data["username"] == "demo-user"
    assert data["status"] == "ok"


async def test_whoami_reports_unbound(user):
    async with _context(user) as ctx:
        data = await adapter.whoami(ctx)
    assert data["configured"] is False


async def test_list_projects_normalizes(bound_user, fake_api):
    fake_api.routes["/api/agile/projects/select-options"] = lambda **_: {
        "value": [
            {
                "_id": "p1",
                "identifier": "TF2",
                "name": "TIANFU",
                "template_type": "waterfall",
                "is_local_configure": 0,
                "members": [{"uid": "u1"}],
            }
        ]
    }
    async with _context(bound_user) as ctx:
        data = await adapter.list_projects(ctx)

    assert data["items"] == [
        {
            "id": "p1",
            "identifier": "TF2",
            "name": "TIANFU",
            "template_type": "waterfall",
            "is_local_configure": False,
        }
    ]
    assert fake_api.calls[0][2] == {"can_create_work_item": 1}


async def test_list_work_item_types_normalizes(bound_user, fake_api):
    fake_api.routes["/api/agile/projects/p1/work-item-types"] = lambda **_: {
        "value": [
            {
                "_id": "t1",
                "type_id": "t1",
                "name": "缺陷",
                "required_property_bindings": [
                    {"key": "title"},
                    {"property_key": "assignee"},
                ],
            }
        ]
    }
    async with _context(bound_user) as ctx:
        data = await adapter.list_work_item_types(ctx, project_id="p1")

    assert data["items"][0]["required_keys"] == ["title", "assignee"]


async def test_property_schema_falls_back_to_global_on_404(bound_user, fake_api):
    calls = {"count": 0}

    def schema(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise adapter.client.PingCodeBusinessError(
                "not found property definition by id or scope", status=404, code=404
            )
        return {
            "value": {
                "properties": [
                    {
                        "key": "title",
                        "name": "标题",
                        "type": 1,
                        "validators": {"is_required": True},
                        "options": [],
                    }
                ]
            }
        }

    fake_api.routes["/api/agile/work-item/creation-template/properties"] = schema
    async with _context(bound_user) as ctx:
        data = await adapter.get_property_schema(
            ctx, project_id="p1", work_item_type_id="t1"
        )

    assert data["used_global_fallback"] is True
    assert data["fields"][0]["required"] is True
    assert "project_id" not in (fake_api.calls[1][2] or {})


async def test_search_resolves_identifier_and_names(bound_user, fake_api):
    fake_api.routes["/api/agile/projects/select-options"] = lambda **_: {
        "value": [{"_id": "p1", "identifier": "TF2", "name": "TIANFU"}]
    }
    fake_api.routes["/api/agile/work-items"] = lambda **_: {
        "value": [
            {
                "_id": "w1",
                "whole_identifier": "TF2-60",
                "title": "偶现掉盘",
                "state_id": "s1",
                "type_id": "t1",
                "assignee": "u1",
                "priority": "p1",
                "updated_at": 1700000000,
            }
        ],
        "count": 1,
        "references": _reference_payload(),
    }
    async with _context(bound_user) as ctx:
        data = await adapter.search_work_items(
            ctx, project_identifier="TF2", keyword="掉盘"
        )

    assert data["total"] == 1
    item = data["items"][0]
    assert item["identifier"] == "TF2-60"
    assert item["state"] == "新建"
    assert item["type"] == "缺陷"
    assert item["assignee"] == "张三"
    assert item["priority"] == "高"
    assert fake_api.calls[-1][2]["project_id"] == "p1"
    assert fake_api.calls[-1][2]["keywords"] == "掉盘"


async def test_search_rejects_unknown_project(bound_user, fake_api):
    fake_api.routes["/api/agile/projects/select-options"] = lambda **_: {"value": []}
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError):
            await adapter.search_work_items(ctx, project_identifier="NOPE")


async def test_get_work_item_by_identifier(bound_user, fake_api):
    fake_api.routes["/api/agile/work-items/dashboard/search"] = lambda **_: {
        "value": [{"_id": "w1", "whole_identifier": "TF2-60", "project_id": "p1"}]
    }
    fake_api.routes["/api/agile/work-items/w1"] = lambda **_: _detail_payload()
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: {
        "value": {
            "properties": [
                {
                    "key": "priority",
                    "name": "优先级",
                    "type": 6,
                    "options": [{"_id": "p1", "text": "高"}],
                }
            ]
        }
    }
    async with _context(bound_user) as ctx:
        data = await adapter.get_work_item(ctx, identifier="TF2-60")

    assert data["id"] == "w1"
    assert data["identifier"] == "TF2-60"
    assert data["state"]["name"] == "新建"
    assert data["type"]["name"] == "缺陷"
    assert data["assignee"]["name"] == "张三"
    assert data["priority"]["name"] == "高"
    assert data["description"]["text"] == "现象"
    assert data["images"][0]["file_id"] == "f9"
    assert data["attachments"][0]["file_id"] == "f2"
    assert data["url"].endswith("/pjm/workitems/w1?#TF2-60")


async def test_get_work_item_requires_id_or_identifier(bound_user):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError):
            await adapter.get_work_item(ctx)


async def test_list_comments_maps_authors(bound_user, fake_api):
    fake_api.routes["/api/agile/work-items/w1/comments"] = lambda **_: {
        "value": [
            {"_id": "c1", "content": "<p>已复现</p>", "created_by": "u1"}
        ],
        "count": 1,
        "references": {"users": [{"uid": "u1", "display_name": "张三"}]},
    }
    async with _context(bound_user) as ctx:
        data = await adapter.list_comments(ctx, id="w1")

    assert data["total"] == 1
    assert data["items"][0]["author"]["name"] == "张三"
    assert data["items"][0]["content_text"] == "已复现"


async def test_list_attachments_uses_detail_references(bound_user, fake_api):
    fake_api.routes["/api/agile/work-items/w1"] = lambda **_: _detail_payload()
    async with _context(bound_user) as ctx:
        data = await adapter.list_attachments(ctx, id="w1")

    assert data["items"][0]["file_id"] == "f2"
    assert data["items"][0]["name"] == "日志.txt"


async def test_download_attachment_rejects_foreign_host(bound_user):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError):
            await adapter.download_attachment(ctx, url="https://evil.example/f")


async def test_download_attachment_returns_inline_image(bound_user, monkeypatch):
    async def fake_download(url, token, max_bytes):
        return "image/png", b"\x89PNG-data"

    monkeypatch.setattr(adapter, "_download_bytes", fake_download)
    async with _context(bound_user) as ctx:
        data = await adapter.download_attachment(
            ctx, url="http://10.20.24.30/atlas/files/public/f9?token=t", name="shot.png"
        )

    assert data["content_type"] == "image/png"
    assert base64.b64decode(data["base64"]) == b"\x89PNG-data"
    assert data["bytes"] == 9


async def test_download_attachment_returns_link_for_non_image(bound_user, monkeypatch):
    async def fake_download(url, token, max_bytes):
        return "application/pdf", b"%PDF-1.4"

    monkeypatch.setattr(adapter, "_download_bytes", fake_download)
    async with _context(bound_user) as ctx:
        data = await adapter.download_attachment(
            ctx, url="http://10.20.24.30/atlas/file/download-url?token=t", name="a.pdf"
        )

    assert data["url"].startswith("http://10.20.24.30/")
    assert data["token"] == "t"
    assert data["bytes"] == 8
    assert "base64" not in data


async def test_download_bytes_never_forwards_authorization_header():
    """S3 预签名地址收到 Authorization 头会返回 InvalidRequest(400)。"""
    seen: dict[str, object] = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"log")

    url = "http://10.20.24.30/atlas/file/download-url?action=download&token=tok"
    content_type, data = await adapter._download_bytes(
        url, "tok", 1024, transport=httpx.MockTransport(handler)
    )

    assert content_type == "text/plain"
    assert data == b"log"
    assert "authorization" not in seen["headers"]
    assert "token=tok" in str(seen["url"])


async def test_download_bytes_appends_token_for_public_file():
    seen: dict[str, str] = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")

    await adapter._download_bytes(
        "http://10.20.24.30/atlas/files/public/f9",
        "pub",
        1024,
        transport=httpx.MockTransport(handler),
    )

    assert "token=pub" in seen["url"]


async def test_download_bytes_rejects_json_error_payload():
    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps({"code": 400401, "message": "missing token from request"}),
        )

    with pytest.raises(adapter.McpRuntimeError) as excinfo:
        await adapter._download_bytes(
            "http://10.20.24.30/atlas/files/public/f9",
            "",
            1024,
            transport=httpx.MockTransport(handler),
        )

    assert excinfo.value.code == "download_failed"
    assert "missing token" in str(excinfo.value)


async def test_public_file_token_reads_value_beside_references(bound_user, monkeypatch):
    async def fake_raw(ctx, method, path, **kwargs):
        return {"value": "public-token", "references": {}}

    monkeypatch.setattr(adapter, "_raw", fake_raw)
    async with _context(bound_user) as ctx:
        assert await adapter._public_file_token(ctx) == "public-token"


async def test_preview_reports_missing_required(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: {
        "value": {
            "properties": [
                {"key": "title", "name": "标题", "type": 1,
                 "validators": {"is_required": True}, "options": []},
                {"key": "assignee", "name": "负责人", "type": 9,
                 "validators": {"is_required": True}, "options": []},
                {"key": "project_id", "name": "项目", "type": 1,
                 "validators": {"is_required": True}, "options": []},
            ]
        }
    }
    async with _context(bound_user) as ctx:
        data = await adapter.preview_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "标题"},
            description_template="standard",
            description_fields={"caseId": "CASE-1", "steps": "步骤一"},
        )

    assert data["ok"] is False
    assert set(data["missing_required"]) == {"assignee"}
    assert "测试用例" in data["payload"]["properties"]["description"]
    assert "步骤一" in data["payload"]["properties"]["description"]


async def test_create_requires_confirm(bound_user, fake_api):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_work_item(
                ctx,
                project_id="p1",
                work_item_type_id="t1",
                properties={"title": "x"},
                confirm=False,
                client_request_id="req-x",
            )
    assert excinfo.value.code == "confirmation_required"
    assert fake_api.calls == []


async def test_create_requires_assignee(bound_user, fake_api):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_work_item(
                ctx,
                project_id="p1",
                work_item_type_id="t1",
                properties={"title": "x", "assignee": ""},
                confirm=True,
                client_request_id="req-no-assignee",
            )
    assert excinfo.value.code == "assignee_required"
    assert fake_api.calls == []


async def test_create_accepts_assignee_member_object(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _typed_schema()
    fake_api.routes["/api/agile/work-item"] = lambda **_: {
        "value": {"_id": "w11", "whole_identifier": "TF2-101"}
    }
    async with _context(bound_user) as ctx:
        await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "有负责人", "assignee": {"uid": "u1", "name": "张三"}},
            confirm=True,
            client_request_id="req-assignee-object",
        )

    body = next(
        json for _, path, _, json in fake_api.calls if path == "/api/agile/work-item"
    )
    values = {item["key"]: item["value"] for item in body["property_values"]}
    assert values["assignee"] == "u1"
    assert values["participants"] == ["u1"]


def _typed_schema() -> dict:
    return {
        "value": {
            "properties": [
                {"key": "title", "type": 1, "validators": {"is_required": True}},
                {"key": "start", "type": 4, "validators": {}},
                {"key": "ceshitexing", "type": 20, "validators": {}},
                {"key": "kaifamokuai", "type": 20, "validators": {}},
            ]
        },
        "references": {},
    }


def _create_schema(*properties: dict) -> dict:
    return {"value": {"properties": list(properties)}, "references": {}}


REQUIRED = {"validators": {"is_required": True}}


async def test_create_rejects_missing_visible_required(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _create_schema(
        {"key": "title", "name": "标题", "type": 1, **REQUIRED},
        {"key": "assignee", "name": "负责人", "type": 9, **REQUIRED},
        {
            "key": "severity",
            "name": "严重程度",
            "type": 6,
            **REQUIRED,
            "options": [{"_id": "sev-1", "text": "严重"}],
        },
    )
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_work_item(
                ctx,
                project_id="p1",
                work_item_type_id="t1",
                properties={"title": "缺必填", "assignee": "u1"},
                confirm=True,
                client_request_id="req-missing-visible",
            )

    assert excinfo.value.code == "invalid_arguments"
    assert "严重程度" in str(excinfo.value)
    assert "/api/agile/work-item" not in fake_api.paths()


async def test_create_fills_hidden_required_defaults(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _create_schema(
        {"key": "title", "name": "标题", "type": 1, **REQUIRED},
        {"key": "assignee", "name": "负责人", "type": 9, **REQUIRED},
        {"key": "start", "name": "开始时间", "type": 4, **REQUIRED},
        {
            "key": "shifouyonglifaxian",
            "name": "是否用例发现",
            "type": 6,
            **REQUIRED,
            "options": [
                {"_id": "opt-case", "text": "用例发现"},
                {"_id": "opt-manual", "text": "非用例发现"},
            ],
        },
        {"key": "replay_step", "name": "重现步骤", "type": 2, **REQUIRED},
    )
    fake_api.routes["/api/agile/work-item"] = lambda **_: {
        "value": {"_id": "w12", "whole_identifier": "TF2-102"}
    }
    async with _context(bound_user) as ctx:
        await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "补隐藏必填", "assignee": "u1"},
            confirm=True,
            client_request_id="req-hidden-defaults",
        )

    body = next(
        json for _, path, _, json in fake_api.calls if path == "/api/agile/work-item"
    )
    values = {item["key"]: item["value"] for item in body["property_values"]}
    assert isinstance(values["start"], int)
    assert values["shifouyonglifaxian"] == "opt-case"
    assert values["replay_step"] == "<p>见描述详情</p>"
    assert values["participants"] == ["u1"]


async def test_create_rejects_invalid_option(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _create_schema(
        {"key": "title", "name": "标题", "type": 1, **REQUIRED},
        {"key": "assignee", "name": "负责人", "type": 9, **REQUIRED},
        {
            "key": "priority",
            "name": "优先级",
            "type": 6,
            **REQUIRED,
            "options": [{"_id": "prio-1", "text": "普通"}],
        },
    )
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.create_work_item(
                ctx,
                project_id="p1",
                work_item_type_id="t1",
                properties={"title": "非法选项", "assignee": "u1", "priority": "not-exist"},
                confirm=True,
                client_request_id="req-invalid-option",
            )

    assert excinfo.value.code == "invalid_arguments"
    assert "优先级" in str(excinfo.value)
    assert "/api/agile/work-item" not in fake_api.paths()



async def test_create_sends_multiselect_as_array_and_date_as_object(bound_user, fake_api):
    """PingCode 校验多选必须数组、日期必须 {date, with_time} —— 标量入参会报 invalidate input data value."""
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _typed_schema()
    fake_api.routes["/api/agile/work-item"] = lambda **_: {
        "value": {"_id": "w10", "whole_identifier": "TF2-100"}
    }
    async with _context(bound_user) as ctx:
        await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={
                "title": "多选编码",
                "start": 1794500653,
                "assignee": "u1",
                "ceshitexing": "opt-c",
                "kaifamokuai": ["opt-k1", "opt-k2"],
            },
            confirm=True,
            client_request_id="req-coerce",
        )

    body = next(
        json for _, path, _, json in fake_api.calls if path == "/api/agile/work-item"
    )
    values = {item["key"]: item["value"] for item in body["property_values"]}
    assert values["ceshitexing"] == ["opt-c"]
    assert values["kaifamokuai"] == ["opt-k1", "opt-k2"]
    assert values["start"] == {"date": 1794500653, "with_time": 0}


async def test_preview_reports_coerced_property_values(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _typed_schema()
    async with _context(bound_user) as ctx:
        data = await adapter.preview_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={
                "title": "x",
                "start": 1794500653,
                "ceshitexing": "opt-c",
                "kaifamokuai": "opt-k",
            },
        )

    props = data["payload"]["properties"]
    assert props["ceshitexing"] == ["opt-c"]
    assert props["kaifamokuai"] == ["opt-k"]
    assert props["start"] == {"date": 1794500653, "with_time": 0}
    assert props["title"] == "x"


async def test_create_is_idempotent(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _typed_schema()
    fake_api.routes["/api/agile/work-item"] = lambda **_: {
        "value": {"_id": "w9", "whole_identifier": "TF2-99"}
    }
    async with _context(bound_user) as ctx:
        first = await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "联调", "assignee": "u1"},
            confirm=True,
            client_request_id="req-1",
        )
        second = await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "联调", "assignee": "u1"},
            confirm=True,
            client_request_id="req-1",
        )

    assert first == second
    assert first["identifier"] == "TF2-99"
    assert fake_api.paths().count("/api/agile/work-item") == 1
    body = next(
        json for _, path, _, json in fake_api.calls if path == "/api/agile/work-item"
    )
    values = {item["key"]: item["value"] for item in body["property_values"]}
    assert values["project_id"] == "p1"
    assert values["type"] == "t1"
    assert values["assignee"] == "u1"
    assert values["participants"] == ["u1"]


async def test_add_comment_requires_confirm(bound_user, fake_api):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.add_comment(ctx, id="w1", content="hi", confirm=False)
    assert excinfo.value.code == "confirmation_required"
    assert fake_api.calls == []


async def test_add_comment_success(bound_user, fake_api):
    fake_api.routes["/api/agile/work-items/w1/comment"] = lambda **_: {
        "value": {"_id": "c2"}
    }
    async with _context(bound_user) as ctx:
        data = await adapter.add_comment(ctx, id="w1", content="已确认", confirm=True)

    assert data == {"ok": True, "id": "c2"}
    assert fake_api.calls[0][3] == {"content": "已确认"}


async def test_unbound_credential_maps_to_error(user, fake_api):
    async def missing(*args, **kwargs):
        raise token_manager.IntegrationNotConfigured("尚未配置 PingCode 账号")

    fake_api.request = missing
    async with _context(user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.list_projects(ctx)
    assert excinfo.value.code == "integration_not_configured"


def test_description_template_renders_sections_and_placeholders():
    html = templates.render_description({"caseId": "CASE-1", "steps": "步骤一"})

    assert "测试用例" in html
    assert "1. 问题描述" in html
    assert "10. 测试日志" in html
    assert "步骤一" in html
    assert "CASE-1" in html
    assert html.count(">-<") >= 3


async def test_property_schema_reads_value_when_references_present(bound_user, fake_api):
    """真实响应 data 里 value 与 references 并列 —— 不能因为多一个键就丢字段."""

    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: {
        "value": {
            "properties": [
                {
                    "key": "title",
                    "name": "标题",
                    "type": 1,
                    "validators": {"is_required": True},
                    "options": [],
                }
            ]
        },
        "references": {"state": {"一": "新建"}},
    }
    async with _context(bound_user) as ctx:
        data = await adapter.get_property_schema(
            ctx, project_id="p1", work_item_type_id="t1"
        )

    assert [field["key"] for field in data["fields"]] == ["title"]
    assert data["fields"][0]["required"] is True


async def test_create_reads_value_when_references_present(bound_user, fake_api):
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = lambda **_: _typed_schema()
    fake_api.routes["/api/agile/work-item"] = lambda **_: {
        "value": {"_id": "w7", "whole_identifier": "TF2-77"},
        "references": {"state": {"一": "新建"}},
    }
    async with _context(bound_user) as ctx:
        data = await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "引用并存", "assignee": "u1"},
            confirm=True,
            client_request_id="req-ref-create",
        )

    assert data["id"] == "w7"
    assert data["identifier"] == "TF2-77"


async def test_add_comment_reads_value_when_references_present(bound_user, fake_api):
    fake_api.routes["/api/agile/work-items/w1/comment"] = lambda **_: {
        "value": {"_id": "c7"},
        "references": {"user": {"一": "张三"}},
    }
    async with _context(bound_user) as ctx:
        data = await adapter.add_comment(
            ctx, id="w1", content="引用并存", confirm=True
        )

    assert data == {"ok": True, "id": "c7"}


async def test_list_members_reads_roles_when_references_present(bound_user, fake_api):
    """roles 响应 data 里 value 与 references 并存时仍要解析出角色与成员."""

    fake_api.routes["/api/agile/projects/p1/roles"] = lambda **_: {
        "value": {"roles": [{"_id": "r1", "name": "项目成员"}]},
        "references": {"members": {"u1": {"display_name": "张三"}}},
    }
    fake_api.routes["/api/agile/projects/p1/roles/r1/members"] = lambda **_: {
        "value": [
            {"uid": "u1", "display_name": "张三", "name": "zhangsan", "email": "z@x"}
        ]
    }
    async with _context(bound_user) as ctx:
        data = await adapter.list_members(ctx, project_id="p1")

    assert [item["id"] for item in data["items"]] == ["u1"]
    assert data["items"][0]["name"] == "张三"


# ── 附件上传与 create attachments ──────────────────────────
def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 16


def _upload_token_route(fake_api, token: str = "upload-token") -> None:
    fake_api.routes["/api/typhon/secret/file/upload-token"] = lambda **_: token


async def test_upload_requires_confirm(bound_user, fake_api, tmp_path):
    src = tmp_path / "shot.png"
    src.write_bytes(_png_bytes())
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.upload_attachment(
                ctx, path=str(src), confirm=False, client_request_id="up-no-confirm"
            )

    assert excinfo.value.code == "confirmation_required"
    assert fake_api.calls == []
    assert fake_api.uploads == []


async def test_upload_requires_exactly_one_source(bound_user, fake_api, tmp_path):
    src = tmp_path / "shot.png"
    src.write_bytes(_png_bytes())
    payload = base64.b64encode(_png_bytes()).decode("ascii")
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as neither:
            await adapter.upload_attachment(
                ctx, confirm=True, client_request_id="up-none"
            )
        with pytest.raises(adapter.McpRuntimeError) as both:
            await adapter.upload_attachment(
                ctx,
                path=str(src),
                content_base64=payload,
                confirm=True,
                client_request_id="up-both",
            )

    assert neither.value.code == "invalid_arguments"
    assert both.value.code == "invalid_arguments"
    assert fake_api.uploads == []


async def test_upload_from_path_sends_token_scope_and_file(bound_user, fake_api, tmp_path):
    content = _png_bytes()
    src = tmp_path / "shot.png"
    src.write_bytes(content)
    _upload_token_route(fake_api, "tok-1")
    fake_api.upload_result = {"_id": "file-1"}
    async with _context(bound_user) as ctx:
        data = await adapter.upload_attachment(
            ctx,
            path=str(src),
            confirm=True,
            client_request_id="up-path",
        )

    token_call = next(
        call for call in fake_api.calls if call[1] == "/api/typhon/secret/file/upload-token"
    )
    assert token_call[2] == {
        "scope": 1,
        "size": len(base64.b64encode(content)),
    }
    assert fake_api.uploads == [
        {
            "user_id": bound_user.id,
            "path": "/atlas/file/upload",
            "token": "tok-1",
            "scope": 1,
            "filename": "shot.png",
            "content": content,
            "content_type": "image/png",
        }
    ]
    assert data["file_id"] == "file-1"
    assert data["bytes"] == len(content)
    assert data["content_type"] == "image/png"
    assert data["purpose"] == "attachment"
    assert data["scope"] == 1


async def test_upload_inline_returns_public_url(bound_user, fake_api):
    _upload_token_route(fake_api)
    fake_api.upload_result = {"_id": "file-9"}
    async with _context(bound_user) as ctx:
        data = await adapter.upload_attachment(
            ctx,
            content_base64=base64.b64encode(_png_bytes()).decode("ascii"),
            name="inline.png",
            purpose="inline",
            confirm=True,
            client_request_id="up-inline",
        )

    token_call = next(
        call for call in fake_api.calls if call[1] == "/api/typhon/secret/file/upload-token"
    )
    assert token_call[2]["scope"] == 3
    assert fake_api.uploads[0]["scope"] == 3
    assert data["public_url"] == f"{adapter._base_url()}/atlas/files/public/file-9"
    assert "attachment_id" not in data


async def test_upload_links_to_work_item(bound_user, fake_api):
    _upload_token_route(fake_api)
    fake_api.upload_result = {"_id": "file-2"}
    fake_api.routes["/api/agile/work-items/w1/attachment"] = lambda **_: {
        "value": {"_id": "att-1", "file_id": "file-2"}
    }
    async with _context(bound_user) as ctx:
        data = await adapter.upload_attachment(
            ctx,
            content_base64=base64.b64encode(_png_bytes()).decode("ascii"),
            name="linked.png",
            work_item_id="w1",
            confirm=True,
            client_request_id="up-link",
        )

    link_call = next(
        call for call in fake_api.calls if call[1] == "/api/agile/work-items/w1/attachment"
    )
    assert link_call[3] == {"file_id": "file-2"}
    assert data["attachment_id"] == "att-1"
    assert data["work_item_id"] == "w1"


async def test_upload_rejects_inline_with_work_item(bound_user, fake_api):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.upload_attachment(
                ctx,
                content_base64=base64.b64encode(_png_bytes()).decode("ascii"),
                name="x.png",
                purpose="inline",
                work_item_id="w1",
                confirm=True,
                client_request_id="up-inline-link",
            )

    assert excinfo.value.code == "invalid_arguments"
    assert fake_api.uploads == []


async def test_upload_rejects_oversize(bound_user, fake_api, monkeypatch):
    monkeypatch.setattr(adapter, "MAX_UPLOAD_BYTES", 8)
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.upload_attachment(
                ctx,
                content_base64=base64.b64encode(_png_bytes()).decode("ascii"),
                name="big.png",
                confirm=True,
                client_request_id="up-big",
            )

    assert excinfo.value.code == "attachment_too_large"
    assert fake_api.uploads == []


async def test_upload_rejects_missing_file(bound_user, fake_api, tmp_path):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.upload_attachment(
                ctx,
                path=str(tmp_path / "absent.png"),
                confirm=True,
                client_request_id="up-absent",
            )

    assert excinfo.value.code == "file_not_found"
    assert fake_api.uploads == []


async def test_upload_rejects_invalid_base64(bound_user, fake_api):
    async with _context(bound_user) as ctx:
        with pytest.raises(adapter.McpRuntimeError) as excinfo:
            await adapter.upload_attachment(
                ctx,
                content_base64="!!!not-base64!!!",
                name="bad.png",
                confirm=True,
                client_request_id="up-bad-b64",
            )

    assert excinfo.value.code == "invalid_arguments"
    assert fake_api.uploads == []


async def test_upload_is_idempotent(bound_user, fake_api):
    _upload_token_route(fake_api)
    payload = base64.b64encode(_png_bytes()).decode("ascii")
    async with _context(bound_user) as ctx:
        first = await adapter.upload_attachment(
            ctx, content_base64=payload, name="once.png", confirm=True,
            client_request_id="up-once",
        )
        second = await adapter.upload_attachment(
            ctx, content_base64=payload, name="once.png", confirm=True,
            client_request_id="up-once",
        )

    assert first == second
    assert len(fake_api.uploads) == 1
    assert fake_api.paths().count("/api/typhon/secret/file/upload-token") == 1


async def test_upload_requires_write_scope(user):
    principal = Principal(
        user=user, client_id="test-client", scopes=frozenset({"pingcode:read"})
    )
    async with _server(principal) as client:
        result = await call_tool(
            client,
            READ_TOKEN,
            "pingcode_upload_attachment",
            {"path": "/tmp/x.png", "confirm": True},
            endpoint=ENDPOINT,
        )

    assert result.get("isError") is True
    assert "scope" in result["content"][0]["text"].lower()


def _attachment_create_routes(fake_api, *, fail_link: bool = False) -> None:
    fake_api.routes["/api/agile/work-item/creation-template/properties"] = (
        lambda **_: _typed_schema()
    )
    fake_api.routes["/api/agile/work-item"] = lambda **_: {
        "value": {"_id": "w20", "whole_identifier": "TF2-120"}
    }

    def link(**_):
        if fail_link:
            raise pingcode_client.PingCodeBusinessError("附件关联失败", status=400)
        return {"value": {"_id": "att-20", "file_id": "f2"}}

    fake_api.routes["/api/agile/work-items/w20/attachment"] = link


async def test_create_links_attachments(bound_user, fake_api):
    _attachment_create_routes(fake_api)
    async with _context(bound_user) as ctx:
        result = await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "带附件", "assignee": "u1"},
            attachments=["f2", "f2", ""],
            confirm=True,
            client_request_id="req-att",
        )

    assert result["attachments"] == [
        {"file_id": "f2", "attachment_id": "att-20", "ok": True}
    ]
    link_calls = [
        call for call in fake_api.calls if call[1] == "/api/agile/work-items/w20/attachment"
    ]
    assert [call[3] for call in link_calls] == [{"file_id": "f2"}]
    body = next(
        json for _, path, _, json in fake_api.calls if path == "/api/agile/work-item"
    )
    values = {item["key"]: item["value"] for item in body["property_values"]}
    assert "attachments" not in values


async def test_create_surfaces_attachment_link_error(bound_user, fake_api):
    _attachment_create_routes(fake_api, fail_link=True)
    async with _context(bound_user) as ctx:
        result = await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "附件失败", "assignee": "u1"},
            attachments=["f2"],
            confirm=True,
            client_request_id="req-att-fail",
        )

    assert result["identifier"] == "TF2-120"
    assert result["attachments"][0]["file_id"] == "f2"
    assert result["attachments"][0]["ok"] is False
    assert result["attachments"][0]["error"]


async def test_create_idempotent_does_not_relink(bound_user, fake_api):
    _attachment_create_routes(fake_api)
    async with _context(bound_user) as ctx:
        first = await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "幂等附件", "assignee": "u1"},
            attachments=["f2"],
            confirm=True,
            client_request_id="req-att-idem",
        )
        second = await adapter.create_work_item(
            ctx,
            project_id="p1",
            work_item_type_id="t1",
            properties={"title": "幂等附件", "assignee": "u1"},
            attachments=["f2"],
            confirm=True,
            client_request_id="req-att-idem",
        )

    assert first == second
    assert fake_api.paths().count("/api/agile/work-items/w20/attachment") == 1


# ── testhub 用例库 ─────────────────────────────────────────
def _case_routes(fake_api):
    libraries = {
        "count": 1,
        "value": [
            {
                "_id": "lib1",
                "name": "HIMA 用例库",
                "short_id": "HIMA3361",
                "project_id": "p1",
                "case_count": 12,
            }
        ],
    }
    cases = {
        "count": 1,
        "value": [
            {
                "_id": "case1",
                "whole_identifier": "HIMA3361-8077",
                "title": "掉盘后恢复",
                "precondition": "设备已连接",
                "steps": [
                    {"index": "1", "description": "插拔", "expected_value": "识别"},
                ],
                "state_id": "st1",
                "suite_id": "su1",
                "created_by": "u1",
                "updated_at": 1700000000,
            }
        ],
    }
    states = {"value": [{"_id": "st1", "name": "已评审", "state_type": 1}]}
    suites = {"value": [{"_id": "su1", "name": "存储用例"}]}
    fields = {
        "value": [
            {
                "property_key": "properties.shiyongbanben",
                "name": "适用版本",
                "type": 1,
                "is_system": False,
                "options": [{"_id": "o1", "text": "V1.0"}],
            }
        ]
    }

    fake_api.routes["/api/testhub/test-libraries"] = lambda params, json: libraries
    fake_api.routes["/api/testhub/test-libraries/lib1/test-cases"] = (
        lambda params, json: cases
    )
    fake_api.routes["/api/testhub/test-case/states"] = lambda params, json: states
    fake_api.routes["/api/testhub/test-libraries/lib1/direct/suites"] = (
        lambda params, json: suites
    )
    fake_api.routes["/api/testhub/test-case/view/properties"] = (
        lambda params, json: fields
    )


async def test_list_test_case_libraries(bound_user, fake_api):
    _case_routes(fake_api)
    async with _context(bound_user) as ctx:
        result = await adapter.list_test_case_libraries(ctx)

    assert result["total"] == 1
    assert result["items"][0] == {
        "id": "lib1",
        "name": "HIMA 用例库",
        "identifier": "HIMA3361",
        "project_id": "p1",
        "description": "",
        "case_count": 12,
    }


async def test_search_test_cases_builds_criteria(bound_user, fake_api):
    _case_routes(fake_api)
    async with _context(bound_user) as ctx:
        result = await adapter.search_test_cases(
            ctx,
            library_id="lib1",
            identifier="HIMA3361-8077",
            page=2,
            page_size=50,
            filters=[{"property_key": "shiyongbanben", "operation": 6, "value": ["o1"]}],
        )

    assert result["items"][0]["identifier"] == "HIMA3361-8077"
    assert "steps" not in result["items"][0]
    call = next(c for c in fake_api.calls if c[1] == "/api/testhub/test-libraries/lib1/test-cases")
    assert call[0] == "POST"
    body = call[3]
    assert body["pi"] == 1
    assert body["ps"] == 50
    assert body["criteria"]["search"] == {"keywords": "8077", "scopes": ["identifier", "title"]}
    assert body["criteria"]["conditions"][0]["property_key"] == "shiyongbanben"
    assert body["criteria"]["conditions"][0]["operation"] == 6


async def test_search_test_cases_requires_library_id(bound_user):
    async with _context(bound_user) as ctx:
        with pytest.raises(McpRuntimeError):
            await adapter.search_test_cases(ctx, library_id="")


async def test_search_test_cases_rejects_bad_filters(bound_user):
    async with _context(bound_user) as ctx:
        with pytest.raises(McpRuntimeError):
            await adapter.search_test_cases(
                ctx, library_id="lib1", filters=[{"operation": 6}]
            )
        with pytest.raises(McpRuntimeError):
            await adapter.search_test_cases(
                ctx, library_id="lib1", filters=[{"property_key": "x", "operation": "bad"}]
            )


async def test_get_test_case_matches_full_identifier_and_enriches(bound_user, fake_api):
    _case_routes(fake_api)
    async with _context(bound_user) as ctx:
        result = await adapter.get_test_case(
            ctx, identifier="HIMA3361-8077", library_id="lib1"
        )

    assert result["identifier"] == "HIMA3361-8077"
    assert result["steps"][0] == {
        "index": 1,
        "description": "插拔",
        "expected_value": "识别",
    }
    assert result["state"] == {"id": "st1", "name": "已评审", "state_type": 1}
    assert result["suite"] == {"id": "su1", "name": "存储用例"}
    assert result["attributes"]["created_by"] == "u1"


async def test_get_test_case_matches_short_identifier(bound_user, fake_api):
    _case_routes(fake_api)
    async with _context(bound_user) as ctx:
        result = await adapter.get_test_case(ctx, identifier="8077", library_id="lib1")

    assert result["identifier"] == "HIMA3361-8077"


async def test_get_test_case_not_found(bound_user, fake_api):
    _case_routes(fake_api)
    async with _context(bound_user) as ctx:
        with pytest.raises(McpRuntimeError) as exc:
            await adapter.get_test_case(ctx, identifier="9999", library_id="lib1")

    assert exc.value.code == "not_found"


async def test_get_test_case_properties_normalizes(bound_user, fake_api):
    _case_routes(fake_api)
    async with _context(bound_user) as ctx:
        result = await adapter.get_test_case_properties(ctx, library_id="lib1")

    assert result["fields"] == [
        {
            "key": "shiyongbanben",
            "name": "适用版本",
            "type": 1,
            "is_system": False,
            "options": [{"id": "o1", "text": "V1.0"}],
        }
    ]
