"""Strict-version asset download tickets over real MCP and HTTP transports."""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from urllib.parse import parse_qs, quote, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from starlette.applications import Starlette
from starlette.routing import Mount

from app.core import git_sync
from app.core.config import settings
from app.core.security import decode_token
from app.db.session import AsyncSessionLocal
from app.mcp.common.context import Principal
from app.mcp.common.server import build_dispatcher, run_mcp_lifespan
from app.mcp.skill.server import build_skill_server
from app.models.asset import Asset
from app.models.user import User, UserRole
from tests._mcp_protocol import call_tool
from tests.conftest import set_setting

OWNER_TOKEN = "asset-download-owner-token"
OTHER_TOKEN = "asset-download-other-token"
PUBLIC_BASE = "https://public.example.test:8443/"


class _FakeRedis:
    async def eval(self, script, numkeys, *args):
        return [1, "ok"]


class _DownloadTokenVerifier(TokenVerifier):
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


@pytest.fixture(autouse=True)
async def _public_base_url():
    await set_setting("extensions.public_base_url", PUBLIC_BASE)


@pytest.fixture
async def principals():
    async with AsyncSessionLocal() as session:
        owner = User(
            username="asset-download-owner",
            password_hash="unused",
            role=UserRole.tester,
        )
        other = User(
            username="asset-download-other",
            password_hash="unused",
            role=UserRole.viewer,
        )
        session.add_all([owner, other])
        await session.commit()
        await session.refresh(owner)
        await session.refresh(other)

    return {
        OWNER_TOKEN: Principal(
            user=owner, client_id="asset-download-tests", scopes=frozenset({"extensions:read"})
        ),
        OTHER_TOKEN: Principal(
            user=other, client_id="asset-download-tests", scopes=frozenset({"extensions:read"})
        ),
    }


@asynccontextmanager
async def _mcp_client(principals):
    server = build_skill_server(
        public_base_url="http://test",
        allowed_hosts=["test"],
        redis_client=_FakeRedis(),
    )
    server._token_verifier = _DownloadTokenVerifier(principals)
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


async def _seed_asset(
    code: str,
    *,
    author: str = "asset-download-owner",
    publish_status: str = "published",
    version: str = "2.0.0",
) -> Asset:
    asset = Asset(
        code=code,
        name=f"Name {code}",
        icon="S",
        kind="skill",
        version=version,
        summary=f"Summary {code}",
        description="Asset download fixture",
        category="质量保障",
        project="6100",
        tags=["download-tests"],
        keywords=[],
        permissions={"network": False},
        install_steps=["copy files"],
        bindings={},
        author=author,
        git_path=f"skills/{code}",
        publish_status=publish_status,
        download_count=0,
    )
    async with AsyncSessionLocal() as session:
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
    return asset


def _write_package(asset: Asset, version: str, content: bytes) -> None:
    package_dir = git_sync.WORKSPACE / asset.git_path / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / f"{version}.zip").write_bytes(content)


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


async def _package_info(client, token: str, code: str, version: str | None = None):
    arguments = {"code": code}
    if version is not None:
        arguments["version"] = version
    return _data(await call_tool(client, token, "extension_package_info", arguments))


