from __future__ import annotations

import asyncio
import copy
import base64
import json
import os
import re
from html import unescape
from html.parser import HTMLParser
from http.cookiejar import Cookie
import threading
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

import httpx
from .config import TRUST_ENV

from .models import AuthConfig, EndpointSet


class LoginImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img" and attrs.get("id"):
            self.images[attrs["id"]] = attrs.get("src", "")

_STORE_LOCK = threading.RLock()


def synchronized(method):
    @wraps(method)
    def locked(*args, **kwargs):
        with _STORE_LOCK:
            return method(*args, **kwargs)
    return locked

try:  # 可选加密 support
    from cryptography.fernet import Fernet  # type: ignore

    _FERNET_AVAILABLE = True
except Exception:  # pragma: no cover - 加密依赖非必选
    _FERNET_AVAILABLE = False


HiddenPair = Tuple[str, str]


HIDDEN_RE = re.compile(
    r"<input[^>]+type=\"hidden\"[^>]*name=\"(?P<name>[^\"]+)\"[^>]*value=\"(?P<value>[^\"]*)\"",
    re.IGNORECASE,
)

FORM_ACTION_RE = re.compile(r"<form[^>]+action=\"(?P<action>[^\"]+)\"", re.IGNORECASE)
CAPTCHA_IMG_RE = re.compile(
    r"<img[^>]+id=\"captcha-img\"[^>]*src=\"(?P<src>[^\"]*)\"",
    re.IGNORECASE,
)
CAPTCHA_UUID_RE = re.compile(r"uuid=([0-9a-f\-]{8,})", re.IGNORECASE)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cookie_header(cookies: httpx.Cookies, *, domain: Optional[str] = None, url: Optional[str] = None) -> str:
    if url:
        request = httpx.Request("GET", url)
        cookies.set_cookie_header(request)
        return request.headers.get("cookie", "")
    cookie_pairs = []
    norm_domain = domain.lstrip(".") if domain else None
    for cookie in cookies.jar:
        if norm_domain:
            cookie_domain = (cookie.domain or "").lstrip(".")
            if cookie_domain and norm_domain != cookie_domain and not norm_domain.endswith("." + cookie_domain):
                continue
        cookie_pairs.append(f"{cookie.name}={cookie.value}")
    return "; ".join(cookie_pairs)


def _clone_cookies(source: httpx.Cookies) -> httpx.Cookies:
    cloned = httpx.Cookies()
    for cookie in source.jar:
        cloned.jar.set_cookie(copy.copy(cookie))
    return cloned


def serialize_cookies(cookies: httpx.Cookies) -> list[dict]:
    """Keep scope and attributes, including same-name cookies on different paths."""
    return [{**{key: getattr(cookie, key) for key in (
        "version", "name", "value", "port", "port_specified", "domain",
        "domain_specified", "domain_initial_dot", "path", "path_specified",
        "secure", "expires", "discard", "comment", "comment_url", "rfc2109",
    )}, "rest": dict(cookie._rest)} for cookie in cookies.jar if not cookie.is_expired()]


def restore_cookies(record: dict) -> httpx.Cookies:
    from .config import BASE_URL
    cookies = httpx.Cookies()
    for item in record.get("session_cookies", []):
        cookie = Cookie(**item)
        if not cookie.is_expired():
            cookies.jar.set_cookie(cookie)
    # Existing credentials remain usable until the next interactive login captures SSO.
    if not record.get("session_cookies"):
        from http.cookies import SimpleCookie
        parsed = SimpleCookie(record.get("cookie", ""))
        for key, value in parsed.items():
            cookies.set(key, value.value, domain=urlparse(BASE_URL).hostname or "", path="/")
    return cookies


def has_sso_session(record: dict) -> bool:
    if record.get("login_required"):
        return False
    return any((cookie.domain or "").lstrip(".") in {"jaccount.sjtu.edu.cn", "sjtu.edu.cn"}
               for cookie in restore_cookies(record).jar)


def authenticated_user(payload: Any) -> Optional[dict]:
    """A successful status without a user identity is not authentication."""
    if not isinstance(payload, dict) or payload.get("error") or payload.get("code") not in (None, 0, "0"):
        return None
    user = payload
    for key in ("data", "user", "userInfo", "result", "payload"):
        if isinstance(payload.get(key), dict) and payload[key]:
            user = payload[key]
            break
    return user if user.get("loginName") or user.get("userName") else None


def same_account(username: Optional[str], login_name: Optional[str]) -> bool:
    def normalize(value):
        return value.strip().lower().removesuffix("@sjtu.edu.cn") if isinstance(value, str) else ""
    return bool(normalize(login_name)) and (username in (None, "", "__default__") or normalize(username) == normalize(login_name))


