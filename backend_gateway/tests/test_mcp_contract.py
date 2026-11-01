"""REST/MCP write parity over real HTTP and production MCP authentication."""
from __future__ import annotations

import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import marketplace
from app.core import git_sync
from app.core.market_catalog import build_manifest
from app.db.session import AsyncSessionLocal
from app.mcp.common.auth import McpTokenVerifier
from app.mcp.common.context import McpContext, Principal
from app.mcp.common.oauth import issue_access_token
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.skill import adapter
from app.mcp.skill.server import build_skill_server
from app.models.asset import Asset
from app.models.mcp import McpOAuthClient, McpOAuthGrant
from app.models.user import User, UserRole
from app.schemas.asset import AssetJobOut, AssetMetaUpdateIn
from tests._mcp_protocol import call_tool_data
from tests.conftest import set_setting

API = "/api/v1/assets"
PUBLIC_BASE = "http://test"
SCENARIOS = ("publish", "update", "edit_meta", "submit_review", "unpublish_request")


class _FakeRedis:
    async def eval(self, script, numkeys, *args):
        return [1, "ok"]


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """Observe the exact route notification calls without contacting DingTalk."""
    sent = []

    async def fake_notify(event, asset=None, **kwargs):
        sent.append(
            {
                "event": event,
                "asset": copy.deepcopy(asset),
                "kwargs": copy.deepcopy(kwargs),
            }
        )
        return True

    monkeypatch.setattr(marketplace.market_notify, "notify_asset", fake_notify)
    return sent


@pytest.fixture
async def credentials(publisher_user):
    await set_setting("marketplace.public_base_url", PUBLIC_BASE)
    await set_setting("marketplace.publisher_roles", "tester")
    await set_setting("marketplace.review.enabled", "true")
    async with AsyncSessionLocal() as session:
        user = await session.get(User, publisher_user["id"])
        assert user is not None
        client_id = "rest-mcp-contract-client"
        session.add(
            McpOAuthClient(
                client_id=client_id,
                client_name="REST/MCP contract test client",
                redirect_uris=["http://127.0.0.1:51234/callback"],
                scopes=["market:read", "market:write"],
            )
        )
        grant = McpOAuthGrant(
            user_id=user.id,
            client_id=client_id,
            scopes=["market:read", "market:write"],
            version=1,
        )
        session.add(grant)
        await session.commit()
        await session.refresh(grant)
        token = await issue_access_token(user, grant, PUBLIC_BASE)
    return {
        "rest_token": publisher_user["token"],
        "mcp_token": token,
        "grant_id": grant.id,
        "username": publisher_user["username"],
    }


@asynccontextmanager
async def _transport_client():
    # No verifier override: build_skill_server installs production McpTokenVerifier.
    server = build_skill_server(
        public_base_url=PUBLIC_BASE,
        allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    assert isinstance(server._token_verifier, McpTokenVerifier)
    dispatcher = build_dispatcher({"skill": server})
    app = FastAPI()
    app.include_router(marketplace.router, prefix=API)
    app.mount("/mcp", dispatcher)
    async with run_mcp_lifespan(dispatcher):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=PUBLIC_BASE
        ) as client:
            yield client


def _skill_files(code: str, marker: str) -> dict[str, str]:
    return {
        "SKILL.md": (
            f"---\nname: {code}\ndescription: Contract fixture\n---\n\n"
            f"# {code}\n\n{marker}\n"
        ),
        "docs/note.txt": f"{marker} for {code}\n",
    }


def _multipart(files: dict[str, str]) -> list[tuple[str, tuple[str, str, str]]]:
    return [
        ("files", (path, content, "text/plain")) for path, content in files.items()
    ]


def _initial_metadata() -> dict[str, Any]:
    return {
        "name": "Contract asset",
        "icon": "I",
        "summary": "Initial summary",
        "description": "Initial description",
        "use_when": "Initial use",
        "not_for": "Initial exclusion",
        "category": "质量保障",
        "project": "",
        "tags": ["initial"],
        "keywords": ["contract"],
        "permissions": {"network": False},
        "install_steps": ["copy"],
        "bindings": {"agent": "qa"},
        "featured": True,
    }


