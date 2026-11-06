"""MCP OAuth DCR, in-memory authorization codes, grants, and JWT issuance."""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ext_policy
from app.core.config import settings
from app.core.dingtalk import get_request_base_url
from app.core.kb_policy import can_write_kb
from app.core.settings_store import get
from app.db.session import AsyncSessionLocal
from app.models.mcp import McpOAuthClient, McpOAuthGrant
from app.models.user import User

SUPPORTED_SCOPES = frozenset(
    {"extensions:read", "extensions:write", "kb:read", "kb:write"}
)
_SCOPE_ORDER = ("extensions:read", "extensions:write", "kb:read", "kb:write")
SCOPE_HINT = " ".join(_SCOPE_ORDER)
_LEGACY_SCOPES = {"market:read": "extensions:read", "market:write": "extensions:write"}
AUTHORIZATION_CODE_TTL_SECONDS = 300


def normalize_scope(scope: str) -> str:
    """Map pre-rename grants/scopes onto the current extensions namespace."""
    return _LEGACY_SCOPES.get(scope, scope)


class OAuthError(Exception):
    """OAuth protocol error safe to return through the future HTTP boundary."""

    def __init__(self, error: str, description: str):
        super().__init__(description)
        self.error = error
        self.description = description


async def resolve_public_base(public_base: str | None = None) -> str:
    """对外基地址: 显式参数 > extensions.public_base_url 设置 > 请求来源推断.

    与 marketplace.json 的「留空则用请求来源」保持一致; 元数据、签发、校验
    三处共用这一个解析, 保证 access token 的 aud 两边算出来是同一个值.
    """
    if public_base:
        return str(public_base).strip().rstrip("/")
    configured = (
        str(await get("extensions.public_base_url", "") or "").strip().rstrip("/")
    )
    if configured:
        return configured
    return get_request_base_url().strip().rstrip("/")


@dataclass(frozen=True, slots=True)
class _AuthorizationCode:
    client_id: str
    redirect_uri: str
    user_id: int
    scopes: tuple[str, ...]
    challenge: str
    expires_at: float


# Deployment intentionally uses one worker: codes must not survive a restart or be shared.
_AUTHORIZATION_CODES: dict[str, _AuthorizationCode] = {}


@asynccontextmanager
async def _session_scope(
    session: AsyncSession | None,
) -> AsyncIterator[AsyncSession]:
    if session is not None:
        yield session
        return
    async with AsyncSessionLocal() as owned:
        yield owned


def _is_loopback_redirect(uri: Any) -> bool:
    if not isinstance(uri, str) or not uri or uri != uri.strip():
        return False
    try:
        parsed = urlsplit(uri)
        # Accessing port also validates malformed values such as ':not-a-port'.
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _ordered_scopes(scopes: Sequence[str]) -> list[str]:
    requested = {normalize_scope(scope) for scope in scopes}
    return [scope for scope in _SCOPE_ORDER if scope in requested]


def _parse_scopes(raw: Any, *, default: Sequence[str] | None = None) -> list[str]:
    if raw is None:
        if default is None:
            raise OAuthError("invalid_scope", "缺少 scope")
        return _ordered_scopes(default)
    if isinstance(raw, str):
        values = raw.split()
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        if not all(isinstance(value, str) for value in raw):
            raise OAuthError("invalid_scope", "scope 格式错误")
        values = list(raw)
    else:
        raise OAuthError("invalid_scope", "scope 格式错误")
    if not values or any(scope not in SUPPORTED_SCOPES for scope in values):
        raise OAuthError("invalid_scope", f"scope 必须是 {SCOPE_HINT} 的非空子集")
    return _ordered_scopes(values)


