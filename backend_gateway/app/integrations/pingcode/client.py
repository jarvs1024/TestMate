"""PingCode 账号登录客户端 (服务端).

已验证契约 (2026-11-12):
- 登录: POST /api/typhon/team/signin, 密码传 md5(明文).
- 响应: data.value.access_token (JWT, 无 exp) + Set-Cookie s-<team_id> (~2h).
- 业务错误常为 HTTP 200 + JSON code=401/403, 必须按 JSON code 判定.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.core.config import settings

LOGIN_PATH = "/api/typhon/team/signin"
REFRESH_PATH = "/api/typhon/account/access-token"
IDENTITY_PATH = "/api/typhon/account/me"
PROLONG_PATH = "/api/typhon/passport/prolong-logged-state"
SESSION_MINUTES = 90
DEFAULT_TIMEOUT = 30.0
_AUTH_CODES = {401, 403}
OK_CODES = {0, 200}


class PingCodeError(Exception):
    """PingCode 集成错误基类; message 可直接给用户看."""


class PingCodeAuthError(PingCodeError):
    """账号/密码错误或账号不可用."""


class PingCodeUnavailable(PingCodeError):
    """网络不可达、超时或上游响应异常."""


class PingCodeSessionExpired(PingCodeError):
    """业务请求判定登录态失效, 需要刷新后重试."""


class PingCodeBusinessError(PingCodeError):
    """上游业务错误; 带 HTTP 状态与业务 code 供调用方区分处理."""

    def __init__(self, message: str, *, status: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class PingCodeSession:
    access_token: str
    team_id: str
    display_name: str
    team_name: str
    cookies: dict[str, str]
    access_token_expires_at: datetime


def _password_md5(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def _pick(value: dict, *keys: str) -> str:
    for key in keys:
        item = value.get(key)
        if item:
            return str(item)
    return ""


async def signin(
    username: str,
    password: str,
    *,
    base_url: str | None = None,
    timeout: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PingCodeSession:
    base = (base_url or settings.PINGCODE_BASE_URL).rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=timeout,
            transport=transport,
            trust_env=False,
        ) as client:
            response = await client.post(
                LOGIN_PATH,
                json={
                    "signin_name": username,
                    "password": _password_md5(password),
                    "captcha_code": "",
                    "captcha_id": "",
                },
            )
    except httpx.HTTPError as exc:
        raise PingCodeUnavailable("PingCode 不可达，请稍后再试") from exc

    if response.status_code < 500 and response.status_code >= 400:
        raise PingCodeAuthError("账号或密码错误")
    if response.status_code >= 500:
        raise PingCodeUnavailable(f"PingCode 返回 HTTP {response.status_code}")

    try:
        body = response.json()
    except ValueError as exc:
        raise PingCodeUnavailable("PingCode 登录响应格式异常") from exc
    if not isinstance(body, dict):
        raise PingCodeUnavailable("PingCode 登录响应格式异常")

    code = body.get("code")
    if isinstance(code, int) and code in _AUTH_CODES:
        raise PingCodeAuthError("账号或密码错误")
    if isinstance(code, int) and code not in OK_CODES:
        raise PingCodeUnavailable("PingCode 登录失败，请稍后再试")

    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    value = data.get("value") if isinstance(data.get("value"), dict) else data
    token = _pick(value, "access_token", "accessToken", "token")
    if not token:
        raise PingCodeUnavailable("PingCode 登录响应缺少 access_token")

    team = value.get("team") if isinstance(value.get("team"), dict) else {}
    user_info = value.get("user") if isinstance(value.get("user"), dict) else {}
    team_id = _pick(team, "_id", "id") or _pick(value, "team_id", "teamId")
    display_name = (
        _pick(user_info, "name", "display_name", "nickname")
        or _pick(value, "display_name", "name")
        or username
    )
    cookies = {cookie.name: cookie.value for cookie in response.cookies.jar}
    return PingCodeSession(
        access_token=token,
        team_id=team_id or settings.PINGCODE_TEAM_ID,
        display_name=display_name,
        team_name=_pick(team, "name"),
        cookies=cookies,
        access_token_expires_at=datetime.utcnow() + timedelta(minutes=SESSION_MINUTES),
    )


async def fetch_display_name(
    session: PingCodeSession,
    *,
    base_url: str | None = None,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """登录响应只有账号名 (如 642355511), 中文名要从 /account/me 补.

    只用于界面展示, 拿不到就返回空串, 不阻断登录/测试连接.
    """
    base = (base_url or settings.PINGCODE_BASE_URL).rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=timeout,
            transport=transport,
            cookies=session.cookies or None,
            trust_env=False,
        ) as client:
            response = await client.get(
                IDENTITY_PATH,
                headers={"Authorization": f"Bearer {session.access_token}"},
            )
            if response.status_code >= 400:
                return ""
            body = response.json()
    except (httpx.HTTPError, ValueError):
        return ""
    record = body.get("data") if isinstance(body, dict) else None
    if not isinstance(record, dict):
        record = body if isinstance(body, dict) else {}
    me = record.get("me") if isinstance(record.get("me"), dict) else record
    return _pick(me, "display_name", "name")


def _token_of(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _pick(value, "access_token", "accessToken", "token")
    return ""


async def refresh_access_token(
    cookies: dict[str, str],
    *,
    base_url: str | None = None,
    timeout: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, dict[str, str]]:
    """用会话 cookie 换新 JWT; 返回新 token 与合并后的 cookie."""
    base = (base_url or settings.PINGCODE_BASE_URL).rstrip("/")
    merged = dict(cookies)
    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=timeout,
            transport=transport,
            cookies=cookies or None,
            trust_env=False,
        ) as client:
            response = await client.get(REFRESH_PATH)
    except httpx.HTTPError as exc:
        raise PingCodeUnavailable("PingCode 不可达，请稍后再试") from exc

    if response.status_code in _AUTH_CODES:
        raise PingCodeAuthError("登录态已失效")
    if response.status_code >= 500:
        raise PingCodeUnavailable(f"PingCode 返回 HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise PingCodeUnavailable("PingCode 刷新响应格式异常") from exc
    if not isinstance(body, dict):
        raise PingCodeUnavailable("PingCode 刷新响应格式异常")
    code = body.get("code")
    if isinstance(code, int) and code in _AUTH_CODES:
        raise PingCodeAuthError("登录态已失效")
    if isinstance(code, int) and code not in OK_CODES:
        raise PingCodeUnavailable("PingCode 刷新登录态失败")

    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    token = _token_of(data.get("value")) or _token_of(data) or _token_of(body)
    if not token:
        raise PingCodeUnavailable("PingCode 刷新响应缺少 access_token")
    merged.update({cookie.name: cookie.value for cookie in response.cookies.jar})
    return token, merged


async def prolong_logged_state(
    cookies: dict[str, str],
    *,
    base_url: str | None = None,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """延长会话有效期; 失败只影响会话寿命, 调用方应忽略异常."""
    base = (base_url or settings.PINGCODE_BASE_URL).rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=timeout,
            transport=transport,
            cookies=cookies or None,
            trust_env=False,
        ) as client:
            await client.post(PROLONG_PATH, json={})
    except httpx.HTTPError as exc:
        raise PingCodeUnavailable("PingCode 续期请求失败") from exc


def _error_message(body: Any, response: httpx.Response) -> str:
    if isinstance(body, dict):
        for key in ("message", "msg", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
    text = (response.text or "").strip()
    return text[:300] or f"PingCode 返回 HTTP {response.status_code}"


class PingCodeClient:
    """带 Bearer + X-Team-Id + cookie 的业务请求客户端."""

    def __init__(
        self,
        session: PingCodeSession,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.session = session
        self.base_url = (base_url or settings.PINGCODE_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._transport = transport

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> Any:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.session.access_token}",
            "X-Team-Id": self.session.team_id,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout or self.timeout,
                headers=headers,
                cookies=self.session.cookies or None,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise PingCodeUnavailable("PingCode 不可达，请稍后再试") from exc

        return self._decode(response)

    async def upload_file(
        self,
        path: str,
        *,
        token: str,
        scope: int,
        filename: str,
        content: bytes,
        content_type: str,
        timeout: float | None = None,
    ) -> Any:
        """multipart 上传到 atlas; 依赖 cookie 会话与 upload-token, 不发送 JSON Content-Type."""
        headers = {
            "Authorization": f"Bearer {self.session.access_token}",
            "X-Team-Id": self.session.team_id,
            "Referer": f"{self.base_url}/",
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout or self.timeout,
                headers=headers,
                cookies=self.session.cookies or None,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post(
                    path,
                    params={"token": token, "scope": scope},
                    files={"file": (filename, content, content_type)},
                )
        except httpx.HTTPError as exc:
            raise PingCodeUnavailable("PingCode 不可达，请稍后再试") from exc

        return self._decode(response)

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if response.status_code in _AUTH_CODES:
            raise PingCodeSessionExpired("登录态已失效")
        if response.status_code >= 500:
            raise PingCodeUnavailable(f"PingCode 返回 HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        if isinstance(code, int) and code in _AUTH_CODES:
            raise PingCodeSessionExpired("登录态已失效")
        if response.status_code >= 400:
            raise PingCodeBusinessError(
                _error_message(body, response),
                status=response.status_code,
                code=code if isinstance(code, int) else None,
            )
        if isinstance(code, int) and code not in OK_CODES:
            raise PingCodeBusinessError(
                _error_message(body, response), status=response.status_code, code=code
            )
        if not isinstance(body, dict):
            raise PingCodeUnavailable("PingCode 响应格式异常")

        data = body.get("data")
        if isinstance(data, dict) and "value" in data:
            # 列表/详情响应会把 references/count 与 value 并列; 适配层要能读到它们.
            return data if len(data) > 1 else data["value"]
        return data if data is not None else body
