"""HTTP routes for MCP OAuth discovery, DCR, and authorization-code exchange."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.mcp.common.oauth import (
    SCOPE_ORDER,
    OAuthError,
    exchange_code,
    register_client,
    resolve_public_base,
    revoke_token,
    validate_authorization,
)

router = APIRouter()


def _error_response(exc: OAuthError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": exc.error, "error_description": exc.description},
    )


async def _form(request: Request) -> dict[str, Any]:
    try:
        return dict(await request.form())
    except Exception as exc:  # Form parsers expose several client-input error types.
        raise OAuthError("invalid_request", "请求表单格式错误") from exc


def _required(form: dict[str, Any], field: str) -> str:
    value = form.get(field)
    if not isinstance(value, str) or not value:
        raise OAuthError("invalid_request", f"缺少 {field}")
    return value


async def _public_base() -> str:
    return await resolve_public_base()


@router.post("/oauth/register", status_code=201)
async def register(request: Request):
    try:
        try:
            metadata = await request.json()
        except ValueError as exc:
            raise OAuthError("invalid_request", "请求 JSON 格式错误") from exc
        return await register_client(metadata)
    except OAuthError as exc:
        return _error_response(exc)


@router.get("/oauth/authorize")
async def authorize(request: Request):
    try:
        await validate_authorization(request.query_params)
    except OAuthError as exc:
        return _error_response(exc)
    query = request.url.query
    location = f"/connect/authorize?{query}" if query else "/connect/authorize"
    return RedirectResponse(location, status_code=302)


@router.post("/oauth/token")
async def token(request: Request):
    try:
        form = await _form(request)
        grant_type = _required(form, "grant_type")
        if grant_type != "authorization_code":
            raise OAuthError(
                "unsupported_grant_type", "仅支持 authorization_code grant"
            )
        return await exchange_code(
            code=_required(form, "code"),
            client_id=_required(form, "client_id"),
            redirect_uri=_required(form, "redirect_uri"),
            code_verifier=_required(form, "code_verifier"),
        )
    except OAuthError as exc:
        return _error_response(exc)


@router.post("/oauth/revoke")
async def revoke(request: Request):
    try:
        form = await _form(request)
        await revoke_token(_required(form, "token"))
        return {}
    except OAuthError as exc:
        return _error_response(exc)


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata():
    issuer = await _public_base()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "scopes_supported": list(SCOPE_ORDER),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
    }


@router.get("/.well-known/oauth-protected-resource/mcp/extensions")
async def protected_resource_metadata():
    issuer = await _public_base()
    return {
        "resource": f"{issuer}/mcp/extensions",
        "authorization_servers": [issuer],
        "scopes_supported": list(SCOPE_ORDER),
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-protected-resource/mcp/skill")
async def protected_resource_metadata_legacy():
    """Keep the pre-rename Qoder connector working against /mcp/skill."""
    issuer = await _public_base()
    return {
        "resource": f"{issuer}/mcp/skill",
        "authorization_servers": [issuer],
        "scopes_supported": list(SCOPE_ORDER),
        "bearer_methods_supported": ["header"],
    }
