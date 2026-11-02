"""Real Streamable HTTP contract tests for the nine read-only skill tools."""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken, TokenVerifier
from starlette.applications import Starlette
from starlette.routing import Mount

from app.core import git_sync, market_categories, market_projects
from app.db.session import AsyncSessionLocal
from app.mcp.common.context import Principal
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.skill.server import build_skill_server
from app.models.asset import Asset, AssetJob
from app.models.user import User, UserRole
from tests._mcp_protocol import call_tool, list_tools
from tests.conftest import set_setting

OWNER_TOKEN = "skill-read-owner-token"
ADMIN_TOKEN = "skill-read-admin-token"
OTHER_TOKEN = "skill-read-other-token"
NO_SCOPE_TOKEN = "skill-read-no-scope-token"
TOOL_NAMES = {
    "extension_search",
    "extension_get",
    "extension_read_doc",
    "extension_list_files",
    "extension_read_file",
    "extension_package_info",
    "extension_categories",
    "extension_projects",
    "extension_job_status",
}


class _FakeRedis:
    async def eval(self, script, numkeys, *args):
        return [1, "ok"]


class _ReadTokenVerifier(TokenVerifier):
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
            User(username="mcp-owner", password_hash="unused", role=UserRole.tester),
            User(username="mcp-admin", password_hash="unused", role=UserRole.admin),
            User(username="mcp-other", password_hash="unused", role=UserRole.viewer),
        ]
        session.add_all(users)
        await session.commit()
        for user in users:
            await session.refresh(user)
        owner, admin, other = users

    def principal(user: User, scopes=frozenset({"extensions:read"})) -> Principal:
        return Principal(user=user, client_id="skill-read-tests", scopes=scopes)

    return {
        OWNER_TOKEN: principal(owner),
        ADMIN_TOKEN: principal(admin),
        OTHER_TOKEN: principal(other),
        NO_SCOPE_TOKEN: principal(owner, frozenset()),
    }


@asynccontextmanager
async def _client(principals):
    server = build_skill_server(
        public_base_url="http://test",
        allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    server._token_verifier = _ReadTokenVerifier(principals)
    dispatcher = build_dispatcher({"extensions": server})
    app = Starlette(routes=[Mount("/mcp", app=dispatcher)])
    async with run_mcp_lifespan(dispatcher):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture
def asset_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "market-workspace"
    workspace.mkdir()
    monkeypatch.setattr(git_sync, "WORKSPACE", workspace)
    return workspace


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


async def _call(client, token, name, **arguments):
    return _data(await call_tool(client, token, name, arguments))


async def _seed_asset(
    code: str,
    *,
    author: str = "someone-else",
    publish_status: str = "published",
    version: str = "1.0.0",
    download_count: int = 0,
    tags: list[str] | None = None,
) -> Asset:
    asset = Asset(
        code=code,
        name=f"Name {code}",
        icon="S",
        kind="skill",
        version=version,
        summary=f"Summary {code}",
        description="Read tool fixture",
        category="质量保障",
        project="6100",
        tags=tags or ["read-tests"],
        keywords=[],
        permissions={"network": False},
        install_steps=["copy files", "restart"],
        bindings={"agent": "qa"},
        author=author,
        git_path=f"skills/{code}",
        publish_status=publish_status,
        download_count=download_count,
    )
    async with AsyncSessionLocal() as session:
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
    return asset


def _write_files(asset: Asset, files: dict[str, str | bytes]) -> None:
    root = git_sync.WORKSPACE / asset.git_path / "files"
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


def _write_package(asset: Asset, version: str, content: bytes) -> None:
    package_dir = git_sync.WORKSPACE / asset.git_path / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / f"{version}.zip").write_bytes(content)


