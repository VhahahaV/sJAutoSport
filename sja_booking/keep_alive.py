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
    import config as CFG
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

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        client.cookies.update(cookie_map)
        try:
            response = await client.get(url)
        except Exception as exc:  # pylint: disable=broad-except
            return False, cookie_header, f"request failed: {exc}"

        if response.status_code == 401:
            return False, cookie_header, "session expired (401)"
        if response.status_code >= 500:
            return False, cookie_header, f"server error {response.status_code}"

        # Update cookies if server returned new values (httpx updates client.cookies automatically)
        domain = urlparse(base_url).hostname
        refreshed_header = _cookie_header(client.cookies, domain=domain)
        if refreshed_header:
            cookie_header = refreshed_header

        return True, cookie_header, f"ping {response.status_code}"


async def run_keep_alive_once(
    *,
    auth_manager: Optional[AuthManager] = None,
    refresh_interval: timedelta = timedelta(hours=1),
) -> List[KeepAliveResult]:
    """
    Refresh all stored cookies once.
    """
    manager = auth_manager or AuthManager()
    cookies_map, _ = manager.load_all_cookies()
    results: List[KeepAliveResult] = []

    if not cookies_map:
        logger.info("KeepAlive: no cookies found in store")
        return results

    now = datetime.now(timezone.utc)

    for key, record in cookies_map.items():
        username = record.get("username") or (None if key == "__default__" else key)
        nickname = record.get("nickname")
        cookie_header = record.get("cookie") or ""

        success, updated_cookie, message = await _ping_cookie(username, nickname, cookie_header)
        if success:
            expires_at = now + refresh_interval
            manager.save_cookie(
                updated_cookie,
                expires_at,
                username=username,
                nickname=nickname,
            )
            results.append(
                KeepAliveResult(
                    username=username,
                    nickname=nickname,
                    success=True,
                    message=message,
                )
            )
            logger.debug("KeepAlive success for %s: %s", username or key, message)
        else:
            results.append(
                KeepAliveResult(
                    username=username,
                    nickname=nickname,
                    success=False,
                    message=message,
                )
            )
            logger.warning("KeepAlive failed for %s: %s", username or key, message)

    # 同步内存中的用户信息，确保后续操作使用最新 Cookie
    try:
        from . import service  # pylint: disable=cyclic-import

        updated_map, _ = manager.load_all_cookies()
        service._sync_users_from_store(updated_map)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - 最好努力但不影响主流程
        pass

    return results


async def run_keep_alive_for_user(
    identifier: str,
    *,
    auth_manager: Optional[AuthManager] = None,
    refresh_interval: timedelta = timedelta(hours=1),
) -> KeepAliveResult:
    """
    Refresh cookie for a single stored user identified by username or nickname.
    """
    manager = auth_manager or AuthManager()
    cookies_map, _ = manager.load_all_cookies()

    target_key = None
    target_record: Optional[Dict[str, Any]] = None

    for key, record in cookies_map.items():
        username = record.get("username")
        nickname = record.get("nickname")
        candidates = {c for c in (key, username, nickname) if c}
        if identifier in candidates:
            target_key = key
            target_record = record
            break

    if not target_record:
        return KeepAliveResult(username=None, nickname=None, success=False, message="user not found")

    username = target_record.get("username")
    nickname = target_record.get("nickname")
    cookie_header = target_record.get("cookie") or ""

    success, updated_cookie, message = await _ping_cookie(username, nickname, cookie_header)
    if success:
        expires_at = datetime.now(timezone.utc) + refresh_interval
        manager.save_cookie(updated_cookie, expires_at, username=username, nickname=nickname)
        try:
            from . import service  # pylint: disable=cyclic-import

            updated_map, _ = manager.load_all_cookies()
            service._sync_users_from_store(updated_map)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

    return KeepAliveResult(username=username, nickname=nickname, success=success, message=message)


async def keep_alive_loop(
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    auth_manager: Optional[AuthManager] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """
    Background loop that refreshes cookies every interval.
    """
    manager = auth_manager or AuthManager()
    event = stop_event or asyncio.Event()

    logger.info("KeepAlive loop started (interval=%ss)", interval_seconds)

    while not event.is_set():
        try:
            results = await run_keep_alive_once(auth_manager=manager)
            total = len(results)
            success = sum(1 for result in results if result.success)
            logger.info("KeepAlive run completed: %s/%s success", success, total)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("KeepAlive loop error: %s", exc)

        try:
            await asyncio.wait_for(event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue

    logger.info("KeepAlive loop stopped")


async def run_keep_alive_job(
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """
    Entry point for background job execution.
    """
    stop_event = asyncio.Event()
    try:
        await keep_alive_loop(interval_seconds=interval_seconds, stop_event=stop_event)
    finally:
        stop_event.set()
