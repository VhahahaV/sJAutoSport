"""Helper utilities for bot plugins to interact with the booking service."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console

import config as CFG
from sja_booking.auth import AuthManager
from sja_booking import service

# 使用 service 内部工具确保用户缓存同步
# pylint: disable=protected-access
from sja_booking.models import BookingTarget, UserAuth
from sja_booking.multi_user import MultiUserManager, UserBookingResult


def _auth_manager() -> AuthManager:
    return AuthManager()


def _refresh_users() -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    manager = _auth_manager()
    cookies_map, active_user = manager.load_all_cookies()
    try:
        if cookies_map:
            service._sync_users_from_store(cookies_map)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - 防御
        pass
    return cookies_map, active_user


def resolve_user(identifier: str) -> Optional[UserAuth]:
    if not identifier:
        return None
    for user in getattr(CFG.AUTH, "users", []) or []:
        if identifier in {user.username or user.nickname, user.username}:
            return user
    return None


def list_users_summary() -> Dict[str, Any]:
    cookies_map, active_user = _refresh_users()
    if not cookies_map and not getattr(CFG.AUTH, "users", None):
        return {"success": False, "message": "尚未保存任何用户"}

    users = getattr(CFG.AUTH, "users", []) or []
    entries: List[Dict[str, Any]] = []

    for key, record in cookies_map.items():
        username = record.get("username")
        nickname = record.get("nickname")
        if not nickname and username:
            match = resolve_user(username)
            nickname = match.nickname if match else username.split("@")[0]

        entry = {
            "key": key,
            "username": username,
            "nickname": nickname,
            "cookie": record.get("cookie"),
            "expires_at": record.get("expires_at"),
            "is_active": key == active_user,
        }
        entries.append(entry)

    known_usernames = {entry.get("username") for entry in entries if entry.get("username")}
    for user in users:
        if user.username and user.username in known_usernames:
            continue
        entries.append(
            {
                "key": user.nickname,
                "username": user.username,
                "nickname": user.nickname,
                "cookie": user.cookie,
                "expires_at": None,
                "is_active": False,
            }
        )

    return {
        "success": True,
        "active_user": active_user,
        "users": entries,
    }


def set_active_user(identifier: str) -> bool:
    cookies_map, _ = _refresh_users()
    manager = _auth_manager()

    candidate = resolve_user(identifier)
    if candidate and candidate.username:
        if manager.set_active_user(candidate.username):
            return True

    if identifier in cookies_map:
        return manager.set_active_user(identifier)

    if candidate and not candidate.username and candidate.cookie:
        return manager.set_active_user(candidate.nickname)

    return False


def remove_user(identifier: str) -> bool:
    removed = False
    users = getattr(CFG.AUTH, "users", []) or []
    remaining: List[UserAuth] = []
    for user in users:
        if identifier not in {user.nickname, user.username}:
            remaining.append(user)
        else:
            removed = True
    CFG.AUTH.users = remaining

    manager = _auth_manager()
    if removed and identifier:
        manager.delete_user(identifier)
    else:
        candidate = resolve_user(identifier)
        if candidate:
            manager.delete_user(candidate.username or candidate.nickname)
            removed = True
    return removed


def summarize_users_text() -> str:
    summary = list_users_summary()
    if not summary.get("success"):
        return summary.get("message", "尚未保存任何用户")

    lines = []
    lines.append("👥 当前已保存的用户：")
    for entry in summary["users"]:
        nickname = entry.get("nickname") or entry.get("username") or entry.get("key")
        username = entry.get("username") or "未设置"
        expires = entry.get("expires_at") or "未知"
        status = "🟢" if entry.get("is_active") else "⚪"
        lines.append(f"{status} {nickname} ({username}) - 有效期至 {expires}")
    return "\n".join(lines)


def build_target(base_target: Optional[BookingTarget], target_users: Optional[List[str]], exclude_users: Optional[List[str]]) -> BookingTarget:
    working = dataclasses.replace(base_target or getattr(CFG, "TARGET", BookingTarget()))
    if target_users is not None:
        working.target_users = [user.strip() for user in target_users if user.strip()]
    if exclude_users is not None:
        working.exclude_users = [user.strip() for user in exclude_users if user.strip()]
    return working


async def order_for_users(
    *,
    preset: int,
    date: str,
    start_time: str,
    end_time: Optional[str] = None,
    base_target: Optional[BookingTarget] = None,
    target_users: Optional[List[str]] = None,
    exclude_users: Optional[List[str]] = None,
) -> List[UserBookingResult]:
    _refresh_users()
    working_target = build_target(base_target, target_users, exclude_users)
    manager = MultiUserManager(CFG.AUTH, Console(width=80, record=True))
    users = manager.get_users_for_booking(working_target)

    results: List[UserBookingResult] = []
    if not users:
        return results

    for index, user in enumerate(users, 1):
        try:
            result = await service.order_once(
                preset=preset,
                date=date,
                start_time=start_time,
                end_time=end_time,
                base_target=working_target,
                user=user.nickname,
            )
            results.append(
                UserBookingResult(
                    nickname=user.nickname,
                    success=result.success,
                    message=result.message,
                    order_id=result.order_id,
                    error=None if result.success else result.message,
                )
            )
        except Exception as exc:  # pylint: disable=broad-except
            results.append(
                UserBookingResult(
                    nickname=user.nickname,
                    success=False,
                    message="预订失败",
                    error=str(exc),
                )
            )
        if index < len(users):
            await asyncio.sleep(2.5)