async def test_tools_list_keeps_nine_accurate_read_schemas(principals):
    async with _client(principals) as client:
        result = await list_tools(client, OWNER_TOKEN)

    tools = {
        tool["name"]: tool for tool in result["tools"] if tool["name"] in TOOL_NAMES
    }
    assert set(tools) == TOOL_NAMES
    assert tools["extension_search"]["inputSchema"]["required"] == []
    assert tools["extension_get"]["inputSchema"]["required"] == ["code"]
    assert tools["extension_read_doc"]["inputSchema"]["required"] == ["code"]
    assert tools["extension_list_files"]["inputSchema"]["required"] == ["code"]
    assert tools["extension_read_file"]["inputSchema"]["required"] == ["code", "path"]
    assert tools["extension_package_info"]["inputSchema"]["required"] == ["code"]
    assert tools["extension_categories"]["inputSchema"]["additionalProperties"] is False
    assert tools["extension_projects"]["inputSchema"]["additionalProperties"] is False
    assert tools["extension_job_status"]["inputSchema"]["required"] == ["job_id"]
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools.values())


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("extension_search", {}),
        ("extension_get", {"code": "unused"}),
        ("extension_read_doc", {"code": "unused"}),
        ("extension_list_files", {"code": "unused"}),
        ("extension_read_file", {"code": "unused", "path": "SKILL.md"}),
        ("extension_package_info", {"code": "unused"}),
        ("extension_categories", {}),
        ("extension_projects", {}),
        ("extension_job_status", {"job_id": 1}),
    ],
)
async def test_every_read_tool_requires_market_read_scope(
    principals, tool_name, arguments
):
    async with _client(principals) as client:
        result = await call_tool(client, NO_SCOPE_TOKEN, tool_name, arguments)
    assert "Insufficient scope" in _error(result)


async def test_search_uses_published_default_and_unified_pagination(
    principals, asset_workspace
):
    for index, code in enumerate(("dml-read-a", "dml-read-b", "dml-read-c")):
        await _seed_asset(code, download_count=30 - index * 10)
    await _seed_asset("dml-owner-pending", author="mcp-owner", publish_status="pending")

    async with _client(principals) as client:
        first = await _call(
            client, OWNER_TOKEN, "extension_search", page=1, page_size=2
        )
        second = await _call(
            client, OWNER_TOKEN, "extension_search", page=2, page_size=2
        )
        included = await _call(
            client,
            OWNER_TOKEN,
            "extension_search",
            include_unpublished=True,
            page=1,
            page_size=20,
        )
        stranger = await _call(
            client,
            OTHER_TOKEN,
            "extension_search",
            include_unpublished=True,
            page=1,
            page_size=20,
        )

    assert [item["code"] for item in first["items"]] == ["dml-read-a", "dml-read-b"]
    assert [item["code"] for item in second["items"]] == ["dml-read-c"]
    assert first["total"] == second["total"] == 3
    assert first["page"] == 1 and first["page_size"] == 2
    assert second["page"] == 2 and second["page_size"] == 2
    assert "dml-owner-pending" in {item["code"] for item in included["items"]}
    assert "dml-owner-pending" not in {item["code"] for item in stranger["items"]}


async def test_search_tag_and_author_are_exact_filters(principals, asset_workspace):
    await _seed_asset("dml-tagged", tags=["wanted"], author="author-one")
    await _seed_asset("dml-not-tagged", tags=["other"], author="author-two")

    async with _client(principals) as client:
        tagged = await _call(
            client, OTHER_TOKEN, "extension_search", tag="wanted", page=1, page_size=20
        )
        authored = await _call(
            client,
            OTHER_TOKEN,
            "extension_search",
            author="author-two",
            page=1,
            page_size=20,
        )

    assert [item["code"] for item in tagged["items"]] == ["dml-tagged"]
    assert tagged["total"] == 1
    assert [item["code"] for item in authored["items"]] == ["dml-not-tagged"]
    assert authored["total"] == 1


