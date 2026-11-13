"""pingcode MCP 域: 13 个工具 schema、scope、幂等与适配输出 (mock 上游)."""
from __future__ import annotations

import base64
import json
import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.db.session import AsyncSessionLocal
from app.integrations import crypto
from app.integrations.pingcode import token_manager
from app.mcp.common.context import McpContext, Principal
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
async def test_tools_list_exposes_thirteen_strict_schemas(user):
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


def _typed_schema() -> dict:
    return {
        "value": {
            "properties": [
                {"key": "title", "type": 1, "validators": {"is_required": True}},
                {"key": "start", "type": 4, "validators": {"is_required": True}},
                {"key": "ceshitexing", "type": 20, "validators": {"is_required": True}},
                {"key": "kaifamokuai", "type": 20, "validators": {"is_required": True}},
            ]
        },
        "references": {},
    }


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
            properties={"title": "引用并存"},
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