def _asset_ticket(
    *,
    user_id: int,
    code: str,
    version: str,
    ttl_seconds: int = 600,
    typ: str = "asset-dl",
    include_exp: bool = True,
) -> str:
    claims = {
        "typ": typ,
        "uid": user_id,
        "code": code,
        "ver": version,
    }
    if include_exp:
        claims["exp"] = datetime.utcnow() + timedelta(seconds=ttl_seconds)
    return jwt.encode(
        claims,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


async def _exchange(client, code: str, version: str, ticket: str):
    return await client.get(
        f"/api/v1/extensions/{quote(code, safe='')}/versions/{quote(version, safe='')}/ticket-download",
        params={"ticket": ticket},
    )


@pytest.mark.parametrize(
    ("requested_version", "selected_version"),
    [(None, "2.0.0"), ("1.0.0", "1.0.0")],
)
async def test_package_info_ticket_downloads_exact_selected_bytes(
    principals, asset_workspace, client, requested_version, selected_version
):
    asset = await _seed_asset("dml-ticket-roundtrip")
    package_bytes = {
        "1.0.0": b"requested version one bytes\x00\xff",
        "2.0.0": b"current version two bytes\x00\xfe",
    }
    for version, content in package_bytes.items():
        _write_package(asset, version, content)

    async with _mcp_client(principals) as mcp:
        info = await _package_info(mcp, OTHER_TOKEN, asset.code, requested_version)

    expected = package_bytes[selected_version]
    assert info["code"] == asset.code
    assert info["version"] == selected_version
    assert info["filename"] == f"{selected_version}.zip"
    assert info["size_bytes"] == len(expected)
    assert info["sha256"] == hashlib.sha256(expected).hexdigest()

    parsed = urlparse(info["download_url"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "public.example.test:8443"
    assert parsed.path == (
        f"/api/v1/extensions/{asset.code}/versions/{selected_version}/ticket-download"
    )
    assert "//" not in parsed.path
    ticket = parse_qs(parsed.query)["ticket"][0]
    claims = decode_token(ticket)
    assert claims["typ"] == "asset-dl"
    assert claims["uid"] == principals[OTHER_TOKEN].user.id
    assert claims["code"] == asset.code
    assert claims["ver"] == selected_version
    assert 590 <= claims["exp"] - int(time.time()) <= 600

    response = await client.get(info["download_url"])
    assert response.status_code == 200, response.text
    assert response.content == expected
    assert hashlib.sha256(response.content).hexdigest() == info["sha256"]
    assert response.headers["x-content-sha256"] == info["sha256"]


async def test_ticket_exchange_rejects_wrong_code_version_type_and_expiry(
    principals, asset_workspace, client
):
    asset = await _seed_asset("dml-ticket-claims")
    _write_package(asset, "2.0.0", b"bound package")
    user_id = principals[OTHER_TOKEN].user.id
    valid = _asset_ticket(user_id=user_id, code=asset.code, version="2.0.0")

    wrong_code = await _exchange(client, "dml-other-code", "2.0.0", valid)
    wrong_version = await _exchange(client, asset.code, "1.0.0", valid)
    wrong_type = await _exchange(
        client,
        asset.code,
        "2.0.0",
        _asset_ticket(user_id=user_id, code=asset.code, version="2.0.0", typ="sw-dl"),
    )
    expired = await _exchange(
        client,
        asset.code,
        "2.0.0",
        _asset_ticket(
            user_id=user_id, code=asset.code, version="2.0.0", ttl_seconds=-1
        ),
    )
    no_expiry = await _exchange(
        client,
        asset.code,
        "2.0.0",
        _asset_ticket(
            user_id=user_id, code=asset.code, version="2.0.0", include_exp=False
        ),
    )

    assert wrong_code.status_code == 403
    assert wrong_version.status_code == 403
    assert wrong_type.status_code == 401
    assert expired.status_code == 401
    assert no_expiry.status_code == 401


async def test_ticket_exchange_rechecks_visibility_without_bypass(
    principals, asset_workspace, client
):
    asset = await _seed_asset("dml-ticket-visibility")
    _write_package(asset, "2.0.0", b"visibility bound package")
    async with _mcp_client(principals) as mcp:
        info = await _package_info(mcp, OTHER_TOKEN, asset.code)

    async with AsyncSessionLocal() as session:
        stored = await session.get(Asset, asset.id)
        stored.publish_status = "unpublished"
        await session.commit()

    response = await client.get(info["download_url"])
    assert response.status_code == 404

    async with _mcp_client(principals) as mcp:
        invisible = await call_tool(
            mcp, OTHER_TOKEN, "extension_package_info", {"code": asset.code}
        )
    assert _error(invisible) == "Tool request failed (HTTP 404)."


async def test_ticket_exchange_requires_ticket_and_active_bound_user(
    principals, asset_workspace, client
):
    asset = await _seed_asset("dml-ticket-user")
    _write_package(asset, "2.0.0", b"user bound package")
    user_id = principals[OTHER_TOKEN].user.id
    ticket = _asset_ticket(user_id=user_id, code=asset.code, version="2.0.0")

    anonymous = await client.get(
        f"/api/v1/extensions/{asset.code}/versions/2.0.0/ticket-download"
    )
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        user.is_active = False
        await session.commit()
    deactivated = await _exchange(client, asset.code, "2.0.0", ticket)

    assert anonymous.status_code == 401
    assert deactivated.status_code == 401


async def test_ticket_exchange_never_falls_back_to_another_version(
    principals, asset_workspace, client
):
    asset = await _seed_asset("dml-ticket-strict")
    package_bytes = b"only version one exists"
    _write_package(asset, "1.0.0", package_bytes)
    user_id = principals[OTHER_TOKEN].user.id

    exact = await _exchange(
        client,
        asset.code,
        "1.0.0",
        _asset_ticket(user_id=user_id, code=asset.code, version="1.0.0"),
    )
    missing = await _exchange(
        client,
        asset.code,
        "2.0.0",
        _asset_ticket(user_id=user_id, code=asset.code, version="2.0.0"),
    )

    assert exact.status_code == 200
    assert exact.content == package_bytes
    assert missing.status_code == 404


async def test_ticket_exchange_rejects_package_symlink_to_outside_storage(
    principals, asset_workspace, client
):
    safe = await _seed_asset("dml-ticket-safe-package")
    _write_package(safe, "2.0.0", b"safe package")
    linked = await _seed_asset("dml-ticket-linked-package")
    package_dir = git_sync.WORKSPACE / linked.git_path / "package"
    package_dir.mkdir(parents=True)
    outside = git_sync.WORKSPACE / "outside-package.zip"
    outside.write_bytes(b"outside target must not be served")
    (package_dir / "2.0.0.zip").symlink_to(outside)
    user_id = principals[OTHER_TOKEN].user.id

    safe_response = await _exchange(
        client,
        safe.code,
        "2.0.0",
        _asset_ticket(user_id=user_id, code=safe.code, version="2.0.0"),
    )
    linked_response = await _exchange(
        client,
        linked.code,
        "2.0.0",
        _asset_ticket(user_id=user_id, code=linked.code, version="2.0.0"),
    )

    assert safe_response.status_code == 200
    assert linked_response.status_code == 404


async def test_package_info_rejects_symlinked_package_directory(
    principals, asset_workspace
):
    asset = await _seed_asset("dml-package-dir-symlink")
    asset_dir = git_sync.WORKSPACE / asset.git_path
    real_package_dir = asset_dir / "real-package"
    real_package_dir.mkdir(parents=True)
    (real_package_dir / "2.0.0.zip").write_bytes(b"outside package directory")
    (asset_dir / "package").symlink_to(real_package_dir, target_is_directory=True)

    async with _mcp_client(principals) as mcp:
        result = await call_tool(
            mcp, OTHER_TOKEN, "extension_package_info", {"code": asset.code}
        )

    assert _error(result) == "Tool request failed (HTTP 404)."


async def test_ticket_download_content_disposition_preserves_unsafe_filename_safely(
    principals, asset_workspace, client
):
    asset = await _seed_asset("dml-ticket-unsafe-filename")
    version = '2.0.0" 包\r\nX-Evil'
    filename = f"{version}.zip"
    _write_package(asset, version, b"unsafe filename package")
    ticket = _asset_ticket(
        user_id=principals[OTHER_TOKEN].user.id,
        code=asset.code,
        version=version,
    )

    try:
        response = await _exchange(client, asset.code, version, ticket)
    except UnicodeEncodeError as exc:
        pytest.fail(f"non-Latin-1 filename broke ticket download: {exc}")

    assert response.status_code == 200, response.text
    assert response.content == b"unsafe filename package"
    disposition = response.headers["content-disposition"]
    disposition.encode("ascii")
    assert disposition == (
        'attachment; filename="2.0.0_ __X-Evil.zip"; '
        "filename*=UTF-8''2.0.0%22%20%E5%8C%85%0D%0AX-Evil.zip"
    )
    assert filename not in disposition