async def test_invisible_and_missing_assets_have_identical_safe_not_found(
    principals, asset_workspace
):
    await _seed_asset(
        "dml-private-pending", author="mcp-owner", publish_status="pending"
    )

    async with _client(principals) as client:
        invisible = await call_tool(
            client, OTHER_TOKEN, "extension_get", {"code": "dml-private-pending"}
        )
        missing = await call_tool(
            client, OTHER_TOKEN, "extension_get", {"code": "dml-does-not-exist"}
        )
        owner = await _call(
            client, OWNER_TOKEN, "extension_get", code="dml-private-pending"
        )

    assert _error(invisible) == _error(missing) == "Tool request failed (HTTP 404)."
    assert owner["code"] == "dml-private-pending"


async def test_get_doc_files_and_exact_text_file_use_existing_market_data(
    principals, asset_workspace
):
    asset = await _seed_asset("dml-read-files")
    _write_files(
        asset,
        {
            "SKILL.md": "---\nname: read-files\ndescription: fixture\n---\n\n# Read me\n",
            "docs/note.txt": "exact nested text\n",
            "image.bin": b"\xff\xfe\x00binary",
        },
    )

    async with _client(principals) as client:
        detail = await _call(client, ADMIN_TOKEN, "extension_get", code=asset.code)
        doc = await _call(client, OTHER_TOKEN, "extension_read_doc", code=asset.code)
        files = await _call(client, OTHER_TOKEN, "extension_list_files", code=asset.code)
        text = await _call(
            client,
            OTHER_TOKEN,
            "extension_read_file",
            code=asset.code,
            path="docs/note.txt",
        )

    assert detail["code"] == asset.code
    assert detail["install_steps"] == ["copy files", "restart"]
    assert detail["permissions"] == {"network": False}
    assert detail["bindings"] == {"agent": "qa"}
    assert detail["can_review"] is True
    assert doc["filename"] == "SKILL.md"
    assert doc["frontmatter"]["name"] == "read-files"
    assert doc["content"] == "\n# Read me"
    assert {node["path"] for node in files["files"]} == {
        "SKILL.md",
        "docs",
        "docs/note.txt",
        "image.bin",
    }
    assert text == {
        "code": asset.code,
        "version": "1.0.0",
        "path": "docs/note.txt",
        "encoding": "text",
        "content": "exact nested text\n",
    }


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/etc/passwd", 400),
        ("../secret.txt", 400),
        ("docs/../../secret.txt", 400),
        ("C:\\secret.txt", 400),
        ("docs/missing.txt", 404),
        ("note.txt", 404),
        ("image.bin", 422),
    ],
)
async def test_read_file_rejects_traversal_absolute_missing_and_binary(
    principals, asset_workspace, path, status
):
    asset = await _seed_asset("dml-read-rejections")
    _write_files(
        asset,
        {"docs/note.txt": "text\n", "image.bin": b"\xff\xfe\x00binary"},
    )

    async with _client(principals) as client:
        result = await call_tool(
            client,
            OTHER_TOKEN,
            "extension_read_file",
            {"code": asset.code, "path": path},
        )

    assert _error(result) == f"Tool request failed (HTTP {status})."


async def test_read_file_rejects_valid_utf8_binary_but_preserves_unicode_text(
    principals, asset_workspace
):
    asset = await _seed_asset("dml-read-utf8-binary")
    unicode_text = "你好，世界 🌍\n\t缩进\r\n下一行\n"
    _write_files(
        asset,
        {
            "valid-utf8.bin": b"PK\x00\x01\x02valid UTF-8: \xe4\xbd\xa0\xe5\xa5\xbd",
            "unicode.txt": unicode_text,
        },
    )

    async with _client(principals) as client:
        binary = await call_tool(
            client,
            OTHER_TOKEN,
            "extension_read_file",
            {"code": asset.code, "path": "valid-utf8.bin"},
        )
        text = await _call(
            client, OTHER_TOKEN, "extension_read_file", code=asset.code, path="unicode.txt"
        )

    assert _error(binary) == "Tool request failed (HTTP 422)."
    assert text["content"] == unicode_text