async def register_client(
    metadata: Mapping[str, Any],
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Register a public authorization-code client with loopback redirects only."""
    if not isinstance(metadata, Mapping):
        raise OAuthError("invalid_client_metadata", "客户端元数据必须是对象")
    if metadata.get("token_endpoint_auth_method") != "none" or metadata.get(
        "client_secret"
    ) is not None:
        raise OAuthError("invalid_client_metadata", "MCP 仅支持无 client_secret 的 public client")
    grant_types = metadata.get("grant_types", ["authorization_code"])
    if (
        not isinstance(grant_types, Sequence)
        or isinstance(grant_types, (str, bytes, bytearray))
        or "authorization_code" not in grant_types
        or any(
            not isinstance(value, str)
            or value not in {"authorization_code", "refresh_token"}
            for value in grant_types
        )
    ):
        raise OAuthError("invalid_client_metadata", "仅支持 authorization_code grant")

    response_types = metadata.get("response_types", ["code"])
    if (
        not isinstance(response_types, Sequence)
        or isinstance(response_types, (str, bytes, bytearray))
        or list(response_types) != ["code"]
    ):
        raise OAuthError("invalid_client_metadata", "仅支持 code response")

    raw_redirects = metadata.get("redirect_uris")
    if not isinstance(raw_redirects, Sequence) or isinstance(
        raw_redirects, (str, bytes, bytearray)
    ) or not raw_redirects:
        raise OAuthError("invalid_redirect_uri", "至少需要一个回环 redirect URI")
    redirects = [str(uri) for uri in raw_redirects]
    if any(not _is_loopback_redirect(uri) for uri in redirects):
        raise OAuthError(
            "invalid_redirect_uri",
            "redirect URI 仅允许 http://127.0.0.1、http://localhost 或 http://[::1]",
        )

    scopes = _parse_scopes(metadata.get("scope"), default=_SCOPE_ORDER)
    client_id = secrets.token_urlsafe(24)
    client_name = str(metadata.get("client_name") or "MCP Client").strip()[:255]
    async with _session_scope(session) as db:
        db.add(
            McpOAuthClient(
                client_id=client_id,
                client_name=client_name or "MCP Client",
                redirect_uris=redirects,
                scopes=scopes,
            )
        )
        await db.commit()

    return {
        "client_id": client_id,
        "client_name": client_name or "MCP Client",
        "redirect_uris": redirects,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "scope": " ".join(scopes),
    }


async def validate_authorization(
    params: Mapping[str, Any],
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Validate and normalize an authorization request against the persisted client."""
    if not isinstance(params, Mapping):
        raise OAuthError("invalid_request", "授权参数必须是对象")
    client_id = params.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise OAuthError("invalid_request", "缺少 client_id")
    async with _session_scope(session) as db:
        client = await db.get(McpOAuthClient, client_id)
        if client is None:
            raise OAuthError("invalid_client", "未知 client_id")
        redirect_uri = params.get("redirect_uri")
        if redirect_uri not in client.redirect_uris:
            raise OAuthError("invalid_request", "redirect_uri 与客户端注册信息不匹配")
        raw_scope = params.get("scope", params.get("scopes"))
        scopes = _parse_scopes(raw_scope, default=client.scopes)
        if any(scope not in client.scopes for scope in scopes):
            raise OAuthError("invalid_scope", "请求 scope 超出客户端注册范围")
        client_name = client.client_name

    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "仅支持 response_type=code")
    if params.get("code_challenge_method") != "S256":
        raise OAuthError("invalid_request", "PKCE 仅支持 S256")
    challenge = params.get("code_challenge")
    if not isinstance(challenge, str) or not challenge:
        raise OAuthError("invalid_request", "缺少 PKCE code_challenge")
    state = params.get("state")
    if state is not None and not isinstance(state, str):
        raise OAuthError("invalid_request", "state 格式错误")
    return {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uri": str(redirect_uri),
        "scopes": scopes,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }


async def allowed_scopes(user: User) -> list[str]:
    """Return scopes allowed by the user's current state and role/policy."""
    if not getattr(user, "is_active", False):
        return []
    scopes = ["extensions:read"]
    if await ext_policy.can_publish(user):
        scopes.append("extensions:write")
    scopes.append("kb:read")
    if can_write_kb(user):
        scopes.append("kb:write")
    return scopes