def _form_data(code: str, version: str, metadata: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": code,
        "kind": "skill",
        "version": version,
        **metadata,
    }
    for field in ("tags", "keywords", "permissions", "install_steps", "bindings"):
        data[field] = json.dumps(data[field], ensure_ascii=False)
    return data


async def _seed_asset(code: str, username: str, scenario: str) -> None:
    if scenario == "publish":
        return
    metadata = _initial_metadata()
    manifest = build_manifest(
        code=code,
        kind="skill",
        version="1.0.0",
        author=username,
        **metadata,
    )
    files = _skill_files(code, "initial")
    manifest.update(
        {
            "publish_status": "rejected" if scenario == "submit_review" else "published",
            "review_note": "Needs changes" if scenario == "submit_review" else "",
            "files": sorted(files),
            "doc_file": "SKILL.md",
            "package_name": "",
            "package_sha256": "",
        }
    )
    asset = Asset(
        code=code,
        name=metadata["name"],
        icon=metadata["icon"],
        kind="skill",
        version="1.0.0",
        summary=metadata["summary"],
        description=metadata["description"],
        use_when=metadata["use_when"],
        not_for=metadata["not_for"],
        category=metadata["category"],
        project=metadata["project"],
        tags=metadata["tags"],
        keywords=metadata["keywords"],
        permissions=metadata["permissions"],
        install_steps=metadata["install_steps"],
        bindings=metadata["bindings"],
        author=username,
        featured=metadata["featured"],
        git_path=manifest["git_path"],
        publish_status=manifest["publish_status"],
        pending_action="new" if scenario == "submit_review" else "",
        review_note=manifest["review_note"],
        sync_status="pushed",
    )
    async with AsyncSessionLocal() as session:
        session.add(asset)
        await session.commit()

    root = git_sync.WORKSPACE / manifest["git_path"]
    (root / "files" / "docs").mkdir(parents=True)
    for path, content in files.items():
        (root / "files" / path).write_text(content, encoding="utf-8")
    (root / "README.md").write_text(metadata["description"], encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def _execute_rest(
    client: AsyncClient, token: str, scenario: str, code: str
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    if scenario == "publish":
        metadata = _initial_metadata() | {
            "name": "Published contract asset",
            "summary": "Contract publish summary",
        }
        response = await client.post(
            f"{API}/upload",
            data=_form_data(code, "1.0.0", metadata),
            files=_multipart(_skill_files(code, "publish")),
            headers=headers,
        )
        expected_status = 202
    elif scenario == "update":
        # MCP omits unchanged metadata and retains it; REST supplies those same
        # retained values explicitly because its PUT form requires them.
        metadata = _initial_metadata() | {"summary": "Contract update summary"}
        response = await client.put(
            f"{API}/{code}",
            data=_form_data(code, "2.0.0", metadata),
            files=_multipart(_skill_files(code, "update")),
            headers=headers,
        )
        expected_status = 202
    elif scenario == "edit_meta":
        response = await client.patch(
            f"{API}/{code}",
            json={
                "summary": "Contract edited summary",
                "description": "Edited description",
                "tags": ["edited", "contract"],
                "permissions": {"network": True},
            },
            headers=headers,
        )
        expected_status = 202
    elif scenario == "submit_review":
        response = await client.post(
            f"{API}/{code}/submit",
            data={"comment": "Please review contract asset"},
            headers=headers,
        )
        expected_status = 200
    else:
        response = await client.post(
            f"{API}/{code}/unpublish",
            data={"confirm_code": code, "comment": "Contract unpublish reason"},
            headers=headers,
        )
        expected_status = 200
    assert response.status_code == expected_status, response.text
    return response.json()


async def _execute_mcp(
    client: AsyncClient, token: str, scenario: str, code: str
) -> dict[str, Any]:
    if scenario == "publish":
        arguments = _initial_metadata() | {
            "code": code,
            "name": "Published contract asset",
            "version": "1.0.0",
            "summary": "Contract publish summary",
            "files": _skill_files(code, "publish"),
        }
    elif scenario == "update":
        arguments = {
            "code": code,
            "version": "2.0.0",
            "summary": "Contract update summary",
            "files": _skill_files(code, "update"),
        }
    elif scenario == "edit_meta":
        arguments = {
            "code": code,
            "summary": "Contract edited summary",
            "description": "Edited description",
            "tags": ["edited", "contract"],
            "permissions": {"network": True},
        }
    elif scenario == "submit_review":
        arguments = {"code": code, "comment": "Please review contract asset"}
    else:
        arguments = {"code": code, "reason": "Contract unpublish reason"}
    return await call_tool_data(client, token, f"skill_{scenario}", arguments)


_GENERATED_ID_PATHS = {
    ("id",),
    ("job_id",),
    ("*", "asset", "job_id"),
}
_GENERATED_TIMESTAMP_PATHS = {
    (field,) for field in (
        "created_at", "updated_at", "staged_at", "pushed_at", "next_retry_at"
    )
}


def _normalize(value: Any, code: str, path: tuple[str, ...] = ()) -> Any:
    """Alias only generated values at known response/notification paths."""
    if path in _GENERATED_ID_PATHS:
        assert isinstance(value, int) and not isinstance(value, bool) and value > 0
        return "<generated-id>"
    if path in _GENERATED_TIMESTAMP_PATHS:
        if value is None or value == "":
            return value
        if isinstance(value, datetime):
            return "<timestamp:datetime>"
        assert isinstance(value, str) and value
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise AssertionError(f"Invalid generated timestamp: {value!r}") from exc
        return "<timestamp:str>"
    if isinstance(value, dict):
        return {
            key: _normalize(item, code, (*path, key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize(item, code, (*path, "*")) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item, code, (*path, "*")) for item in value)
    if isinstance(value, str):
        return value.replace(code, "<code>")
    return value


def test_normalize_does_not_alias_arbitrary_nested_ids():
    rest = {"payload": {"id": 101}}
    mcp = {"payload": {"id": 202}}
    assert _normalize(rest, "rest-code") != _normalize(mcp, "mcp-code")


def test_normalize_rejects_non_timestamp_strings():
    with pytest.raises(AssertionError):
        _normalize({"created_at": "not-a-timestamp"}, "contract-code")


def test_normalize_preserves_timestamp_types():
    value = datetime(2026, 10, 31, 12, 30, 0)
    assert _normalize({"created_at": value}, "contract-code") != _normalize(
        {"created_at": value.isoformat()}, "contract-code"
    )


def test_normalize_preserves_sequence_container_types():
    assert _normalize({"items": ["one"]}, "contract-code") != _normalize(
        {"items": ("one",)}, "contract-code"
    )


def _expected_state_change(scenario: str, username: str) -> dict[str, Any]:
    assert scenario in {"submit_review", "unpublish_request"}
    return {
        "ok": True,
        "code": "<code>",
        "publish_status": (
            "pending" if scenario == "submit_review" else "unpublish_pending"
        ),
        "changed": True,
        "job_id": "<generated-id>",
        "name": "Contract asset",
        "version": "1.0.0",
        "kind": "skill",
        "category": "质量保障",
        "author": username,
        "project": "",
        # ⚠️ 2026-11-01: 通知要带资产简介 (审核通过的上架通知靠它填「说明」)
        "summary": "Initial summary",
        "pending_action": "new" if scenario == "submit_review" else "",
    }


def _expected_response(scenario: str, username: str) -> dict[str, Any]:
    if scenario == "submit_review":
        return _expected_state_change(scenario, username)
    if scenario == "unpublish_request":
        return {
            "ok": True,
            "code": "<code>",
            "publish_status": "unpublish_pending",
            "changed": True,
            "needs_review": True,
        }
    return {
        "id": "<generated-id>",
        "action": {
            "publish": "create",
            "update": "update",
            "edit_meta": "update_meta",
        }[scenario],
        "status": "staged",
        "code": "<code>",
        "asset_name": (
            "Published contract asset" if scenario == "publish" else "Contract asset"
        ),
        "kind": "skill",
        "git_path": "assets/skills/quality/<code>",
        "commit_sha": "",
        "error": "",
        "attempts": 0,
        "staged_at": None,
        "pushed_at": None,
        "next_retry_at": None,
        "created_at": "<timestamp:str>",
        "updated_at": "<timestamp:str>",
    }


def _expected_notifications(scenario: str, username: str) -> list[dict[str, Any]]:
    if scenario in {"submit_review", "unpublish_request"}:
        return [
            {
                "event": (
                    "review" if scenario == "submit_review" else "unpublish_request"
                ),
                "asset": _expected_state_change(scenario, username),
                "kwargs": {
                    "actor": username,
                    "detail": (
                        "Please review contract asset"
                        if scenario == "submit_review"
                        else "Contract unpublish reason"
                    ),
                    # ⚠️ 显式传空 = 用 detail 说"发生了什么", 不拿简介顶替
                    "summary": "",
                },
            }
        ]

    edited = scenario == "edit_meta"
    asset = {
        "schema_version": 1,
        "code": "<code>",
        "name": "Published contract asset" if scenario == "publish" else "Contract asset",
        "icon": "I",
        "kind": "skill",
        "version": {"publish": "1.0.0", "update": "2.0.0", "edit_meta": "1.0.0"}[
            scenario
        ],
        "summary": {
            "publish": "Contract publish summary",
            "update": "Contract update summary",
            "edit_meta": "Contract edited summary",
        }[scenario],
        "description": "Edited description" if edited else "Initial description",
        "use_when": "Initial use",
        "not_for": "Initial exclusion",
        "category": "质量保障",
        "project": "",
        "tags": ["edited", "contract"] if edited else ["initial"],
        "keywords": ["contract"],
        "author": username,
        "featured": True,
        "homepage": None,
        "permissions": {"network": edited},
        "install_steps": ["copy"],
        "bindings": {"agent": "qa"},
        "git_path": "assets/skills/quality/<code>",
        "mcp_config": None,
        "updated_at": "",
        "publish_status": "pending",
        "files": ["SKILL.md", "docs/note.txt"],
        "doc_file": "SKILL.md",
        "package_sha256": "",
        "package_name": "",
    }
    kwargs = {
        "actor": username,
        "detail": {
            "publish": "提交了新资产, 等管理员审核",
            "update": "更新了资产, 等管理员审核",
            "edit_meta": "修改了资产信息, 等管理员审核",
        }[scenario],
        "author": username,
    }
    if edited:
        kwargs["title_override"] = "📝 资产信息修改, 待审核"
    return [{"event": "review", "asset": asset, "kwargs": kwargs}]


def _assert_expected_contract(
    scenario: str,
    response: dict[str, Any],
    notifications: list[dict[str, Any]],
    username: str,
) -> None:
    assert response == _expected_response(scenario, username)
    assert notifications == _expected_notifications(scenario, username)


def test_scenario_anchors_reject_deliberate_semantic_mutations():
    for scenario in SCENARIOS:
        username = "publisher_t"
        response = _expected_response(scenario, username)
        notifications = _expected_notifications(scenario, username)

        if scenario in {"publish", "update", "edit_meta"}:
            response["action"] = "wrong-action"
        elif scenario == "submit_review":
            response["changed"] = False
        else:
            response["needs_review"] = False
        with pytest.raises(AssertionError):
            _assert_expected_contract(scenario, response, notifications, username)

        response = _expected_response(scenario, username)
        if scenario in {"publish", "update", "edit_meta"}:
            response["status"] = "succeeded"
        else:
            response["publish_status"] = "published"
        with pytest.raises(AssertionError):
            _assert_expected_contract(scenario, response, notifications, username)

        response = _expected_response(scenario, username)
        notifications[0]["kwargs"]["actor"] = "wrong-actor"
        with pytest.raises(AssertionError):
            _assert_expected_contract(scenario, response, notifications, username)

        notifications = _expected_notifications(scenario, username)
        notifications[0]["kwargs"]["detail"] = "wrong detail"
        with pytest.raises(AssertionError):
            _assert_expected_contract(scenario, response, notifications, username)

        notifications = _expected_notifications(scenario, username)
        if scenario in {"publish", "update", "edit_meta"}:
            notifications[0]["asset"]["publish_status"] = "published"
        else:
            notifications[0]["asset"]["changed"] = False
        with pytest.raises(AssertionError):
            _assert_expected_contract(scenario, response, notifications, username)


_STATE_FIELDS = (
    "code",
    "name",
    "icon",
    "kind",
    "version",
    "summary",
    "description",
    "use_when",
    "not_for",
    "category",
    "project",
    "tags",
    "keywords",
    "permissions",
    "install_steps",
    "bindings",
    "author",
    "featured",
    "homepage",
    "git_path",
    "git_commit_sha",
    "git_web_url",
    "sync_status",
    "last_error",
    "publish_status",
    "pending_action",
    "review_note",
    "download_count",
    "mcp_config",
)


async def _asset_state(code: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        asset = (
            await session.execute(select(Asset).where(Asset.code == code))
        ).scalar_one()
        state = {field: getattr(asset, field) for field in _STATE_FIELDS}
        state["featured"] = bool(state["featured"])
        return _normalize(state, code)


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_rest_and_mcp_write_scenarios_have_equivalent_contracts(
    scenario,
    credentials,
    ws,
    restore_git_config,
    notifications,
):
    code_scenario = scenario.replace("_", "-")
    rest_code = f"rest-{code_scenario}"
    mcp_code = f"mcp-{code_scenario}"
    assert rest_code != mcp_code
    await _seed_asset(rest_code, credentials["username"], scenario)
    await _seed_asset(mcp_code, credentials["username"], scenario)

    async with _transport_client() as client:
        notifications.clear()
        rest_response = await _execute_rest(
            client, credentials["rest_token"], scenario, rest_code
        )
        rest_notifications = copy.deepcopy(notifications)
        rest_state = await _asset_state(rest_code)

        notifications.clear()
        mcp_response = await _execute_mcp(
            client, credentials["mcp_token"], scenario, mcp_code
        )
        mcp_notifications = copy.deepcopy(notifications)
        mcp_state = await _asset_state(mcp_code)

    normalized_rest_response = _normalize(rest_response, rest_code)
    normalized_mcp_response = _normalize(mcp_response, mcp_code)
    normalized_rest_notifications = _normalize(rest_notifications, rest_code)
    normalized_mcp_notifications = _normalize(mcp_notifications, mcp_code)
    assert normalized_rest_response == normalized_mcp_response
    assert normalized_rest_notifications == normalized_mcp_notifications
    for response, notification_calls in (
        (normalized_rest_response, normalized_rest_notifications),
        (normalized_mcp_response, normalized_mcp_notifications),
    ):
        _assert_expected_contract(
            scenario, response, notification_calls, credentials["username"]
        )
    expected_event = (
        "unpublish_request" if scenario == "unpublish_request" else "review"
    )
    assert [item["event"] for item in rest_notifications] == [expected_event]
    assert [item["event"] for item in mcp_notifications] == [expected_event]
    assert rest_state == mcp_state

    expected_core = {
        "publish": ("pending", "new", "1.0.0", "Contract publish summary"),
        "update": ("pending", "update", "2.0.0", "Contract update summary"),
        "edit_meta": ("pending", "meta", "1.0.0", "Contract edited summary"),
        "submit_review": ("pending", "new", "1.0.0", "Initial summary"),
        "unpublish_request": ("unpublish_pending", "", "1.0.0", "Initial summary"),
    }[scenario]
    for state in (rest_state, mcp_state):
        assert (
            state["publish_status"],
            state["pending_action"],
            state["version"],
            state["summary"],
        ) == expected_core


def _mapping_context() -> tuple[McpContext, User]:
    user = User(username="mapping-user", password_hash="unused", role=UserRole.tester)
    user.id = 41
    principal = Principal(
        user=user, client_id="mapping-tests", scopes=frozenset({"market:write"})
    )
    return McpContext(principal=principal, session=None), user


def _job(code: str, action: str = "create") -> AssetJobOut:
    return AssetJobOut(id=1, action=action, status="staged", code=code)


def _take_route_user(call: dict[str, Any]) -> User:
    names = [name for name in ("user", "_user") if name in call]
    assert len(names) == 1
    return call.pop(names[0])


async def _upload_contents(uploads) -> list[tuple[str, str]]:
    return [(upload.filename, (await upload.read()).decode("utf-8")) for upload in uploads]


async def test_publish_adapter_maps_every_explicit_route_parameter(monkeypatch):
    ctx, user = _mapping_context()
    calls = {}

    async def require_publisher(candidate):
        calls.setdefault("publisher", []).append(candidate)

    async def upload_asset(**kwargs):
        calls["route"] = kwargs
        return _job(kwargs["code"])

    monkeypatch.setattr(marketplace, "require_publisher", require_publisher)
    monkeypatch.setattr(marketplace, "upload_asset", upload_asset)
    files = {"SKILL.md": "skill body", "docs/note.txt": "note body"}
    await adapter.publish(
        ctx,
        code="mapping-publish",
        name="Publish name",
        version="1.2.3",
        summary="Publish summary",
        description="Publish description",
        use_when="Use now",
        not_for="Not later",
        category="质量保障",
        project="6100",
        icon="P",
        tags=["one", "two"],
        keywords=["key"],
        featured=True,
        permissions={"network": True},
        install_steps=["copy", "restart"],
        bindings={"agent": "writer"},
        files=files,
    )

    call = calls["route"]
    assert _take_route_user(call) is user
    uploads = call.pop("files")
    assert call == {
        "code": "mapping-publish",
        "kind": "skill",
        "name": "Publish name",
        "summary": "Publish summary",
        "version": "1.2.3",
        "description": "Publish description",
        "use_when": "Use now",
        "not_for": "Not later",
        "category": "质量保障",
        "project": "6100",
        "icon": "P",
        "tags": '["one", "two"]',
        "keywords": '["key"]',
        "featured": True,
        "permissions": '{"network": true}',
        "install_steps": '["copy", "restart"]',
        "bindings": '{"agent": "writer"}',
        "mcp_config": "",
        "package": None,
    }
    assert await _upload_contents(uploads) == list(files.items())
    assert calls["publisher"] == [user]


async def test_update_adapter_maps_every_explicit_route_parameter(monkeypatch):
    ctx, user = _mapping_context()
    current = Asset(
        code="mapping-update",
        name="Old name",
        icon="O",
        kind="skill",
        version="1.0.0",
        summary="Old summary",
        description="Old description",
        use_when="Old use",
        not_for="Old exclusion",
        category="其他",
        project="",
        tags=["old"],
        keywords=["old"],
        permissions={},
        install_steps=[],
        bindings={},
        featured=True,
    )
    calls = {}

    async def get_asset(**kwargs):
        calls["get"] = kwargs
        return current

    async def require_publisher(candidate):
        calls.setdefault("publisher", []).append(candidate)

    async def update_asset(**kwargs):
        calls["route"] = kwargs
        return _job(kwargs["code"], "update")

    monkeypatch.setattr(marketplace, "get_asset", get_asset)
    monkeypatch.setattr(marketplace, "require_publisher", require_publisher)
    monkeypatch.setattr(marketplace, "update_asset", update_asset)
    files = {"SKILL.md": "new body"}
    await adapter.update(
        ctx,
        code="mapping-update",
        version="2.0.0",
        name="New name",
        summary="New summary",
        description="New description",
        use_when="New use",
        not_for="New exclusion",
        category="质量保障",
        project="6100",
        icon="N",
        tags=["new"],
        keywords=["new-key"],
        featured=False,
        permissions={"network": False},
        install_steps=["install"],
        bindings={"agent": "new"},
        files=files,
    )

    get_call = calls["get"]
    assert _take_route_user(get_call) is user
    assert get_call == {"code": "mapping-update", "client_id": "local"}
    call = calls["route"]
    assert _take_route_user(call) is user
    uploads = call.pop("files")
    assert call == {
        "code": "mapping-update",
        "kind": "skill",
        "name": "New name",
        "summary": "New summary",
        "version": "2.0.0",
        "description": "New description",
        "use_when": "New use",
        "not_for": "New exclusion",
        "category": "质量保障",
        "project": "6100",
        "icon": "N",
        "tags": '["new"]',
        "keywords": '["new-key"]',
        "featured": False,
        "permissions": '{"network": false}',
        "install_steps": '["install"]',
        "bindings": '{"agent": "new"}',
        "mcp_config": "",
        "package": None,
    }
    assert await _upload_contents(uploads) == list(files.items())
    assert calls["publisher"] == [user]


async def test_edit_meta_adapter_maps_every_explicit_route_parameter(monkeypatch):
    ctx, user = _mapping_context()
    calls = {}

    async def require_publisher(candidate):
        calls.setdefault("publisher", []).append(candidate)

    async def update_asset_meta(**kwargs):
        calls["route"] = kwargs
        return _job(kwargs["code"], "meta_only")

    monkeypatch.setattr(marketplace, "require_publisher", require_publisher)
    monkeypatch.setattr(marketplace, "update_asset_meta", update_asset_meta)
    changes = {
        "name": "Meta name",
        "icon": "M",
        "summary": "Meta summary",
        "description": "Meta description",
        "use_when": "Meta use",
        "not_for": "Meta exclusion",
        "category": "流程规范",
        "project": "7000",
        "tags": ["meta"],
        "keywords": ["meta-key"],
        "permissions":{"filesystem": "read"},
        "install_steps": ["meta-install"],
        "bindings": {"agent": "meta"},
    }
    await adapter.edit_meta(ctx, code="mapping-meta", **changes)

    call = calls["route"]
    assert _take_route_user(call) is user
    assert call["code"] == "mapping-meta"
    assert isinstance(call["payload"], AssetMetaUpdateIn)
    assert call["payload"].model_dump(exclude_unset=True) == changes
    assert set(call) == {"code", "payload"}
    assert calls["publisher"] == [user]


async def test_submit_review_adapter_maps_code_comment_and_any_user_name(monkeypatch):
    ctx, user = _mapping_context()
    calls = {}

    async def require_publisher(candidate):
        calls.setdefault("publisher", []).append(candidate)

    async def submit_for_review(**kwargs):
        calls["route"] = kwargs
        return {"ok": True, "code": kwargs["code"], "changed": True}

    monkeypatch.setattr(marketplace, "require_publisher", require_publisher)
    monkeypatch.setattr(marketplace, "submit_for_review", submit_for_review)
    await adapter.submit_review(ctx, code="mapping-submit", comment="Exact comment")

    call = calls["route"]
    assert _take_route_user(call) is user
    assert call == {"code": "mapping-submit", "comment": "Exact comment"}
    assert calls["publisher"] == [user]


async def test_unpublish_adapter_maps_confirmation_and_reason(monkeypatch):
    ctx, user = _mapping_context()
    calls = {}

    async def require_publisher(candidate):
        calls.setdefault("publisher", []).append(candidate)

    async def unpublish_asset(**kwargs):
        calls["route"] = kwargs
        return {"ok": True, "code": kwargs["code"], "changed": True}

    monkeypatch.setattr(marketplace, "require_publisher", require_publisher)
    monkeypatch.setattr(marketplace, "unpublish_asset", unpublish_asset)
    await adapter.unpublish_request(ctx, code="mapping-unpublish", reason="Exact reason")

    call = calls["route"]
    assert _take_route_user(call) is user
    assert call == {
        "code": "mapping-unpublish",
        "confirm_code": "mapping-unpublish",
        "comment": "Exact reason",
    }
    assert calls["publisher"] == [user]
