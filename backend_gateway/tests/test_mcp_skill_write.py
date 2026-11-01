"""Real Streamable HTTP contract tests for the five marketplace write tools."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import zipfile
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken, TokenVerifier
from sqlalchemy import func, select
from starlette.applications import Starlette
from starlette.routing import Mount

from app.api import marketplace
from app.core import market_projects
from app.db.session import AsyncSessionLocal
from app.mcp.common.context import Principal
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.skill.server import build_skill_server
from app.models.asset import Asset, AssetAudit, AssetJob
from app.models.mcp import McpToolCall
from app.models.user import User, UserRole
from tests._mcp_protocol import call_tool, list_tools
from tests.conftest import set_setting

OWNER_TOKEN = "skill-write-owner-token"
OTHER_PUBLISHER_TOKEN = "skill-write-other-publisher-token"
NON_PUBLISHER_TOKEN = "skill-write-non-publisher-token"
READ_ONLY_TOKEN = "skill-write-read-only-token"

READ_TOOL_NAMES = {
    "skill_search",
    "skill_get",
    "skill_read_doc",
    "skill_list_files",
    "skill_read_file",
    "skill_package_info",
    "skill_categories",
    "skill_projects",
    "skill_job_status",
}
WRITE_TOOL_NAMES = {
    "skill_publish",
    "skill_update",
    "skill_edit_meta",
    "skill_submit_review",
    "skill_unpublish_request",
}
TOOL_NAMES = READ_TOOL_NAMES | WRITE_TOOL_NAMES

_METADATA_PROPERTIES = {
    "name",
    "icon",
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
}
_PACKAGE_PROPERTIES = {"files", "package_base64"}
EXPECTED_SCHEMAS = {
    "skill_search": (
        [],
        {
            "keyword",
            "category",
            "project",
            "tag",
            "author",
            "include_unpublished",
            "page",
            "page_size",
        },
    ),
    "skill_get": (["code"], {"code"}),
    "skill_read_doc": (["code"], {"code"}),
    "skill_list_files": (["code"], {"code"}),
    "skill_read_file": (["code", "path"], {"code", "path"}),
    "skill_package_info": (["code"], {"code", "version"}),
    "skill_categories": ([], set()),
    "skill_projects": ([], set()),
    "skill_job_status": (["job_id"], {"job_id"}),
    "skill_publish": (
        ["code", "name", "version", "summary"],
        {"code", "version", "featured"} | _METADATA_PROPERTIES | _PACKAGE_PROPERTIES,
    ),
    "skill_update": (
        ["code", "version"],
        {"code", "version", "featured"} | _METADATA_PROPERTIES | _PACKAGE_PROPERTIES,
    ),
    "skill_edit_meta": (["code"], {"code"} | _METADATA_PROPERTIES),
    "skill_submit_review": (["code"], {"code", "comment"}),
    "skill_unpublish_request": (["code"], {"code", "reason"}),
}


class _FakeRedis:
    async def eval(self, script, numkeys, *args):
        return [1, "ok"]


class _WriteTokenVerifier(TokenVerifier):
    def __init__(self, principals: dict[str, Principal]):
        self.principals = principals

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = self.principals.get(token)
        if principal is None:
            return None
        return AccessToken(
            token=token,
            client_id=principal.client_id,
            scopes=sorted(principal.scopes),
            subject=str(principal.user.id),
            claims={"principal": principal},
        )


@pytest.fixture
async def principals():
    async with AsyncSessionLocal() as session:
        users = [
            User(username="mcp-write-owner", password_hash="unused", role=UserRole.tester),
            User(username="mcp-write-other", password_hash="unused", role=UserRole.tester),
            User(username="mcp-write-viewer", password_hash="unused", role=UserRole.viewer),
        ]
        session.add_all(users)
        await session.commit()
        for user in users:
            await session.refresh(user)
        owner, other, viewer = users

    def principal(user: User, scopes: frozenset[str]) -> Principal:
        return Principal(user=user, client_id="skill-write-tests", scopes=scopes)

    write = frozenset({"market:read", "market:write"})
    return {
        OWNER_TOKEN: principal(owner, write),
        OTHER_PUBLISHER_TOKEN: principal(other, write),
        NON_PUBLISHER_TOKEN: principal(viewer, write),
        READ_ONLY_TOKEN: principal(owner, frozenset({"market:read"})),
    }


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """Keep route notification behavior observable without contacting DingTalk."""
    sent = []

    async def fake_notify(event, asset=None, **kwargs):
        sent.append((event, asset, kwargs))
        return True

    monkeypatch.setattr(marketplace.market_notify, "notify_asset", fake_notify)
    return sent


@asynccontextmanager
async def _client(principals):
    server = build_skill_server(
        public_base_url="http://test",
        allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    server._token_verifier = _WriteTokenVerifier(principals)
    dispatcher = build_dispatcher({"skill": server})
    app = Starlette(routes=[Mount("/mcp", app=dispatcher)])
    async with run_mcp_lifespan(dispatcher):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


def _data(result):
    assert result.get("isError") is not True, result
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    return json.loads(result["content"][0]["text"])


def _error(result) -> str:
    assert result.get("isError") is True, result
    text = "\n".join(
        item["text"] for item in result["content"] if item["type"] == "text"
    )
    return text.split(": ", 1)[1] if text.startswith("Error executing tool ") else text


async def _call(client, token, tool_name, **arguments):
    return _data(await call_tool(client, token, tool_name, arguments))


def _skill_files(code: str, marker: str = "body") -> dict[str, str]:
    return {
        "SKILL.md": (
            f"---\nname: {code}\ndescription: MCP write fixture\n---\n\n"
            f"# {code}\n\n{marker}\n"
        ),
        "docs/note.txt": f"private file text: {marker}\n",
    }


def _zip_bytes(code: str, marker: str = "body") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in _skill_files(code, marker).items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _package(code: str, marker: str = "body") -> str:
    return base64.b64encode(_zip_bytes(code, marker)).decode("ascii")


def _workspace_snapshot(root) -> dict[str, bytes | None]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        snapshot[str(relative)] = None if path.is_dir() else path.read_bytes()
    return snapshot


async def _publish(client, code: str, **overrides):
    arguments = {
        "code": code,
        "name": f"Name {code}",
        "version": "1.0.0",
        "summary": f"Summary {code}",
        "files": _skill_files(code),
    }
    if "package_base64" in overrides:
        del arguments["files"]
    arguments.update(overrides)
    return await _call(client, OWNER_TOKEN, "skill_publish", **arguments)


async def _seed_asset(
    code: str,
    *,
    author: str = "mcp-write-owner",
    version: str = "1.0.0",
    publish_status: str = "published",
) -> Asset:
    asset = Asset(
        code=code,
        name=f"Original {code}",
        icon="S",
        kind="skill",
        version=version,
        summary=f"Original summary {code}",
        description="Original description",
        use_when="Original use",
        not_for="Original exclusion",
        category="misc",
        project="6100",
        tags=["original"],
        keywords=["keep"],
        permissions={"network": True},
        install_steps=["copy"],
        bindings={"agent": "qa"},
        author=author,
        featured=True,
        git_path=f"assets/skills/misc/{code}",
        publish_status=publish_status,
    )
    async with AsyncSessionLocal() as session:
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
    return asset


async def _asset(code: str) -> Asset:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Asset).where(Asset.code == code))
        asset = result.scalar_one()
        await session.refresh(asset)
        return asset


async def _market_counts() -> tuple[int, int, int]:
    async with AsyncSessionLocal() as session:
        return (
            await session.scalar(select(func.count()).select_from(Asset)),
            await session.scalar(select(func.count()).select_from(AssetJob)),
            await session.scalar(select(func.count()).select_from(AssetAudit)),
        )


async def _tool_audits(tool: str) -> list[McpToolCall]:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(McpToolCall).where(McpToolCall.tool == tool).order_by(McpToolCall.id)
        )
        return list(rows.scalars())


async def test_tools_list_exposes_exactly_fourteen_frozen_schemas(principals):
    async with _client(principals) as client:
        result = await list_tools(client, OWNER_TOKEN)

    tools = {tool["name"]: tool for tool in result["tools"]}
    assert set(tools) == TOOL_NAMES
    assert len(result["tools"]) == 14
    for name, (required, properties) in EXPECTED_SCHEMAS.items():
        schema = tools[name]["inputSchema"]
        assert schema["type"] == "object", name
        assert schema["additionalProperties"] is False, name
        assert schema["required"] == required, name
        assert set(schema["properties"]) == properties, name
        if "code" in properties:
            assert schema["properties"]["code"] == {
                "type": "string",
                "minLength": 3,
                "maxLength": 64,
            }, name

    search = tools["skill_search"]["inputSchema"]["properties"]
    assert search["page"]["minimum"] == 1
    assert search["page_size"]["minimum"] == 1
    assert search["page_size"]["maximum"] == 100
    assert tools["skill_read_file"]["inputSchema"]["properties"]["path"][
        "maxLength"
    ] == 1024
    assert tools["skill_job_status"]["inputSchema"]["properties"]["job_id"][
        "minimum"
    ] == 1

    package_choice = [
        {"required": ["files"], "not": {"required": ["package_base64"]}},
        {"required": ["package_base64"], "not": {"required": ["files"]}},
    ]
    for name in ("skill_publish", "skill_update"):
        schema = tools[name]["inputSchema"]
        assert schema["oneOf"] == package_choice, name
        assert schema["properties"]["files"] == {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {"type": "string"},
        }, name
        assert schema["properties"]["package_base64"] == {
            "type": "string",
            "minLength": 1,
            "contentEncoding": "base64",
        }, name
        assert schema["properties"]["version"] == {
            "type": "string",
            "minLength": 1,
            "maxLength": 32,
        }, name

    edit_schema = tools["skill_edit_meta"]["inputSchema"]
    assert "version" not in edit_schema["properties"]
    assert "featured" not in edit_schema["properties"]
    assert not _PACKAGE_PROPERTIES & edit_schema["properties"].keys()
    assert edit_schema["anyOf"] == [
        {"required": [field]} for field in sorted(_METADATA_PROPERTIES)
    ]


@pytest.mark.parametrize("missing", ["code", "name", "version", "summary"])
async def test_publish_missing_required_fields_have_no_side_effects(
    principals, notifications, missing
):
    arguments = {
        "code": "mcp-missing-required",
        "name": "Missing required",
        "version": "1.0.0",
        "summary": "Missing required",
        "files": _skill_files("mcp-missing-required"),
    }
    del arguments[missing]
    async with _client(principals) as client:
        result = await call_tool(client, OWNER_TOKEN, "skill_publish", arguments)

    assert _error(result) == "Invalid tool arguments."
    assert await _market_counts() == (0, 0, 0)
    assert notifications == []


@pytest.mark.parametrize(
    "package_arguments",
    [
        {},
        {"files": _skill_files("mcp-package-choice"), "package_base64": "eA=="},
        {"files": {}},
    ],
)
async def test_publish_requires_exactly_one_nonempty_package_source(
    principals, notifications, package_arguments
):
    arguments = {
        "code": "mcp-package-choice",
        "name": "Package choice",
        "version": "1.0.0",
        "summary": "Package choice",
        **package_arguments,
    }
    async with _client(principals) as client:
        result = await call_tool(client, OWNER_TOKEN, "skill_publish", arguments)

    assert _error(result) == "Invalid tool arguments."
    assert await _market_counts() == (0, 0, 0)
    assert notifications == []


@pytest.mark.parametrize("encoded", ["not base64!", "Zm\n9v"])
async def test_publish_rejects_non_strict_base64_before_side_effects(
    principals, notifications, encoded
):
    arguments = {
        "code": "mcp-invalid-base64",
        "name": "Invalid base64",
        "version": "1.0.0",
        "summary": "Invalid base64",
        "package_base64": encoded,
    }
    async with _client(principals) as client:
        result = await call_tool(client, OWNER_TOKEN, "skill_publish", arguments)

    assert _error(result) == "Tool request failed (HTTP 422)."
    assert await _market_counts() == (0, 0, 0)
    assert notifications == []


async def test_malformed_publish_archive_leaves_workspace_unchanged(
    principals, ws, restore_git_config, notifications
):
    before = _workspace_snapshot(ws)
    arguments = {
        "code": "mcp-malformed-publish",
        "name": "Malformed publish",
        "version": "1.0.0",
        "summary": "Malformed publish",
        "package_base64": base64.b64encode(b"not a zip archive").decode("ascii"),
    }

    async with _client(principals) as client:
        result = await call_tool(client, OWNER_TOKEN, "skill_publish", arguments)

    assert _error(result) == "Tool request failed (HTTP 422)."
    assert _workspace_snapshot(ws) == before
    assert await _market_counts() == (0, 0, 0)
    assert notifications == []


async def test_malformed_update_archive_leaves_workspace_unchanged(
    principals, ws, restore_git_config, notifications
):
    await _seed_asset("mcp-malformed-update")
    package_path = (
        ws
        / "assets/skills/misc/mcp-malformed-update/package/1.0.0.zip"
    )
    package_path.parent.mkdir(parents=True)
    package_path.write_bytes(b"original package bytes")
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed existing package"],
        cwd=ws,
        check=True,
        capture_output=True,
    )
    before = _workspace_snapshot(ws)
    arguments = {
        "code": "mcp-malformed-update",
        "version": "2.0.0",
        "package_base64": base64.b64encode(b"not a zip archive").decode("ascii"),
    }

    async with _client(principals) as client:
        result = await call_tool(client, OWNER_TOKEN, "skill_update", arguments)

    assert _error(result) == "Tool request failed (HTTP 422)."
    assert _workspace_snapshot(ws) == before
    assert package_path.read_bytes() == b"original package bytes"
    asset = await _asset("mcp-malformed-update")
    assert asset.version == "1.0.0"
    assert notifications == []


async def test_publish_rejects_oversized_decoded_package_before_side_effects(
    principals, notifications
):
    await set_setting("marketplace.max_package_mb", "1")
    arguments = {
        "code": "mcp-oversized-package",
        "name": "Oversized package",
        "version": "1.0.0",
        "summary": "Oversized package",
        "package_base64": base64.b64encode(b"x" * (1024 * 1024 + 1)).decode("ascii"),
    }
    async with _client(principals) as client:
        result = await call_tool(client, OWNER_TOKEN, "skill_publish", arguments)

    assert _error(result) == "Tool request failed (HTTP 413)."
    assert await _market_counts() == (0, 0, 0)
    assert notifications == []


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        ({"code": "mcp-update-negative"}, "Invalid tool arguments."),
        (
            {"code": "mcp-update-negative", "version": "2.0.0"},
            "Invalid tool arguments.",
        ),
        (
            {
                "code": "mcp-update-negative",
                "version": "2.0.0",
                "files": _skill_files("mcp-update-negative"),
                "package_base64": "eA==",
            },
            "Invalid tool arguments.",
        ),
        (
            {
                "code": "mcp-update-negative",
                "version": "1.0.0",
                "files": _skill_files("mcp-update-negative"),
            },
            "Tool request failed (HTTP 409).",
        ),
        (
            {
                "code": "mcp-update-negative",
                "version": "2.0.0",
                "package_base64": "invalid!",
            },
            "Tool request failed (HTTP 422).",
        ),
    ],
)
async def test_update_rejects_missing_package_version_same_version_and_bad_base64(
    principals, notifications, arguments, expected_error
):
    await _seed_asset("mcp-update-negative")
    before = await _market_counts()
    async with _client(principals) as client:
        result = await call_tool(client, OWNER_TOKEN, "skill_update", arguments)

    assert _error(result) == expected_error
    asset = await _asset("mcp-update-negative")
    assert asset.version == "1.0.0"
    assert asset.summary == "Original summary mcp-update-negative"
    assert await _market_counts() == before
    assert notifications == []


async def test_edit_meta_requires_an_editable_field_and_forbids_version_featured(
    principals, notifications
):
    await _seed_asset("mcp-edit-negative")
    before = await _market_counts()
    async with _client(principals) as client:
        empty = await call_tool(client, OWNER_TOKEN, "skill_edit_meta", {"code": "mcp-edit-negative"})
        version = await call_tool(
            client,
            OWNER_TOKEN,
            "skill_edit_meta",
            {"code": "mcp-edit-negative", "version": "2.0.0"},
        )
        featured = await call_tool(
            client,
            OWNER_TOKEN,
            "skill_edit_meta",
            {"code": "mcp-edit-negative", "featured": False},
        )

    assert _error(empty) == "Invalid tool arguments."
    assert _error(version) == "Invalid tool arguments."
    assert _error(featured) == "Invalid tool arguments."
    assert await _market_counts() == before
    assert notifications == []


def _write_arguments(tool: str) -> dict:
    if tool == "skill_publish":
        return {
            "code": "mcp-scope-publish",
            "name": "Scope",
            "version": "1.0.0",
            "summary": "Scope",
            "files": _skill_files("mcp-scope-publish"),
        }
    if tool == "skill_update":
        return {
            "code": "mcp-scope-update",
            "version": "2.0.0",
            "files": _skill_files("mcp-scope-update"),
        }
    if tool == "skill_edit_meta":
        return {"code": "mcp-scope-meta", "summary": "Scope"}
    if tool == "skill_submit_review":
        return {"code": "mcp-scope-submit"}
    return {"code": "mcp-scope-unpublish", "reason": "Scope"}


@pytest.mark.parametrize("tool", sorted(WRITE_TOOL_NAMES))
async def test_every_write_tool_requires_market_write_scope(
    principals, notifications, tool
):
    async with _client(principals) as client:
        result = await call_tool(client, READ_ONLY_TOKEN, tool, _write_arguments(tool))

    assert _error(result) == "Insufficient scope for this tool."
    assert await _market_counts() == (0, 0, 0)
    audits = await _tool_audits(tool)
    assert len(audits) == 1
    assert audits[0].read_only is False
    assert audits[0].success is False
    assert audits[0].error == "insufficient_scope"
    assert notifications == []


@pytest.mark.parametrize("tool", sorted(WRITE_TOOL_NAMES))
async def test_non_publisher_is_denied_before_every_write_route(
    principals, notifications, tool
):
    if tool != "skill_publish":
        await _seed_asset("mcp-non-publisher", author="mcp-write-viewer")
    before = await _market_counts()
    arguments = _write_arguments(tool)
    if tool != "skill_publish":
        arguments["code"] = "mcp-non-publisher"
    async with _client(principals) as client:
        result = await call_tool(client, NON_PUBLISHER_TOKEN, tool, arguments)

    assert _error(result) == "Tool request failed (HTTP 403)."
    assert await _market_counts() == before
    assert notifications == []


@pytest.mark.parametrize(
    "tool",
    ["skill_update", "skill_edit_meta", "skill_submit_review", "skill_unpublish_request"],
)
async def test_existing_object_level_authorization_still_denies_other_publishers(
    principals, notifications, tool
):
    await _seed_asset("mcp-object-auth", author="mcp-write-owner")
    before = await _market_counts()
    arguments = _write_arguments(tool)
    arguments["code"] = "mcp-object-auth"
    async with _client(principals) as client:
        result = await call_tool(client, OTHER_PUBLISHER_TOKEN, tool, arguments)

    assert _error(result) == "Tool request failed (HTTP 403)."
    assert await _market_counts() == before
    assert notifications == []


async def test_publish_files_presences_and_defaults_are_not_guessed(
    principals, ws, restore_git_config, notifications
):
    await set_setting("marketplace.review.enabled", "false")
    await set_setting(market_projects.SETTINGS_KEY, "6100,7000")
    async with _client(principals) as client:
        explicit = await _publish(
            client,
            "mcp-publish-explicit",
            description="Explicit description",
            use_when="Explicit use",
            not_for="Explicit exclusion",
            category="质量保障",
            project="6100",
            icon="W",
            tags=["confirmed"],
            keywords=["explicit"],
            featured=True,
            permissions={"network": False},
            install_steps=["copy", "restart"],
            bindings={"agent": "writer"},
        )
        minimal = await _publish(client, "mcp-publish-minimal")

    assert explicit["action"] == minimal["action"] == "create"
    assert explicit["status"] == minimal["status"] == "staged"
    asset = await _asset("mcp-publish-explicit")
    assert asset.publish_status == "published"
    assert asset.description == "Explicit description"
    assert asset.use_when == "Explicit use"
    assert asset.not_for == "Explicit exclusion"
    assert asset.category == "质量保障"
    assert asset.project == "6100"
    assert asset.icon == "W"
    assert asset.tags == ["confirmed"]
    assert asset.keywords == ["explicit"]
    assert bool(asset.featured) is True
    assert asset.permissions == {"network": False}
    assert asset.install_steps == ["copy", "restart"]
    assert asset.bindings == {"agent": "writer"}

    minimal_asset = await _asset("mcp-publish-minimal")
    assert minimal_asset.description == ""
    assert minimal_asset.use_when == ""
    assert minimal_asset.not_for == ""
    assert minimal_asset.category == "其他"
    assert minimal_asset.project == ""
    assert minimal_asset.tags == []
    assert minimal_asset.keywords == []
    assert bool(minimal_asset.featured) is False
    assert minimal_asset.permissions == {}
    assert minimal_asset.install_steps == []
    assert minimal_asset.bindings == {}
    assert [event for event, _, _ in notifications] == ["publish", "publish"]

    audits = await _tool_audits("skill_publish")
    assert len(audits) == 2
    assert audits[0].success is True and audits[0].read_only is False
    assert audits[0].args_summary["files"] == {
        "paths": ["SKILL.md", "docs/note.txt"],
        "count": 2,
    }
    assert "private file text" not in json.dumps(audits[0].args_summary)


async def test_publish_base64_returns_real_job_and_audits_only_package_metadata(
    principals, ws, restore_git_config, notifications
):
    await set_setting("marketplace.review.enabled", "false")
    package = _zip_bytes("mcp-publish-base64", "sensitive package body")
    encoded = base64.b64encode(package).decode("ascii")
    async with _client(principals) as client:
        result = await _call(
            client,
            OWNER_TOKEN,
            "skill_publish",
            code="mcp-publish-base64",
            name="Base64 publish",
            version="1.2.3",
            summary="Base64 publish",
            package_base64=encoded,
        )

    assert result["code"] == "mcp-publish-base64"
    assert result["action"] == "create"
    asset = await _asset("mcp-publish-base64")
    assert asset.version == "1.2.3"
    assert asset.publish_status == "published"
    package_path = ws / asset.git_path / "package" / "1.2.3.zip"
    assert package_path.read_bytes() == package
    assert [event for event, _, _ in notifications] == ["publish"]

    audit = (await _tool_audits("skill_publish"))[0]
    assert audit.success is True
    assert audit.args_summary["package_base64"] == {
        "bytes": len(package),
        "sha256": hashlib.sha256(package).hexdigest(),
    }
    stored = json.dumps(audit.args_summary)
    assert encoded not in stored
    assert "sensitive package body" not in stored


async def test_update_retains_every_omitted_metadata_field(
    principals, ws, restore_git_config, notifications
):
    await set_setting("marketplace.review.enabled", "false")
    await set_setting(market_projects.SETTINGS_KEY, "6100,7000")
    async with _client(principals) as client:
        await _publish(
            client,
            "mcp-update-retain",
            description="Keep description",
            use_when="Keep use",
            not_for="Keep exclusion",
            category="质量保障",
            project="6100",
            icon="K",
            tags=["keep"],
            keywords=["retain"],
            featured=True,
            permissions={"network": True},
            install_steps=["keep"],
            bindings={"agent": "keep"},
        )
        notifications.clear()
        result = await _call(
            client,
            OWNER_TOKEN,
            "skill_update",
            code="mcp-update-retain",
            version="2.0.0",
            summary="Only summary changes",
            package_base64=_package("mcp-update-retain", "version two"),
        )

    assert result["action"] == "update"
    asset = await _asset("mcp-update-retain")
    assert asset.version == "2.0.0"
    assert asset.summary == "Only summary changes"
    assert asset.name == "Name mcp-update-retain"
    assert asset.description == "Keep description"
    assert asset.use_when == "Keep use"
    assert asset.not_for == "Keep exclusion"
    assert asset.category == "质量保障"
    assert asset.project == "6100"
    assert asset.icon == "K"
    assert asset.tags == ["keep"]
    assert asset.keywords == ["retain"]
    assert bool(asset.featured) is True
    assert asset.permissions == {"network": True}
    assert asset.install_steps == ["keep"]
    assert asset.bindings == {"agent": "keep"}
    assert [event for event, _, _ in notifications] == ["update"]


async def test_edit_meta_changes_only_supplied_fields_and_preserves_package(
    principals, ws, restore_git_config, notifications
):
    await set_setting("marketplace.review.enabled", "false")
    original_package = _zip_bytes("mcp-edit-success")
    async with _client(principals) as client:
        await _publish(
            client,
            "mcp-edit-success",
            package_base64=base64.b64encode(original_package).decode("ascii"),
            description="Clear me",
            tags=["clear"],
            featured=True,
        )
        notifications.clear()
        await set_setting("marketplace.review.enabled", "true")
        result = await _call(
            client,
            OWNER_TOKEN,
            "skill_edit_meta",
            code="mcp-edit-success",
            summary="Edited summary",
            description="",
            tags=[],
        )

    assert result["code"] == "mcp-edit-success"
    assert result["status"] == "staged"
    asset = await _asset("mcp-edit-success")
    assert asset.version == "1.0.0"
    assert asset.name == "Name mcp-edit-success"
    assert asset.summary == "Edited summary"
    assert asset.description == ""
    assert asset.tags == []
    assert bool(asset.featured) is True
    assert asset.publish_status == "pending"
    assert asset.pending_action == "meta"
    package_path = ws / asset.git_path / "package" / "1.0.0.zip"
    assert package_path.read_bytes() == original_package
    assert [event for event, _, _ in notifications] == ["review"]


async def test_submit_review_uses_existing_state_machine_comment_and_audit(
    principals, ws, restore_git_config, notifications
):
    await set_setting("marketplace.review.enabled", "false")
    async with _client(principals) as client:
        await _publish(client, "mcp-submit-success")
        async with AsyncSessionLocal() as session:
            rejected = await session.scalar(
                select(Asset).where(Asset.code == "mcp-submit-success")
            )
            rejected.publish_status = "rejected"
            rejected.pending_action = "new"
            await session.commit()
        notifications.clear()
        result = await _call(
            client,
            OWNER_TOKEN,
            "skill_submit_review",
            code="mcp-submit-success",
            comment="Please review this exact comment",
        )

    assert result["code"] == "mcp-submit-success"
    assert result["publish_status"] == "pending"
    assert result["changed"] is True
    asset = await _asset("mcp-submit-success")
    assert asset.publish_status == "pending"
    assert asset.pending_action == "new"
    assert [event for event, _, _ in notifications] == ["review"]
    assert notifications[0][2]["detail"] == "Please review this exact comment"
    async with AsyncSessionLocal() as session:
        audit = await session.scalar(
            select(AssetAudit)
            .where(AssetAudit.code == "mcp-submit-success")
            .where(AssetAudit.action == "submit")
        )
    assert audit.comment == "Please review this exact comment"


@pytest.mark.parametrize(
    ("review_enabled", "expected_status", "expected_event", "expected_action"),
    [
        (True, "unpublish_pending", "unpublish_request", "unpublish_request"),
        (False, "unpublished", "unpublish", "take_down"),
    ],
)
async def test_unpublish_binds_confirmation_reason_and_preserves_review_switch(
    principals,
    ws,
    restore_git_config,
    notifications,
    review_enabled,
    expected_status,
    expected_event,
    expected_action,
):
    await set_setting("marketplace.review.enabled", "false")
    async with _client(principals) as client:
        await _publish(client, "mcp-unpublish-success")
        notifications.clear()
        await set_setting("marketplace.review.enabled", str(review_enabled).lower())
        result = await _call(
            client,
            OWNER_TOKEN,
            "skill_unpublish_request",
            code="mcp-unpublish-success",
            reason="Exact unpublish reason",
        )

    assert result["code"] == "mcp-unpublish-success"
    assert result["publish_status"] == expected_status
    assert result["needs_review"] is review_enabled
    assert result["changed"] is True
    asset = await _asset("mcp-unpublish-success")
    assert asset.publish_status == expected_status
    assert [event for event, _, _ in notifications] == [expected_event]
    assert "Exact unpublish reason" in notifications[0][2]["detail"]
    async with AsyncSessionLocal() as session:
        audit = await session.scalar(
            select(AssetAudit)
            .where(AssetAudit.code == "mcp-unpublish-success")
            .where(AssetAudit.action == expected_action)
        )
    assert audit.comment == "Exact unpublish reason"