async def test_package_info_hashes_real_bytes_and_never_falls_back_to_another_version(
    principals, asset_workspace
):
    await set_setting(
        "extensions.public_base_url", "https://public.example.test:8443/"
    )
    asset = await _seed_asset("dml-package-info", version="2.0.0")
    package_bytes = b"actual package bytes for version one\x00\xff"
    _write_package(asset, "1.0.0", package_bytes)
    outside_package = git_sync.WORKSPACE / asset.git_path / "outside.zip"
    outside_package.write_bytes(b"outside the package directory")

    async with _client(principals) as client:
        info = await _call(
            client,
            OTHER_TOKEN,
            "extension_package_info",
            code=asset.code,
            version="1.0.0",
        )
        current_missing = await call_tool(
            client, OTHER_TOKEN, "extension_package_info", {"code": asset.code}
        )
        explicit_missing = await call_tool(
            client,
            OTHER_TOKEN,
            "extension_package_info",
            {"code": asset.code, "version": "3.0.0"},
        )
        traversal = await call_tool(
            client,
            OTHER_TOKEN,
            "extension_package_info",
            {"code": asset.code, "version": "../outside"},
        )

    download_url = info.pop("download_url")
    assert info == {
        "code": asset.code,
        "version": "1.0.0",
        "filename": "1.0.0.zip",
        "size_bytes": len(package_bytes),
        "sha256": hashlib.sha256(package_bytes).hexdigest(),
    }
    assert download_url.startswith(
        "https://public.example.test:8443"
        f"/api/v1/extensions/{asset.code}/versions/1.0.0/ticket-download?ticket="
    )
    assert _error(current_missing) == "Tool request failed (HTTP 404)."
    assert _error(explicit_missing) == "Tool request failed (HTTP 404)."
    assert _error(traversal) == "Tool request failed (HTTP 404)."


async def test_package_info_rejects_package_symlink_to_outside_target(
    principals, asset_workspace
):
    asset = await _seed_asset("dml-package-symlink", version="1.0.0")
    package_dir = git_sync.WORKSPACE / asset.git_path / "package"
    package_dir.mkdir(parents=True)
    outside = git_sync.WORKSPACE / "outside-package.zip"
    outside.write_bytes(b"outside target must not be hashed")
    (package_dir / "1.0.0.zip").symlink_to(outside)

    async with _client(principals) as client:
        result = await call_tool(
            client,
            OTHER_TOKEN,
            "extension_package_info",
            {"code": asset.code, "version": "1.0.0"},
        )

    assert _error(result) == "Tool request failed (HTTP 404)."


async def test_categories_and_projects_come_from_current_single_rule_source(principals):
    await set_setting(market_projects.SETTINGS_KEY, "7000, 7100")

    async with _client(principals) as client:
        categories = await _call(client, OTHER_TOKEN, "extension_categories")
        projects = await _call(client, OTHER_TOKEN, "extension_projects")

    assert categories == {"items": market_categories.table()}
    assert projects == {"items": ["7000", "7100"]}


@pytest.mark.parametrize("status", ["staged", "syncing", "pushed", "failed"])
async def test_job_status_exposes_real_state_to_owner_and_admin_only(
    principals, asset_workspace, status
):
    owner_id = principals[OWNER_TOKEN].user.id
    async with AsyncSessionLocal() as session:
        job = AssetJob(
            action="create",
            status=status,
            code="dml-job-state",
            asset_name="Job state",
            kind="skill",
            payload={"secret": "must not be returned"},
            created_by=owner_id,
            error="sync failed" if status == "failed" else "",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    async with _client(principals) as client:
        owned = await _call(client, OWNER_TOKEN, "extension_job_status", job_id=job_id)
        administered = await _call(
            client, ADMIN_TOKEN, "extension_job_status", job_id=job_id
        )
        denied = await call_tool(
            client, OTHER_TOKEN, "extension_job_status", {"job_id": job_id}
        )

    assert owned["id"] == job_id and owned["status"] == status
    assert administered["id"] == job_id and administered["status"] == status
    assert owned["error"] == ("sync failed" if status == "failed" else "")
    assert "payload" not in owned
    assert _error(denied) == "Tool request failed (HTTP 403)."