async def create_authorization_code(
    params: Mapping[str, Any],
    user: User,
    session: AsyncSession | None = None,
) -> str:
    """Create a five-minute code bound to the request, user, scopes, and PKCE challenge."""
    validated = await validate_authorization(params, session)
    permitted = await allowed_scopes(user)
    if any(scope not in permitted for scope in validated["scopes"]):
        raise OAuthError("invalid_scope", "请求 scope 超出当前用户可授权范围")
    code = secrets.token_urlsafe(32)
    _AUTHORIZATION_CODES[code] = _AuthorizationCode(
        client_id=validated["client_id"],
        redirect_uri=validated["redirect_uri"],
        user_id=int(user.id),
        scopes=tuple(validated["scopes"]),
        challenge=validated["code_challenge"],
        expires_at=time.time() + AUTHORIZATION_CODE_TTL_SECONDS,
    )
    return code


async def issue_access_token(
    user: User,
    grant: McpOAuthGrant,
    public_base: str | None = None,
) -> str:
    """Issue an OAuth JWT with no exp; grant and user versions provide revocation."""
    base = await resolve_public_base(public_base)
    if not base:
        raise OAuthError(
            "invalid_request",
            "未配置 extensions.public_base_url 且无法从请求来源推断基地址",
        )
    payload = {
        "sub": str(user.id),
        "client_id": grant.client_id,
        "grant_id": int(grant.id),
        "grant_version": int(grant.version),
        "token_version": int(user.token_version),
        "scopes": _ordered_scopes(grant.scopes),
        "aud": f"{base}/mcp",
        "typ": "mcp-oauth",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def exchange_code(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    public_base: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, str]:
    """Consume a code once, enforce all bindings, persist its grant, and issue a token."""
    pending = _AUTHORIZATION_CODES.pop(code, None)
    if (
        pending is None
        or pending.expires_at <= time.time()
        or pending.client_id != client_id
        or pending.redirect_uri != redirect_uri
    ):
        raise OAuthError("invalid_grant", "授权码无效、已过期或绑定信息不匹配")
    try:
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise OAuthError("invalid_grant", "PKCE 校验失败") from exc
    if not secrets.compare_digest(expected, pending.challenge):
        raise OAuthError("invalid_grant", "PKCE 校验失败")

    async with _session_scope(session) as db:
        user = await db.get(User, pending.user_id)
        if user is None:
            raise OAuthError("invalid_grant", "授权用户不存在")
        permitted = await allowed_scopes(user)
        scopes = [scope for scope in pending.scopes if scope in permitted]
        if not scopes:
            raise OAuthError("invalid_grant", "用户当前无可授予 scope")

        upsert = mysql_insert(McpOAuthGrant).values(
            user_id=user.id,
            client_id=client_id,
            scopes=scopes,
            version=1,
            revoked_at=None,
        )
        upsert = upsert.on_duplicate_key_update(
            scopes=upsert.inserted.scopes,
            version=McpOAuthGrant.version + 1,
            revoked_at=None,
            updated_at=datetime.utcnow(),
        )
        await db.execute(upsert)
        grant = (
            await db.execute(
                select(McpOAuthGrant)
                .where(
                    McpOAuthGrant.user_id == user.id,
                    McpOAuthGrant.client_id == client_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        await db.commit()
        token = await issue_access_token(user, grant, public_base)

    return {
        "access_token": token,
        "token_type": "bearer",
        "scope": " ".join(scopes),
    }


async def revoke_token(
    token: str,
    session: AsyncSession | None = None,
) -> None:
    """Revoke the persisted grant targeted by a signed MCP OAuth token."""
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
    except (JWTError, TypeError, ValueError) as exc:
        raise OAuthError("invalid_grant", "access token 无效") from exc
    if claims.get("typ") != "mcp-oauth":
        raise OAuthError("invalid_grant", "access token 类型无效")
    try:
        grant_id = int(claims["grant_id"])
        user_id = int(claims["sub"])
        client_id = str(claims["client_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OAuthError("invalid_grant", "access token 缺少 grant 绑定") from exc

    async with _session_scope(session) as db:
        grant = await db.get(McpOAuthGrant, grant_id)
        if grant is None or grant.user_id != user_id or grant.client_id != client_id:
            raise OAuthError("invalid_grant", "access token 与 grant 不匹配")
        if grant.revoked_at is None:
            grant.revoked_at = datetime.utcnow()
            await db.commit()
