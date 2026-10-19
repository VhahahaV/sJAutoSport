"""Verify the sports session and recover it through the saved jAccount session."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from . import config as CFG
from .auth import (AuthClient, AuthManager, _cookie_header, has_sso_session,
                   restore_cookies, same_account, serialize_cookies)
from .notification import emit

_session_lock = None
_session_loop = None


@dataclass
class KeepAliveResult:
    username: Optional[str]
    nickname: Optional[str]
    success: bool
    message: str
    status: str = "online"
    sso_available: bool = False
    checked_at: Optional[str] = None


async def run_keep_alive_once(*, auth_manager=None):
    """Shared preflight for both heads and background monitors. Never replay business requests."""
    global _session_lock, _session_loop
    loop = asyncio.get_running_loop()
    if _session_loop is not loop:
        _session_loop, _session_lock = loop, asyncio.Lock()
    async with _session_lock:
        return await _check_session(auth_manager or AuthManager())


async def _check_session(manager):
    record = manager.load_record()
    result = KeepAliveResult(
        (record or {}).get("username"), (record or {}).get("nickname"), False, "请先登录",
        status="login_required", checked_at=datetime.now(timezone.utc).isoformat(),
    )
    if not record:
        return result
    result.sso_available = has_sso_session(record)
    if record.get("login_required"):
        result.message = record.get("login_required_message") or "jAccount 会话已失效或需要验证，请重新扫码或使用密码与验证码登录"
        return result

    def login_required(message):
        result.message = message
        result.sso_available = False
        if manager.mark_login_required(record, message):
            emit("login_required", {"message": message})
        else:
            result.status, result.message = "session_changed", "会话已变更，请重试"
        return result

    client = AuthClient(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH, cookies=restore_cookies(record))
    try:
        try:
            profile = await client.current_user()
            renewed = False
            if profile is None and result.sso_available and await client.reauthorize():
                profile = await client.current_user()
                renewed = profile is not None
        except (httpx.HTTPError, RuntimeError, OSError):
            # Request URLs can contain authorization codes. Do not expose exception text.
            result.status = "error"
            result.message = "校园会话检查或授权暂时不可用，原凭据已保留；请稍后重试"
            return result

        if profile is None:
            if not result.sso_available:
                return login_required("运动站会话已失效，未保存可用的 jAccount 会话；请重新登录一次以启用自动恢复")
            return login_required("jAccount 需要重新认证，请扫码或使用密码与验证码登录")

        if not same_account(record.get("username"), profile.get("loginName")):
            return login_required("校园授权返回的账号与当前账号不一致，原凭据已保留；请重新登录")
        cookie = _cookie_header(client._client.cookies, url=f"{CFG.BASE_URL}{CFG.ENDPOINTS.current_user}")
        if not cookie:
            return login_required("校园授权未返回运动站凭据，请重新登录")
        nickname = record.get("nickname")
        if nickname in (None, "", "__default__"):
            nickname = profile.get("userName") or profile["loginName"]
        saved = manager.save_cookie(
            cookie, username=profile["loginName"], nickname=nickname,
            session_cookies=serialize_cookies(client._client.cookies),
            expected_record=record, renewed=renewed,
        )
        if not saved:
            result.status, result.message = "session_changed", "会话已变更，请重试"
            return result
        result.username, result.nickname = profile["loginName"], nickname
        result.success = True
        result.status = "renewed" if renewed else "online"
        result.message = "已通过 jAccount 自动恢复运动站登录" if renewed else "运动站会话有效"
        result.sso_available = has_sso_session(manager.load_record() or {})
        if renewed:
            emit("session_renewed", {"message": result.message})
        return result
    finally:
        await client.close()
