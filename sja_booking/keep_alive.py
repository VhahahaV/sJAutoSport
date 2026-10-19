from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from .auth import AuthManager, _cookie_header

try:
    from . import config as CFG
except ImportError as exc:  # pragma: no cover - configuration should exist
    raise RuntimeError("keep_alive module requires top-level config.py") from exc


logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 15 * 60
REFRESH_WINDOW_MARGIN = timedelta(minutes=10)


@dataclass
class KeepAliveResult:
    username: Optional[str]
    nickname: Optional[str]
    success: bool
    message: str


def _parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    cookie = SimpleCookie()
    cookie.load(cookie_header or "")
    return {key: morsel.value for key, morsel in cookie.items()}


def _resolve_ping_endpoint() -> str:
    """
    Determine which endpoint to ping for keep-alive.
    Prefer the current_user endpoint if configured, fallback to '/'.
    """
    endpoint = getattr(CFG.ENDPOINTS, "current_user", None)
    if endpoint:
        return endpoint
    return "/"


async def _ping_cookie(
    username: Optional[str],
    nickname: Optional[str],
    cookie_header: str,
    *,
    timeout: float = 10.0,
) -> Tuple[bool, str, str]:
    """
    Send a GET request with the provided cookie header to keep the session alive.

    Returns:
        success flag, updated cookie header (may be unchanged), status message.
    """
    cookie_map = _parse_cookie_header(cookie_header)
    if not cookie_map:
        return False, cookie_header, "cookie header is empty"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{CFG.BASE_URL}/pc/",
    }

    base_url = CFG.BASE_URL.rstrip("/")
    endpoint = _resolve_ping_endpoint()
    url = endpoint if endpoint.startswith("http") else f"{base_url}{endpoint}"

    async with httpx.AsyncClient(headers=headers, timeout=timeout, trust_env=CFG.TRUST_ENV) as client:
        client.cookies.update(cookie_map)
        try:
            response = await client.get(url)
        except Exception as exc:  # pylint: disable=broad-except
            return False, cookie_header, f"request failed: {exc}"

        if response.status_code != 200:
            return False, cookie_header, f"session check returned HTTP {response.status_code}; log in again if expired"
        try:
            payload = response.json()
        except ValueError:
            return False, cookie_header, "session check returned HTML/non-JSON; log in again"
        if not isinstance(payload, dict) or payload.get("error") or payload.get("code") not in (None, 0, "0"):
            return False, cookie_header, "session invalid; log in again"
        if not any(payload.get(key) for key in ("data", "user", "userInfo", "loginName", "userName")):
            return False, cookie_header, "session has no authenticated profile; log in again"

        # Update cookies if server returned new values (httpx updates client.cookies automatically)
        domain = urlparse(base_url).hostname
        refreshed_header = _cookie_header(client.cookies, domain=domain)
        if refreshed_header:
            cookie_header = refreshed_header
        # 如果没有刷新后的header，使用原始的cookie_header
        elif not cookie_header and client.cookies:
            cookie_header = _cookie_header(client.cookies, domain=domain)

        return True, cookie_header, f"ping {response.status_code}"


async def run_keep_alive_once(*, auth_manager=None):
    manager = auth_manager or AuthManager()
    record = manager.load_record()
    if not record:
        return KeepAliveResult(None, None, False, "请先登录")
    username, nickname = record.get("username"), record.get("nickname")
    success, cookie, message = await _ping_cookie(username, nickname, record["cookie"])
    if success:
        manager.save_cookie(cookie, datetime.now(timezone.utc) + timedelta(hours=1), username=username, nickname=nickname)
    return KeepAliveResult(username, nickname, success, message)


async def keep_alive_loop(*, interval_seconds=900, stop_event=None):
    event = stop_event or asyncio.Event()
    while not event.is_set():
        await run_keep_alive_once()
        try:
            await asyncio.wait_for(event.wait(), timeout=max(60, interval_seconds))
        except asyncio.TimeoutError:
            pass
