"""PLM (用友 YonBIP) 账号登录与业务请求客户端 (服务端).

已验证契约 (2026-11-13, 线上实测):
- 登录页 GET /cas/login?sysid=diwork&multiCas=true&service=<base>/login
  页面内嵌 modulus / exponent / randomvalue; 密码 tokeninfo 必须 RSA 加密
  (即使页面 pdstronger=false), 算法按 JS RSAUtils: little-endian 分块 + 十六进制拼接.
- POST 同一 URL 后返回 JS 跳转页; 需跟随 location.href → /login → CAS → /login?ticket=ST-...
  应用 cookie (orgId / tenantid / XSRF-TOKEN / yht_access_token) 才落地.
- 站点证书无法通过标准链校验, 默认关闭 TLS 校验 (settings.PLM_VERIFY_TLS).
- 业务请求使用 cookie 会话; X-Csrf-Token 取 XSRF-TOKEN cookie 中 '!' 之前部分.
"""
from __future__ import annotations

import hashlib
import json as jsonlib
import re
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from app.core.config import settings

DEFAULT_TIMEOUT = 30.0
SESSION_MINUTES = 120
CAS_PATH = "/cas/login"
LOGIN_PATH = "/login"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DOMAIN_KEY = "IMP-BASE"
_OK_CODES = {"0", "200", "success"}
_AUTH_STATUS = {401, 403}
_JS_REDIRECT_RE = re.compile(r"""location\.href\s*=\s*["']([^"']+)["']""")


class PlmError(Exception):
    """PLM 集成错误基类; message 可直接给用户看."""


class PlmAuthError(PlmError):
    """账号/密码错误或账号不可用."""


class PlmUnavailable(PlmError):
    """网络不可达、超时或上游响应异常."""


class PlmSessionExpired(PlmError):
    """业务请求判定登录态失效, 需要重新登录."""