def _merge_form(base: Dict[str, str], updates: Dict[str, str]) -> Dict[str, str]:
    merged = dict(base)
    merged.update({k: v for k, v in updates.items() if v is not None})
    return merged


@dataclass
class AuthState:
    prepare_url: str
    submit_url: str
    captcha_url: Optional[str]
    form: Dict[str, str]
    cookies: httpx.Cookies
    captcha_required: bool = True
    referer: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuthStore:
    """文件持久化，支持可选 Fernet 加密。"""

    def __init__(self, path: Optional[Path] = None, *, secret_env: str = "SJA_SECRET") -> None:
        default_store = os.getenv("SJA_CREDENTIAL_STORE")
        if default_store:
            default_path = Path(default_store).expanduser()
        else:
            default_path = Path(os.environ.get("SJA_DATA_DIR", Path.home() / ".local/share/sja-sport")) / "credentials.json"

        self.path = Path(path).expanduser() if path else default_path
        self.path = self.path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        secret = os.getenv(secret_env)
        if secret and not _FERNET_AVAILABLE:
            raise RuntimeError("SJA_SECRET requires cryptography; install the secure extra or unset SJA_SECRET")
        self._fernet: Optional[Any] = None
        if secret and _FERNET_AVAILABLE:
            key = secret.strip().encode("utf-8")
            if len(key) != 32:
                key = base64.urlsafe_b64encode(key.ljust(32, b"0")[:32])
            else:
                key = base64.urlsafe_b64encode(key)
            try:
                self._fernet = Fernet(key)
            except ValueError as exc:
                raise RuntimeError("SJA_SECRET cannot initialize credential encryption") from exc

    def save(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self._fernet:
            data = self._fernet.encrypt(data)
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        temporary.chmod(0o600)
        temporary.replace(self.path)

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        data = self.path.read_bytes()
        if self._fernet:
            try:
                data = self._fernet.decrypt(data)
            except Exception as exc:
                raise RuntimeError("凭据解密失败，请核对 SJA_SECRET；原文件已保留") from exc
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("凭据文件损坏或未使用正确的解密配置；原文件已保留") from exc

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class AuthManager:
    """Persist exactly one verified account. A successful login replaces it."""
    def __init__(self, store: Optional[AuthStore] = None):
        self.store = store or AuthStore()

    @synchronized
    def load_record(self):
        record = self.store.load()
        if not record:
            return None
        if not isinstance(record, dict) or "cookies" in record:
            raise RuntimeError("凭据文件必须为单账号结构，请根据 README 迁移或重新登录")
        if not record.get("cookie"):
            return None
        result = dict(record)
        value = result.get("expires_at")
        if value:
            expires = datetime.fromisoformat(value)
            result["expires_at"] = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
        return result

    @synchronized
    def save_cookie(self, cookie, expires_at=None, *, username=None, nickname=None,
                    session_cookies=None, expected_record=None, renewed=False):
        if expected_record is not None and self.load_record() != expected_record:
            return False
        now = _now_utc().isoformat()
        self.store.save({"username": username, "nickname": nickname, "cookie": cookie,
                         "expires_at": expires_at.isoformat() if expires_at else None,
                         "session_cookies": session_cookies or [], "verified_at": now,
                         "renewed_at": now if renewed else (expected_record or {}).get("renewed_at"),
                         "login_required": False})
        return True

    @synchronized
    def mark_login_required(self, expected_record, message):
        if self.load_record() != expected_record:
            return False
        record = self.store.load()
        record["login_required"] = True
        record["login_required_message"] = message
        self.store.save(record)
        return True

    @synchronized
    def update_identity(self, cookie, *, username=None, nickname=None):
        """Enrich this session's identity without replacing newer credentials."""
        record = self.store.load()
        if not record or record.get("cookie") != cookie:
            return
        updated = dict(record)
        if username and username != "__default__":
            updated["username"] = username
        if nickname and record.get("nickname") in (None, "", "__default__"):
            updated["nickname"] = nickname
        if updated != record:
            self.store.save(updated)

    @synchronized
    def clear(self):
        self.store.clear()


class AuthClient:
    def __init__(
        self,
        base_url: str,
        endpoints: EndpointSet,
        auth_config: AuthConfig,
        *,
        timeout: float = 15.0,
        cookies: Optional[httpx.Cookies] = None,
    ) -> None:
        if not endpoints.login_prepare or not endpoints.login_submit:
            raise ValueError("EndpointSet 未配置 login_prepare/login_submit")
        self.base_url = base_url.rstrip("/")
        self.endpoints = endpoints
        self.auth_config = auth_config
        self._client = httpx.AsyncClient(timeout=timeout, cookies=cookies, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=False, trust_env=TRUST_ENV)

    async def close(self) -> None:
        await self._client.aclose()

    async def current_user(self) -> Optional[dict]:
        response = await self._client.get(self._url(self.endpoints.current_user))
        if response.status_code in (401, 403) or response.is_redirect:
            return None
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            if "text/html" in response.headers.get("content-type", ""):
                return None
            raise RuntimeError("用户资料接口返回异常，稍后重试") from None
        user = authenticated_user(payload)
        if user:
            return user
        if isinstance(payload, dict) and payload.get("code") in (None, 0, "0", 301, "301", 401, "401", 403, "403"):
            return None
        raise RuntimeError("用户资料接口暂时不可用，稍后重试")

    async def reauthorize(self) -> bool:
        """Only follow the normal sports/jAccount authorization redirects; never submit a login form."""
        sports_host = urlparse(self.base_url).hostname
        # Start a fresh sports session while retaining jAccount's separate session.
        for cookie in list(self._client.cookies.jar):
            if cookie.domain.lstrip(".") == sports_host:
                self._client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
        target = self._url(self.endpoints.login_prepare)
        for _ in range(12):
            url = httpx.URL(target)
            if url.scheme != "https" or url.host not in {sports_host, "jaccount.sjtu.edu.cn"}:
                raise RuntimeError("校园授权返回了非预期地址，已停止恢复")
            response = await self._client.get(url)
            if not response.is_redirect:
                response.raise_for_status()
                return response.url.host == sports_host
            location = response.headers.get("location")
            if not location:
                raise RuntimeError("校园授权跳转缺少目标地址")
            target = self._absolute_url(response.url, location)
        raise RuntimeError("校园授权跳转次数过多，稍后重试")

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}{path}"

    @staticmethod
    def _absolute_url(base: httpx.URL, target: str) -> str:
        if not target:
            return str(base)
        url_obj = httpx.URL(target)
        if not url_obj.scheme:
            url_obj = base.join(target)
        return str(url_obj)

    async def _resolve_response(self, response: httpx.Response, *, max_jumps: int = 8) -> httpx.Response:
        current = response
        jumps = 0
        while current.is_redirect and jumps < max_jumps:
            location = current.headers.get("location")
            if not location:
                break
            next_url = self._absolute_url(current.request.url, location)
            headers = {"Referer": str(current.request.url)}
            current = await self._client.get(next_url, headers=headers)
            jumps += 1
        return current

    @staticmethod
    def _extract_form_action(html: str) -> Optional[str]:
        match = FORM_ACTION_RE.search(html)
        if match:
            return match.group("action").strip()
        return None

    @staticmethod
    def _extract_error_message(html: str) -> Optional[str]:
        for pattern in (
            re.compile(r"<span[^>]+id=\"(?:errmsg|errorMsg)\"[^>]*>(?P<msg>[^<]+)<", re.IGNORECASE),
            re.compile(r"<p[^>]+class=\"error[^>]*>(?P<msg>[^<]+)<", re.IGNORECASE),
            re.compile(r"showMessage\(['\"](?P<msg>[^'\"]+)['\"]\)", re.IGNORECASE),
            re.compile(r"msg\s*:\s*['\"](?P<msg>[^'\"]+)['\"]", re.IGNORECASE),
            re.compile(r"<div[^>]+class=\"alert[^>]*>(?P<msg>[^<]+)<", re.IGNORECASE),
            re.compile(r"Missing your account[^<]*", re.IGNORECASE),
        ):
            match = pattern.search(html)
            if match:
                group = match.groupdict().get("msg") if match.groups() else match.group(0)
                return group.strip()
        return None

    @staticmethod
    def _extract_captcha_info(base_url: httpx.URL, html: str) -> Tuple[Optional[str], Optional[str]]:
        match = CAPTCHA_IMG_RE.search(html)
        if not match:
            return None, None
        raw_src = unescape(match.group("src"))
        if not raw_src or raw_src.endswith("image/captcha.png"):
            raw_src = ""
        captcha_url = AuthClient._absolute_url(base_url, raw_src) if raw_src else None
        uuid_match = CAPTCHA_UUID_RE.search(raw_src)
        if not uuid_match:
            uuid_match = CAPTCHA_UUID_RE.search(html)
        captcha_uuid = uuid_match.group(1) if uuid_match else None
        return captcha_url, captcha_uuid

    async def prepare(self) -> AuthState:
        entry_path = self.endpoints.login_prepare or "/"
        entry_url = self._url(entry_path)
        resp = await self._client.get(entry_url)
        resp = await self._resolve_response(resp)
        resp.raise_for_status()
        html = resp.text
        hidden = self._parse_hidden_inputs(html)
        metadata: Dict[str, Any] = {}
        images = LoginImages()
        images.feed(html)

        captcha_url, captcha_uuid = self._extract_captcha_info(resp.request.url, html)
        if captcha_uuid and "uuid" not in hidden:
            hidden["uuid"] = captcha_uuid
            metadata["captcha_uuid"] = captcha_uuid
        elif "uuid" not in hidden:
            match = CAPTCHA_UUID_RE.search(html)
            if match:
                hidden["uuid"] = match.group(1)
                metadata["captcha_uuid"] = match.group(1)

        if "qr-img" in images.images:
            image_url = httpx.URL(self._absolute_url(resp.request.url, images.images["qr-img"] or "qrcode"))
            qr_uuid = image_url.params.get("uuid") or metadata.get("captcha_uuid") or hidden.get("uuid")
            if image_url.host != resp.request.url.host or not qr_uuid:
                raise RuntimeError("二维码登录页面返回异常地址")
            image_url = image_url.copy_merge_params({"uuid": qr_uuid})
            metadata.update(qr_image_url=str(image_url), qr_uuid=qr_uuid,
                            qr_socket_url=f"{'wss' if resp.request.url.scheme == 'https' else 'ws'}://{resp.request.url.host}/jaccount/sub/{qr_uuid}",
                            qr_express_url=str(resp.request.url.join("expresslogin").copy_merge_params({"uuid": qr_uuid})))

        form_action = self._extract_form_action(html) or self.endpoints.login_submit or str(resp.request.url)
        submit_url = self._absolute_url(resp.request.url, form_action)
        if not captcha_url and self.endpoints.login_captcha:
            captcha_url = self._url(self.endpoints.login_captcha)

        # Persist key query parameters required by the form submission (sid/client/returl/se)
        query_params = {key: value for key, value in resp.request.url.params.multi_items()}
        if query_params:
            metadata["login_params"] = {k: v for k, v in query_params.items() if v}

        return AuthState(
            prepare_url=str(resp.request.url),
            submit_url=submit_url,
            captcha_url=captcha_url,
            form=hidden,
            cookies=_clone_cookies(self._client.cookies),
            captcha_required=bool(captcha_url),
            referer=str(resp.request.url),
            metadata=metadata,
        )

    async def fetch_captcha(self, state: AuthState) -> bytes:
        if not state.captcha_url:
            raise RuntimeError("未配置验证码端点")
        url_obj = httpx.URL(state.captcha_url)
        captcha_uuid = state.metadata.get("captcha_uuid") or state.form.get("uuid")
        if captcha_uuid:
            url_obj = url_obj.copy_add_param("uuid", captcha_uuid)
        url_obj = url_obj.copy_add_param("_ts", str(int(_now_utc().timestamp() * 1000)))
        headers = {"Referer": state.referer or state.prepare_url}
        resp = await self._client.get(url_obj, headers=headers)
        resp.raise_for_status()
        return resp.content

    async def submit(
        self,
        state: AuthState,
        username: str,
        password: str,
        captcha_text: Optional[str],
    ) -> httpx.Response:
        form = _merge_form(
            state.form,
            {
                "user": username,
                "pass": password,
                "captcha": captcha_text or "",
            },
        )
        login_params = state.metadata.get("login_params") or {}
        form = _merge_form(form, {k: v for k, v in login_params.items() if v})
        headers = {"Referer": state.referer or state.prepare_url}
        parsed = urlparse(state.submit_url)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
        else:
            origin = self.base_url
        headers["Origin"] = origin
        resp = await self._client.post(state.submit_url, data=form, headers=headers)
        return resp

    async def follow_redirects(self, response: httpx.Response, max_jumps: int = 5) -> httpx.Response:
        current = response
        for _ in range(max_jumps):
            if current.is_redirect:
                location = current.headers.get("location")
                if not location:
                    break
                method = "GET" if current.status_code in (301, 302, 303) else "POST"
                target = self._absolute_url(current.request.url, location)
                headers = {"Referer": str(current.request.url)}
                current = await self._client.request(method, target, headers=headers)
                continue
            break
        current.raise_for_status()
        if "jaccount" in (current.request.url.host or "").lower():
            reason = self._extract_error_message(current.text)
            raise RuntimeError(reason or "登录停留在 jAccount，请检查账号、密码、验证码或额外认证要求")
        return current

    async def __aenter__(self) -> "AuthClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        await self.close()

    @staticmethod
    def _parse_hidden_inputs(html: str) -> Dict[str, str]:
        form: Dict[str, str] = {}
        for match in HIDDEN_RE.finditer(html):
            form[match.group("name")] = match.group("value")
        return form
