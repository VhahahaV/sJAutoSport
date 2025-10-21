from __future__ import annotations

import asyncio
import copy
import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

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

FORM_ACTION_RE = re.compile(r"<form[^>]+action=\"(?P<action>[^\"]+)\"", re.IGNORECASE)
CAPTCHA_IMG_RE = re.compile(
    r"<img[^>]+id=\"captcha-img\"[^>]*src=\"(?P<src>[^\"]*)\"",
    re.IGNORECASE,
)
CAPTCHA_UUID_RE = re.compile(r"uuid=([0-9a-f\-]{8,})", re.IGNORECASE)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cookie_header(cookies: httpx.Cookies, *, domain: Optional[str] = None) -> str:
    cookie_pairs = []
    norm_domain = domain.lstrip(".") if domain else None
    for cookie in cookies.jar:
        if norm_domain:
            cookie_domain = (cookie.domain or "").lstrip(".")
            if cookie_domain and not norm_domain.endswith(cookie_domain):
                continue
        cookie_pairs.append(f"{cookie.name}={cookie.value}")
    return "; ".join(cookie_pairs)


def _clone_cookies(source: httpx.Cookies) -> httpx.Cookies:
    cloned = httpx.Cookies()
    for cookie in source.jar:
        cloned.jar.set_cookie(copy.copy(cookie))
    return cloned


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

    def _load_data(self) -> Tuple[Dict[str, Any], bool]:
        data_raw = self.store.load()
        changed = False
        if not isinstance(data_raw, dict):
            data_raw = {}
            changed = True

        data = dict(data_raw)

        # 迁移旧结构
        if "cookies" not in data or not isinstance(data.get("cookies"), dict):
            cookies: Dict[str, Any] = {}
            cookie_value = data.get("cookie")
            expires_at = data.get("expires_at")
            if cookie_value:
                cookies["__default__"] = {
                    "cookie": cookie_value,
                    "expires_at": expires_at,
                }
                data["active_user"] = "__default__"
            data["cookies"] = cookies
            changed = True

        data.setdefault("version", 2)
        data.setdefault("cookies", {})
        return data, changed

    def load_all_cookies(self) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        data, changed = self._load_data()
        cookies: Dict[str, Dict[str, Any]] = {}
        stale_keys: Dict[str, Any] = {}
        now = _now_utc()

        for key, entry in list(data["cookies"].items()):
            if not isinstance(entry, dict):
                stale_keys[key] = entry
                continue
            cookie_value = entry.get("cookie")
            if not cookie_value:
                stale_keys[key] = entry
                continue

            expires_raw = entry.get("expires_at")
            expires_at = None
            if expires_raw:
                try:
                    expires_at = datetime.fromisoformat(str(expires_raw))
                except Exception:
                    expires_at = None

            if expires_at and expires_at < now:
                stale_keys[key] = entry
                continue

            if not expires_at:
                expires_at = now + timedelta(hours=4)

            record = {
                "cookie": cookie_value,
                "expires_at": expires_at,
                "nickname": entry.get("nickname"),
                "username": entry.get("username") or (None if key == "__default__" else key),
            }
            cookies[key] = record

        if stale_keys:
            for key in stale_keys:
                data["cookies"].pop(key, None)
            changed = True

        if changed:
            self.store.save(data)

        return cookies, data.get("active_user")

    def load_cookie(self, username: Optional[str] = None) -> Optional[Tuple[str, datetime]]:
        cookies, active_user = self.load_all_cookies()
        key: Optional[str] = None

        if username and username in cookies:
            key = username
        elif active_user and active_user in cookies:
            key = active_user
        elif cookies:
            key = next(iter(cookies.keys()))

        if not key:
            return None
        record = cookies[key]
        return record["cookie"], record["expires_at"]

    def save_cookie(
        self,
        cookie: str,
        expires_at: datetime,
        *,
        username: Optional[str] = None,
        nickname: Optional[str] = None,
    ) -> None:
        data, _ = self._load_data()
        key = username or "__default__"
        entry: Dict[str, Any] = {
            "cookie": cookie,
            "expires_at": expires_at.isoformat(),
            "updated_at": _now_utc().isoformat(),
        }
        if username:
            entry["username"] = username
        if nickname:
            entry["nickname"] = nickname

        data["cookies"][key] = entry
        data["active_user"] = key
        self.store.save(data)

    def set_active_user(self, username: Optional[str]) -> bool:
        data, _ = self._load_data()
        if username is None:
            data["active_user"] = None
            self.store.save(data)
            return True

        if username not in data["cookies"]:
            return False
        data["active_user"] = username
        self.store.save(data)
        return True

    def delete_user(self, username: str) -> bool:
        data, _ = self._load_data()
        removed = False
        for key in list(data["cookies"].keys()):
            entry = data["cookies"].get(key, {})
            entry_username = entry.get("username") or key
            if entry_username == username:
                data["cookies"].pop(key, None)
                removed = True
        if removed:
            if data.get("active_user") == username:
                data["active_user"] = None
            self.store.save(data)
        return removed

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
        ):
            match = pattern.search(html)
            if match:
                return match.group("msg").strip()
        return None

    @staticmethod
    def _extract_captcha_info(base_url: httpx.URL, html: str) -> Tuple[Optional[str], Optional[str]]:
        match = CAPTCHA_IMG_RE.search(html)
        if not match:
            return None, None
        raw_src = match.group("src")
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

        captcha_url, captcha_uuid = self._extract_captcha_info(resp.request.url, html)
        if captcha_uuid and "uuid" not in hidden:
            hidden["uuid"] = captcha_uuid
            metadata["captcha_uuid"] = captcha_uuid
        elif "uuid" not in hidden:
            match = CAPTCHA_UUID_RE.search(html)
            if match:
                hidden["uuid"] = match.group(1)
                metadata["captcha_uuid"] = match.group(1)

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
        return current

    async def login(
        self,
        username: str,
        password: str,
        *,
        solver: Optional[CaptchaSolver] = None,
        fallback: Optional[HumanFallback] = None,
        threshold: float = 0.3,
        expires_in_hours: int = 8,
    ) -> AuthResult:
        state = await self.prepare()
        captcha_text: Optional[str] = None
        if state.captcha_required:
            if not solver:
                from .ocr import solve_captcha_async  # 延迟导入

                solver = solve_captcha_async
            image = await self.fetch_captcha(state)
            
            # 保存验证码图片用于调试
            import os
            import tempfile
            from datetime import datetime
            debug_dir = os.path.join(os.path.expanduser("~"), ".sja", "debug")
            os.makedirs(debug_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_path = os.path.join(debug_dir, f"captcha_{timestamp}.png")
            with open(debug_path, "wb") as f:
                f.write(image)
            print(f"[blue]验证码图片已保存到: {debug_path}[/blue]")
            
            captcha_text = ""
            confidence = 0.0
            if solver:
                captcha_text, confidence = await solver(image)
            # 智能验证码处理策略
            if not captcha_text:
                if fallback:
                    captcha_text = await fallback(image)
            elif confidence < threshold:
                # 如果置信度低但结果长度合理，仍然尝试使用
                if 4 <= len(captcha_text) <= 6:
                    print(f"[yellow]验证码识别置信度较低 ({confidence:.2f})，但将尝试使用识别结果: {captcha_text}[/yellow]")
                else:
                    if fallback:
                        captcha_text = await fallback(image)
            else:
                print(f"[green]验证码识别成功，置信度: {confidence:.2f}, 结果: {captcha_text}[/green]")
        submit_resp = await self.submit(state, username, password, captcha_text)
        final_resp = await self.follow_redirects(submit_resp, max_jumps=8)

        final_host = final_resp.request.url.host or ""
        if "jaccount" in final_host.lower():
            error_message = self._extract_error_message(final_resp.text) or f"{final_resp.status_code}"
            raise RuntimeError(f"登录失败：{error_message}")

        if final_resp.status_code >= 400:
            raise RuntimeError(f"登录失败：{final_resp.status_code}")

        sports_domain = urlparse(self.base_url).hostname
        cookie_header = _cookie_header(self._client.cookies, domain=sports_domain)
        if not cookie_header:
            raise RuntimeError("登录失败：未获得场馆系统会话 Cookie")
        expires_at = _now_utc() + timedelta(hours=expires_in_hours)
        return AuthResult(_clone_cookies(self._client.cookies), cookie_header, expires_at)

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
        f"{path}\n  输入验证码："
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
    threshold: float = 0.3,
) -> AuthResult:
    async with AuthClient(base_url, endpoints, auth_config) as client:
        return await client.login(
            username,
            password,
            solver=solver,
            fallback=fallback or default_fallback_prompt,
            threshold=threshold,
        )