class PlmBusinessError(PlmError):
    """上游业务错误; 带 HTTP 状态与业务 code 供调用方区分处理."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class PlmSession:
    access_token: str
    username: str
    display_name: str
    cookies: dict[str, str]
    access_token_expires_at: datetime
    org_id: str = ""
    tenant_id: str = ""

    def __post_init__(self) -> None:
        if not self.org_id:
            self.org_id = str(self.cookies.get("orgId") or "")
        if not self.tenant_id:
            self.tenant_id = str(self.cookies.get("tenantid") or "")


def _verify(value: bool | None) -> bool:
    return settings.PLM_VERIFY_TLS if value is None else value


def js_rsa_encrypt(text: str, modulus_hex: str, exponent_hex: str) -> str:
    """复刻 PLM 登录页 JS RSAUtils.encryptedString (1024-bit, 分块小端)."""
    n = int(modulus_hex, 16)
    e = int(exponent_hex, 16)
    chunk = 2 * (((n.bit_length() + 15) // 16) - 1)
    raw = text.encode("utf-8")
    out: list[str] = []
    for offset in range(0, len(raw), chunk):
        block = raw[offset : offset + chunk]
        out.append(format(pow(int.from_bytes(block, "little"), e, n), "x"))
    return " ".join(out)


def _page_var(html: str, name: str) -> str:
    match = re.search(name + r"""\s*=\s*['"]([^'"]*)['"]""", html)
    return match.group(1) if match else ""


def _cookie_dict(jar: Any) -> dict[str, str]:
    return {cookie.name: cookie.value for cookie in jar}


def _set_cookie(client: httpx.AsyncClient, base: str, name: str, value: str) -> None:
    host = urlparse(base).hostname or ""
    client.cookies.set(name, value, domain=host, path="/")


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _login_message(html: str) -> str:
    match = re.search(r'id="msg"[^>]*>(.*?)</div>', html, re.S)
    if match:
        text = _strip_tags(match.group(1))
        if text:
            return text[:200]
    return ""


async def _follow_js_redirect(
    client: httpx.AsyncClient, response: httpx.Response, rounds: int = 6
) -> httpx.Response:
    for _ in range(rounds):
        match = _JS_REDIRECT_RE.search(response.text or "")
        if not match:
            break
        target = urljoin(str(response.url), match.group(1))
        response = await client.get(target)
    return response


def _raise_if_login_failed(response: httpx.Response) -> None:
    """CAS 登录失败会停留在登录页 (带 msg 或密码框)."""
    path = urlparse(str(response.url)).path
    html = response.text or ""
    if path.startswith(CAS_PATH):
        message = _login_message(html)
        if message:
            raise PlmAuthError(f"PLM 登录失败: {message}")
        if 'name="password"' in html or 'id="password"' in html:
            raise PlmAuthError("PLM 账号或密码错误")


async def signin(
    username: str,
    password: str,
    *,
    base_url: str | None = None,
    timeout: float = 25.0,
    transport: httpx.AsyncBaseTransport | None = None,
    verify: bool | None = None,
) -> PlmSession:
    base = base_url or settings.PLM_BASE_URL
    base = base.rstrip("/")
    cas_url = (
        f"{base}{CAS_PATH}?sysid=diwork&multiCas=true"
        f"&service={quote(base + LOGIN_PATH, safe='')}"
    )
    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
            trust_env=False,
            verify=_verify(verify),
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(cas_url)
            html = response.text or ""
            modulus = _page_var(html, "modulus")
            exponent = _page_var(html, "exponent") or "10001"
            randomvalue = _page_var(html, "randomvalue")
            if not modulus or not randomvalue:
                raise PlmUnavailable("PLM 登录页解析失败，请稍后再试")

            xsrf = str(uuid.uuid4())
            _set_cookie(client, base, "CASJS-XSRF-TOKEN", xsrf)
            form = {
                "yhtCountry": "86",
                "username": username,
                "ssoLoginType": "normal",
                "tenantid": "-1",
                "warn": "true",
                "lt": "",
                "execution": "",
                "_eventId": "submit",
                "realusername": "",
                "tokeninfo": js_rsa_encrypt(password, modulus, exponent) + "_encrypted",
                "isAutoLogin": "0",
                "randomvalue": randomvalue,
                "yhtPd1": hashlib.sha1(password.encode("utf-8")).hexdigest(),
                "yhtPd2": hashlib.sha256(password.encode("utf-8")).hexdigest(),
                "yhtPd3": hashlib.md5(password.encode("utf-8")).hexdigest(),
                "X-XSRF-TOKEN": xsrf,
                "timeCode": "",
                "finger": "",
                "encryptData": "",
                "sid": "",
                "beat": "",
                "topService": "",
                "real": "",
                "validateCode": "",
                "validateKey": "false",
                "tenantPswIsSuccess": "true",
                "submit_btn": "登录",
            }
            response = await client.post(cas_url, data=form)
            _raise_if_login_failed(response)
            response = await _follow_js_redirect(client, response)
            response = await client.get(LOGIN_PATH)
            response = await _follow_js_redirect(client, response)
            _raise_if_login_failed(response)

            cookies = _cookie_dict(client.cookies.jar)
            # XSRF-TOKEN 是业务请求后才下发的, 登录完成时只有 orgId / tenantid.
            if not cookies.get("orgId"):
                raise PlmAuthError("PLM 账号或密码错误")
            return PlmSession(
                access_token=cookies.get("yht_access_token") or "plm-session",
                username=username,
                display_name=username,
                cookies=cookies,
                access_token_expires_at=datetime.utcnow()
                + timedelta(minutes=SESSION_MINUTES),
            )
    except httpx.HTTPError as exc:
        raise PlmUnavailable("PLM 不可达，请稍后再试") from exc


def _business_message(body: Any, response: httpx.Response) -> str:
    if isinstance(body, dict):
        for key in ("message", "msg", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
    text = (response.text or "").strip()
    return text[:300] or f"PLM 返回 HTTP {response.status_code}"


def _xml_error(text: str) -> str:
    code = re.search(r"<code>(\d+)</code>", text or "")
    if not code:
        return ""
    message = re.search(r"<message>([^<]*)</message>", text or "")
    return f"code={code.group(1)} {message.group(1) if message else ''}".strip()


def _is_login_page(response: httpx.Response, body: Any) -> bool:
    if any("/cas/login" in urlparse(str(hop.url)).path for hop in response.history):
        return True
    path = urlparse(str(response.url)).path
    if path.startswith(CAS_PATH):
        return True
    content_type = response.headers.get("content-type", "")
    return "text/html" in content_type and (
        'name="password"' in (response.text or "") or "cas/login" in (response.text or "")
    )


class PlmClient:
    """带 cookie 会话 + CSRF 的业务请求客户端."""

    def __init__(
        self,
        session: PlmSession,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        verify: bool | None = None,
    ) -> None:
        self.session = session
        self.base_url = (base_url or settings.PLM_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._verify = _verify(verify)

    def _headers(self, *, ajax: bool, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "domain-key": DOMAIN_KEY,
            "Referer": (
                f"{self.base_url}/mdf-node/meta/voucherlist/baseQuestionList"
                "?domainKey=IMP-BASE&locale=zh_CN&serviceCode=plm_base_question_manage"
            ),
        }
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
            xsrf = self.session.cookies.get("XSRF-TOKEN", "")
            if xsrf:
                headers["X-Csrf-Token"] = xsrf.split("!")[0]
        if extra:
            headers.update(extra)
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        ajax: bool = True,
        timeout: float | None = None,
        deflate: bool = False,
    ) -> Any:
        # 字典类接口 (getRefData) 只在 deflate + enable-deflate 下返回数据.
        extra = dict(headers or {})
        content: bytes | None = None
        if deflate:
            extra["enable-deflate"] = "true"
            content = zlib.compress(
                jsonlib.dumps(
                    json if json is not None else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout or self.timeout,
                headers=self._headers(ajax=ajax, extra=extra),
                cookies=self.session.cookies or None,
                transport=self._transport,
                follow_redirects=True,
                trust_env=False,
                verify=self._verify,
            ) as client:
                if content is not None:
                    response = await client.request(
                        method,
                        path,
                        params=params,
                        content=content,
                    )
                else:
                    response = await client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise PlmUnavailable("PLM 不可达，请稍后再试") from exc
        return self._decode(response)

    async def put(self, url: str, content: bytes, headers: dict[str, str] | None = None) -> int:
        """PUT 到对象存储预签名地址 (不同源, 不带会话 cookie)."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                trust_env=False,
                verify=self._verify,
            ) as client:
                response = await client.put(url, content=content, headers=headers or {})
        except httpx.HTTPError as exc:
            raise PlmUnavailable("PLM 附件存储不可达，请稍后再试") from exc
        return response.status_code

    async def download(
        self,
        url: str,
        *,
        timeout: float | None = None,
    ) -> tuple[bytes, str, str]:
        """下载同源文件; 返回 (内容, mime, 文件名)."""
        host = urlparse(url).hostname or ""
        if host != (urlparse(self.base_url).hostname or ""):
            raise PlmBusinessError("只允许下载 PLM 同源文件")
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout or self.timeout,
                headers={"User-Agent": USER_AGENT},
                cookies=self.session.cookies or None,
                transport=self._transport,
                follow_redirects=True,
                trust_env=False,
                verify=self._verify,
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise PlmUnavailable("PLM 不可达，请稍后再试") from exc
        if _is_login_page(response, None):
            raise PlmSessionExpired("登录态已失效")
        if response.status_code >= 400:
            raise PlmBusinessError(
                f"PLM 文件下载失败 (HTTP {response.status_code})",
                status=response.status_code,
            )
        mime = response.headers.get("content-type", "application/octet-stream")
        disposition = response.headers.get("content-disposition", "")
        match = re.search(r"filename\*?=(?:UTF-8'')?[\"']?([^;\"']+)", disposition, re.I)
        name = (match.group(1).strip() if match else "") or urlparse(url).path.rsplit("/", 1)[-1]
        return response.content, mime, name

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if _is_login_page(response, None):
            raise PlmSessionExpired("登录态已失效")
        if response.status_code in _AUTH_STATUS:
            raise PlmSessionExpired("登录态已失效")
        if response.status_code >= 500:
            raise PlmUnavailable(f"PLM 返回 HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError:
            body = None
        if body is None:
            text = (response.text or "").strip()
            xml = _xml_error(text)
            if xml:
                raise PlmBusinessError(f"PLM 业务错误: {xml}", status=response.status_code)
            if response.status_code >= 400:
                raise PlmBusinessError(
                    text[:300] or f"PLM 返回 HTTP {response.status_code}",
                    status=response.status_code,
                )
            raise PlmUnavailable("PLM 响应格式异常")

        code = body.get("code") if isinstance(body, dict) else None
        if isinstance(code, str) and code not in _OK_CODES:
            raise PlmBusinessError(
                _business_message(body, response),
                status=response.status_code,
                code=code,
            )
        if isinstance(code, int) and str(code) not in _OK_CODES:
            raise PlmBusinessError(
                _business_message(body, response),
                status=response.status_code,
                code=str(code),
            )
        if response.status_code >= 400:
            raise PlmBusinessError(
                _business_message(body, response), status=response.status_code
            )
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body
