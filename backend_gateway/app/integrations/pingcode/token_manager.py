"""PingCode 登录态生命周期: 缓存、主动续期、401 重试、失败冷却与单飞."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

import httpx

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.integrations import credentials, crypto
from app.integrations.pingcode import client
from app.integrations.redis import redis_client
from app.models.integration import IntegrationCredential

logger = logging.getLogger(__name__)

PROVIDER = "pingcode"
LOCK_TTL_SECONDS = 30
MAX_LOGIN_FAILURES = 3
COOLDOWN_SECONDS = 300
COOLDOWN_MESSAGE = "账号连续登录失败，请稍后再试或检查凭据"

BackgroundTask = Callable[[], Awaitable[None]]


class IntegrationNotConfigured(client.PingCodeError):
    """用户尚未绑定外部系统凭据."""


class IntegrationReauthRequired(client.PingCodeError):
    """缓存的登录态不可用, 需要用户重新绑定."""


def _lock_key(record_id: int) -> str:
    return f"integration:login:{record_id}"


class TokenManager:
    """按用户维护 PingCode 会话; 所有网络与时钟依赖均可注入以便测试."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        redis_factory: Callable[[], Any] | None = None,
        session_factory: Callable[[], Any] = AsyncSessionLocal,
        now: Callable[[], datetime] = datetime.utcnow,
        poll_interval: float = 0.05,
        lock_timeout: float = 30.0,
    ) -> None:
        self._transport = transport
        self._redis_factory = redis_factory or redis_client
        self._session_factory = session_factory
        self._now = now
        self._poll_interval = poll_interval
        self._lock_timeout = lock_timeout
        self._tasks: set[asyncio.Task] = set()

    # ── 公共入口 ──────────────────────────────────────────────
    async def ensure_session(self, user_id: int, *, force: bool = False) -> client.PingCodeSession:
        async with self._session_factory() as session:
            record = await credentials.get(session, user_id, PROVIDER)
            if record is None:
                raise IntegrationNotConfigured(
                    "尚未配置 PingCode 账号，请在个人中心 → 平台认证中绑定"
                )
            if not force:
                cached = self._cached(record)
                if cached is not None:
                    return cached
            if self._cooling(record):
                raise IntegrationReauthRequired(COOLDOWN_MESSAGE)
            record_id = record.id
        return await self._refresh_single_flight(user_id, record_id, force=force)

    async def request(
        self,
        user_id: int,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        session = await self.ensure_session(user_id)
        try:
            return await self._client(session).request(
                method, path, params=params, json=json
            )
        except client.PingCodeSessionExpired:
            pass
        session = await self.ensure_session(user_id, force=True)
        try:
            return await self._client(session).request(
                method, path, params=params, json=json
            )
        except client.PingCodeSessionExpired as exc:
            await self._mark_reauth(user_id, "登录态已失效，请重新绑定账号")
            raise IntegrationReauthRequired(
                "PingCode 登录态已失效，请到个人中心重新绑定账号"
            ) from exc

    # ── 缓存与冷却 ────────────────────────────────────────────
    def _cached(self, record: IntegrationCredential) -> client.PingCodeSession | None:
        if record.status != "ok" or not record.token_encrypted:
            return None
        expires_at = record.token_expires_at
        if expires_at is None or expires_at <= self._now():
            return None
        try:
            token = crypto.decrypt_secret(
                record.token_encrypted,
                user_id=record.user_id,
                provider=record.provider,
            )
        except crypto.IntegrationCryptoError:
            return None
        cookies = self._cookies(record)
        return client.PingCodeSession(
            access_token=token,
            team_id=settings.PINGCODE_TEAM_ID,
            display_name=record.username,
            team_name="",
            cookies=cookies,
            access_token_expires_at=expires_at,
        )

    @staticmethod
    def _cookies(record: IntegrationCredential) -> dict[str, str]:
        if not record.cookies_encrypted:
            return {}
        try:
            raw = crypto.decrypt_secret(
                record.cookies_encrypted,
                user_id=record.user_id,
                provider=record.provider,
            )
            data = json.loads(raw)
        except (crypto.IntegrationCryptoError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def _cooling(self, record: IntegrationCredential) -> bool:
        if (record.login_failures or 0) < MAX_LOGIN_FAILURES:
            return False
        attempted = record.last_attempt_at
        if attempted is None:
            return False
        return self._now() - attempted < timedelta(seconds=COOLDOWN_SECONDS)

    # ── 单飞与刷新 ────────────────────────────────────────────
    async def _refresh_single_flight(
        self, user_id: int, record_id: int, *, force: bool = False
    ) -> client.PingCodeSession:
        key = _lock_key(record_id)
        try:
            async with self._redis_factory() as redis:
                acquired = await redis.set(key, "1", nx=True, ex=LOCK_TTL_SECONDS)
                if not acquired:
                    cached = None if force else await self._wait_for_refresh(
                        user_id, redis, key
                    )
                    if cached is not None:
                        return cached
                    if force:
                        await self._wait_for_lock_release(redis, key)
                    acquired = await redis.set(key, "1", nx=True, ex=LOCK_TTL_SECONDS)
                if not acquired:
                    logger.warning("pingcode login lock timed out for credential %s", record_id)
                    return await self._refresh_or_login(user_id)
                try:
                    if not force:
                        cached = await self._reload_cached(user_id)
                        if cached is not None:
                            return cached
                    return await self._refresh_or_login(user_id)
                finally:
                    await redis.delete(key)
        except IntegrationNotConfigured:
            raise
        except IntegrationReauthRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, client.PingCodeError):
                raise
            logger.warning("pingcode login lock unavailable: %s", type(exc).__name__)
            return await self._refresh_or_login(user_id)

    async def _wait_for_refresh(
        self, user_id: int, redis: Any, key: str
    ) -> client.PingCodeSession | None:
        deadline = time.monotonic() + self._lock_timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(self._poll_interval)
            cached = await self._reload_cached(user_id)
            if cached is not None:
                return cached
            if not await redis.get(key):
                return None
        return None

    async def _wait_for_lock_release(self, redis: Any, key: str) -> None:
        deadline = time.monotonic() + self._lock_timeout
        while time.monotonic() < deadline:
            if not await redis.get(key):
                return
            await asyncio.sleep(self._poll_interval)

    async def _reload_cached(self, user_id: int) -> client.PingCodeSession | None:
        async with self._session_factory() as session:
            record = await credentials.get(session, user_id, PROVIDER)
            return self._cached(record) if record is not None else None

    async def _refresh_or_login(self, user_id: int) -> client.PingCodeSession:
        async with self._session_factory() as session:
            record = await credentials.get(session, user_id, PROVIDER)
            if record is None:
                raise IntegrationNotConfigured(
                    "尚未配置 PingCode 账号，请在个人中心 → 平台认证中绑定"
                )
            if self._cooling(record):
                raise IntegrationReauthRequired(COOLDOWN_MESSAGE)
            try:
                password = credentials.password_of(record)
            except crypto.IntegrationCryptoError as exc:
                raise IntegrationReauthRequired("凭据无法解密，请重新绑定账号") from exc

            cookies = self._cookies(record)
            if cookies:
                try:
                    token, merged = await client.refresh_access_token(
                        cookies, transport=self._transport
                    )
                except (client.PingCodeAuthError, client.PingCodeUnavailable) as exc:
                    logger.info("pingcode cookie refresh failed: %s", type(exc).__name__)
                else:
                    login = client.PingCodeSession(
                        access_token=token,
                        team_id=settings.PINGCODE_TEAM_ID,
                        display_name=record.username,
                        team_name="",
                        cookies=merged,
                        access_token_expires_at=datetime.utcnow()
                        + timedelta(minutes=client.SESSION_MINUTES),
                    )
                    await credentials.save_session(session, record, login)
                    self._schedule_prolong(merged)
                    return login

            try:
                login = await client.signin(
                    record.username, password, transport=self._transport
                )
            except client.PingCodeAuthError as exc:
                await credentials.record_failure(session, record, str(exc))
                raise IntegrationReauthRequired(str(exc)) from exc
            except client.PingCodeUnavailable as exc:
                await credentials.record_failure(
                    session, record, str(exc), needs_reauth=False
                )
                raise
            await credentials.save_login(
                session,
                user_id=record.user_id,
                provider=record.provider,
                username=record.username,
                password=password,
                login=login,
            )
            return login

    async def _mark_reauth(self, user_id: int, message: str) -> None:
        async with self._session_factory() as session:
            record = await credentials.get(session, user_id, PROVIDER)
            if record is not None:
                await credentials.record_failure(session, record, message)

    def _schedule_prolong(self, cookies: dict[str, str]) -> None:
        async def _run() -> None:
            try:
                await client.prolong_logged_state(cookies, transport=self._transport)
            except Exception as exc:  # noqa: BLE001
                logger.info("pingcode prolong failed: %s", type(exc).__name__)

        task = asyncio.create_task(_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _client(self, session: client.PingCodeSession) -> client.PingCodeClient:
        return client.PingCodeClient(session, transport=self._transport)


_default_manager = TokenManager()


async def ensure_session(user_id: int, *, force: bool = False) -> client.PingCodeSession:
    return await _default_manager.ensure_session(user_id, force=force)


async def request(
    user_id: int,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
) -> Any:
    return await _default_manager.request(user_id, method, path, params=params, json=json)
