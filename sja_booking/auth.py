from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple

import httpx

from .models import AuthConfig, EndpointSet

try:  # 可选加密 support
    from cryptography.fernet import Fernet  # type: ignore

    _FERNET_AVAILABLE = True
except Exception:  # pragma: no cover - 加密依赖非必选
    _FERNET_AVAILABLE = False


HiddenPair = Tuple[str, str]
CaptchaSolver = Callable[[bytes], Awaitable[Tuple[str, float]]]
HumanFallback = Callable[[bytes], Awaitable[str]]


HIDDEN_RE = re.compile(
    r"<input[^>]+type=\"hidden\"[^>]*name=\"(?P<name>[^\"]+)\"[^>]*value=\"(?P<value>[^\"]*)\"",
    re.IGNORECASE,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cookie_header(cookies: httpx.Cookies) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.jar.items())


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


@dataclass
class AuthResult:
    cookies: httpx.Cookies
    cookie_header: str
    expires_at: datetime


class AuthStore:
    """文件持久化，支持可选 Fernet 加密。"""

    def __init__(self, path: Optional[Path] = None, *, secret_env: str = "SJABOT_SECRET") -> None:
        self.path = path or Path.home() / ".sja" / "credentials.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        secret = os.getenv(secret_env)
        self._fernet: Optional[Any] = None
        if secret and _FERNET_AVAILABLE:
            key = secret.strip().encode("utf-8")
            if len(key) != 32:
                key = base64.urlsafe_b64encode(key.ljust(32, b"0")[:32])
            else:
                key = base64.urlsafe_b64encode(key)
            try:
                self._fernet = Fernet(key)
            except Exception:
                self._fernet = None

    def save(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self._fernet:
            data = self._fernet.encrypt(data)
        self.path.write_bytes(data)

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        data = self.path.read_bytes()
        if self._fernet:
            try:
                data = self._fernet.decrypt(data)
            except Exception:
                return None
        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class AuthManager:
    def __init__(self, store: Optional[AuthStore] = None) -> None:
        self.store = store or AuthStore()

    def load_cookie(self) -> Optional[Tuple[str, datetime]]:
        record = self.store.load()
        if not record:
            return None
        cookie = record.get("cookie")
        expires_at_raw = record.get("expires_at")
        if not cookie:
            return None
        expires_at = None
        if expires_at_raw:
            try:
                expires_at = datetime.fromisoformat(expires_at_raw)
            except Exception:
                expires_at = None
        if expires_at and expires_at < _now_utc():
            return None
        return cookie, expires_at or (_now_utc() + timedelta(hours=4))

    def save_cookie(self, cookie: str, expires_at: datetime) -> None:
        payload = {"cookie": cookie, "expires_at": expires_at.isoformat()}
        self.store.save(payload)

    def clear(self) -> None:
        self.store.clear()


class AuthClient:
    def __init__(
        self,
        base_url: str,
        endpoints: EndpointSet,
        auth_config: AuthConfig,
        *,
        timeout: float = 15.0,
    ) -> None:
        if not endpoints.login_prepare or not endpoints.login_submit:
            raise ValueError("EndpointSet 未配置 login_prepare/login_submit")
        self.base_url = base_url.rstrip("/")
        self.endpoints = endpoints
        self.auth_config = auth_config
        self._client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=False)

    async def close(self) -> None:
        await self._client.aclose()

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}{path}"

    async def prepare(self) -> AuthState:
        url = self._url(self.endpoints.login_prepare)
        resp = await self._client.get(url)
        resp.raise_for_status()
        html = resp.text
        hidden = self._parse_hidden_inputs(html)
        captcha_required = "captcha" in html.lower()
        referer = url
        submit_url = self._url(self.endpoints.login_submit)
        captcha_url = self._url(self.endpoints.login_captcha) if self.endpoints.login_captcha else None
        return AuthState(
            prepare_url=url,
            submit_url=submit_url,
            captcha_url=captcha_url,
            form=hidden,
            cookies=self._client.cookies.copy(),
            captcha_required=captcha_required,
            referer=referer,
        )

    async def fetch_captcha(self, state: AuthState) -> bytes:
        if not state.captcha_url:
            raise RuntimeError("未配置验证码端点")
        url = state.captcha_url
        if "?" in url:
            url = f"{url}&_ts={int(_now_utc().timestamp()*1000)}"
        else:
            url = f"{url}?_ts={int(_now_utc().timestamp()*1000)}"
        headers = {"Referer": state.referer or state.prepare_url}
        resp = await self._client.get(url, headers=headers)
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
        headers = {"Referer": state.referer or state.prepare_url, "Origin": self.base_url}
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
                current = await self._client.request(method, location)
                continue
            break
        return current

    async def login(
        self,
        username: str,
        password: str,
        *,
        solver: Optional[CaptchaSolver] = None,
        fallback: Optional[HumanFallback] = None,
        threshold: float = 0.85,
        expires_in_hours: int = 8,
    ) -> AuthResult:
        state = await self.prepare()
        captcha_text: Optional[str] = None
        if state.captcha_required:
            if not solver:
                from .ocr import solve_captcha_async  # 延迟导入

                solver = solve_captcha_async
            image = await self.fetch_captcha(state)
            captcha_text = ""
            confidence = 0.0
            if solver:
                captcha_text, confidence = await solver(image)
            if (not captcha_text or confidence < threshold) and fallback:
                captcha_text = await fallback(image)
        submit_resp = await self.submit(state, username, password, captcha_text)
        final_resp = await self.follow_redirects(submit_resp)
        if final_resp.status_code >= 400:
            raise RuntimeError(f"登录失败：{final_resp.status_code}")
        cookie_header = _cookie_header(self._client.cookies)
        expires_at = _now_utc() + timedelta(hours=expires_in_hours)
        return AuthResult(self._client.cookies.copy(), cookie_header, expires_at)

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


async def default_fallback_prompt(image_bytes: bytes) -> str:
    import tempfile

    path = Path(tempfile.gettempdir()) / f"captcha_{int(_now_utc().timestamp())}.png"
    path.write_bytes(image_bytes)
    console_message = (
        "验证码识别置信度不足，请查看文件并输入结果：\n"
        f"  路径：{path}\n  输入验证码："
    )
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(console_message).strip())


async def perform_login(
    base_url: str,
    endpoints: EndpointSet,
    auth_config: AuthConfig,
    username: str,
    password: str,
    *,
    solver: Optional[CaptchaSolver] = None,
    fallback: Optional[HumanFallback] = None,
) -> AuthResult:
    async with AuthClient(base_url, endpoints, auth_config) as client:
        return await client.login(
            username,
            password,
            solver=solver,
            fallback=fallback or default_fallback_prompt,
        )
