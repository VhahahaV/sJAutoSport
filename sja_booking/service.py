"""Single-account booking, login and task orchestration."""
from __future__ import annotations
import asyncio
import dataclasses
import hashlib
import json
import logging
import re
import threading
import time
import uuid
import httpx
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse
from . import config as CFG
from .api import SportsAPI
from .auth import AuthManager, AuthClient, AuthState, _cookie_header, authenticated_user, has_sso_session, serialize_cookies
from .keep_alive import run_keep_alive_once
from .models import BookingTarget, DateAvailability, FieldType, MonitorPlan, PresetOption, Slot, UserAuth, Venue, AuthConfig
from .monitor import SlotMonitor
from .order import OrderManager, OrderResult
from .database import get_db_manager
from .notification import emit

logger = logging.getLogger(__name__)
_auth_manager = AuthManager()
_login_sessions = {}
_qr_sessions = {}
_LOGIN_SESSION_TIMEOUT = timedelta(minutes=5)
_active_monitors = {}
_paused_monitors = {}
_task_handles = {}
_order_lock = None
_booking_mutex = threading.RLock()
_booking_manager = None
_booking_session = None
_booking_created = 0
_slot_snapshots = {}
_SNAPSHOT_SECONDS = 60

@dataclass
class ResolvedTarget:
    """Resolved booking target with metadata for presentation layers."""

    target: BookingTarget
    venue_id: str
    venue_name: Optional[str]
    field_type_id: str
    field_type_name: Optional[str]
    preset: Optional[PresetOption] = None

    @property
    def label(self) -> str:
        venue = self.venue_name or self.preset.venue_name if self.preset else self.venue_id
        field = self.field_type_name or self.preset.field_type_name if self.preset else self.field_type_id
        return f"{venue} / {field}"


@dataclass
class SlotAvailability:
    """Single slot availability entry bound to a booking date."""

    date: str
    slot: Slot

    @property
    def start(self) -> str:
        return str(self.slot.start)

    @property
    def end(self) -> str:
        return str(self.slot.end)

    @property
    def price(self) -> Optional[float]:
        return self.slot.price

    @property
    def remain(self) -> Optional[int]:
        return self.slot.remain

    @property
    def available(self) -> bool:
        return self.slot.available


@dataclass
class SlotListResult:
    resolved: ResolvedTarget
    slots: List[SlotAvailability]
    snapshot_id: Optional[str] = None
    expires_at: Optional[str] = None
    timings_ms: Dict[str, float] = dataclasses.field(default_factory=dict)


@dataclass
class DateAvailabilityResult:
    resolved: ResolvedTarget
    dates: List[DateAvailability]

    @property
    def default_date(self) -> Optional[str]:
        for entry in self.dates:
            if entry.selectable:
                return entry.date
        return self.dates[0].date if self.dates else None


def _slot_label_to_hour(label: Any) -> Optional[int]:
    text = str(label).strip()
    if not text:
        return None
    if text.startswith("slot-"):
        remainder = text[5:]
        if remainder.isdigit():
            return (7 + int(remainder)) % 24
        return None
    if ":" in text:
        hour_part = text.split(":", 1)[0]
        if hour_part.isdigit():
            return int(hour_part)
    if text.isdigit():
        return int(text)
    return None


def _normalise_slot_times(slot: Slot) -> Optional[int]:
    hour = _slot_label_to_hour(slot.start)
    if hour is not None and ":" not in str(slot.start):
        slot.start = f"{hour:02d}:00"

    end_hour = _slot_label_to_hour(slot.end)
    if end_hour is not None and ":" not in str(slot.end):
        slot.end = f"{end_hour:02d}:00"
    elif end_hour is None and hour is not None:
        slot.end = f"{(hour + 1) % 24:02d}:00"
    return hour


def _list_venues_sync(
    *,
    keyword: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    flag: int = 0,
) -> List[Venue]:
    api = _create_api()
    try:
        return api.list_venues(keyword=keyword, page=page, size=size, flag=flag)
    finally:
        api.close()


async def list_venues(
    *,
    keyword: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    flag: int = 0,
) -> List[Venue]:
    return await asyncio.to_thread(
        _list_venues_sync,
        keyword=keyword,
        page=page,
        size=size,
        flag=flag,
    )


def _list_field_types_sync(venue_id: str) -> List[FieldType]:
    api = _create_api()
    try:
        detail = api.get_venue_detail(venue_id)
        return api.list_field_types(detail)
    finally:
        api.close()


async def list_field_types(venue_id: str) -> List[FieldType]:
    return await asyncio.to_thread(_list_field_types_sync, venue_id)


def _list_date_availability_sync(
    venue_id: str,
    field_type_id: str,
) -> List[DateAvailability]:
    api = _create_api()
    try:
        return api.list_date_availability(venue_id, field_type_id)
    finally:
        api.close()


async def list_date_availability(
    *,
    preset: Optional[int] = None,
    venue_id: Optional[str] = None,
    field_type_id: Optional[str] = None,
    base_target: Optional[BookingTarget] = None,
) -> DateAvailabilityResult:
    resolved = await resolve_preset_or_ids(
        preset=preset,
        venue_id=venue_id,
        field_type_id=field_type_id,
        base_target=base_target,
    )
    dates = await asyncio.to_thread(
        _list_date_availability_sync,
        resolved.venue_id,
        resolved.field_type_id,
    )
    # Ensure consistent ordering and deduplicate by date
    seen: Dict[str, DateAvailability] = {}
    for entry in dates:
        if entry.date not in seen or entry.selectable:
            seen[entry.date] = entry
    ordered_all = sorted(seen.values(), key=lambda item: item.date)
    ordered = [entry for entry in ordered_all if entry.selectable]
    return DateAvailabilityResult(resolved=resolved, dates=ordered)


def _normalize_user_payload(payload: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "success": False,
        "message": None,
        "raw": payload,
        "profile": None,
    }
    if not isinstance(payload, dict):
        result["message"] = "unexpected response format"
        return result

    code = payload.get("code")
    if code in (None, 0, "0") and not payload.get("error"):
        result["success"] = True
    else:
        result["message"] = payload.get("msg") or payload.get("message") or payload.get("error")
        return result

    user_info = authenticated_user(payload)
    if user_info is None:
        result.update(success=False, message="未获得有效的用户资料，请刷新重试或重新登录")
        return result

    if isinstance(user_info, dict):
        dept = user_info.get("dept")
        if isinstance(dept, dict):
            dept = dept.get("deptName")

        roles: List[str] = []
        if isinstance(user_info.get("roles"), list):
            for role in user_info["roles"]:
                if isinstance(role, dict) and "roleName" in role:
                    roles.append(str(role["roleName"]))
                elif isinstance(role, str):
                    roles.append(role)

        profile = {
            "create_time": user_info.get("createTime"),
            "login_name": user_info.get("loginName"),
            "user_name": user_info.get("userName"),
            "phone": user_info.get("phonenumber"),
            "sex": user_info.get("sex"),
            "dept": dept,
            "code": user_info.get("code"),
            "class_no": user_info.get("classNo"),
            "admin": user_info.get("admin"),
            "roles": roles,
        }
        if profile["login_name"] or profile["user_name"]:
            result["profile"] = profile
        else:
            result["success"] = False
            result["message"] = "未获得有效的用户资料，请刷新重试或重新登录"
    return result


def _clone_target(base: BookingTarget) -> BookingTarget:
    return dataclasses.replace(base, fixed_dates=list(base.fixed_dates))


def _iter_presets() -> Iterable[PresetOption]:
    return getattr(CFG, "PRESET_TARGETS", []) or []


def _get_preset(index: Optional[int]) -> Optional[PresetOption]:
    if index is None:
        return None
    for option in _iter_presets():
        if option.index == index:
            return option
    raise ValueError(f"unknown preset index: {index}")


def _parse_date_input(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("date value cannot be empty")
    if text.isdigit():
        offset = int(text)
        target_date = datetime.now() + timedelta(days=offset)
        return target_date.strftime("%Y-%m-%d")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"invalid date format: {text}") from exc
    return text


def _parse_time_input(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("time value cannot be empty")
    if text.isdigit():
        hour = int(text)
        if not 0 <= hour <= 23:
            raise ValueError("hour must be within 0-23")
        return f"{hour:02d}:00"
    parts = text.split(":")
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        hour = int(parts[0])
        minute = int(parts[1])
        if not 0 <= hour <= 23:
            raise ValueError("hour must be within 0-23")
        if not 0 <= minute <= 59:
            raise ValueError("minute must be within 0-59")
        return f"{hour:02d}:{minute:02d}"
    raise ValueError(f"invalid time format: {value}")


def _next_hour(time_text: str, duration_hours: int = 1) -> str:
    base = datetime.strptime(time_text, "%H:%M")
    result = base + timedelta(hours=duration_hours)
    return result.strftime("%H:%M")


def _filter_slots_by_start(slots: List[Tuple[str, Slot]], start_hour: Optional[int]) -> List[SlotAvailability]:
    results: List[SlotAvailability] = []
    for date_str, slot in slots:
        slot_hour = _normalise_slot_times(slot)
        if start_hour is not None:
            if slot_hour is None or slot_hour != start_hour:
                continue
        results.append(SlotAvailability(date=date_str, slot=slot))
    return results


def _resolve_target_sync(
    *,
    preset: Optional[int],
    venue_id: Optional[str],
    field_type_id: Optional[str],
    base_target: Optional[BookingTarget],
) -> ResolvedTarget:
    api = _create_api()
    try:
        preset_option = _get_preset(preset)
        reference_target = base_target or getattr(CFG, "TARGET", BookingTarget())
        target_template = _clone_target(reference_target)
        if preset_option:
            target_template.venue_id = preset_option.venue_id
            target_template.venue_keyword = preset_option.venue_name
            target_template.field_type_id = preset_option.field_type_id
            target_template.field_type_keyword = preset_option.field_type_name
            if preset_option.field_type_code:
                target_template.field_type_code = preset_option.field_type_code
        if venue_id:
            target_template.venue_id = venue_id
        if field_type_id:
            target_template.field_type_id = field_type_id

        monitor = SlotMonitor(api, target_template, MonitorPlan(enabled=False), console=None)
        monitor.resolve_context()

        # sync identifiers back to the template so callers reuse populated values
        target_template.venue_id = monitor._venue_id or target_template.venue_id  # type: ignore[attr-defined]
        target_template.field_type_id = monitor._field_type_id or target_template.field_type_id  # type: ignore[attr-defined]
        if not target_template.venue_keyword and monitor._venue_name:  # type: ignore[attr-defined]
            target_template.venue_keyword = monitor._venue_name  # type: ignore[attr-defined]
        if not target_template.field_type_keyword and monitor._field_type_name:  # type: ignore[attr-defined]
            target_template.field_type_keyword = monitor._field_type_name  # type: ignore[attr-defined]
        if monitor._field_type_info and monitor._field_type_info.category and not target_template.field_type_code:  # type: ignore[attr-defined]
            target_template.field_type_code = monitor._field_type_info.category  # type: ignore[attr-defined]

        resolved_target = ResolvedTarget(
            target=target_template,
            venue_id=monitor._venue_id or target_template.venue_id or "",  # type: ignore[attr-defined]
            venue_name=monitor._venue_name,  # type: ignore[attr-defined]
            field_type_id=monitor._field_type_id or target_template.field_type_id or "",  # type: ignore[attr-defined]
            field_type_name=monitor._field_type_name,  # type: ignore[attr-defined]
            preset=preset_option,
        )
        return resolved_target
    finally:
        api.close()


async def resolve_preset_or_ids(
    *,
    preset: Optional[int] = None,
    venue_id: Optional[str] = None,
    field_type_id: Optional[str] = None,
    base_target: Optional[BookingTarget] = None,
) -> ResolvedTarget:
    return await asyncio.to_thread(
        _resolve_target_sync,
        preset=preset,
        venue_id=venue_id,
        field_type_id=field_type_id,
        base_target=base_target,
    )


def _list_slots_sync(
    *,
    preset: Optional[int],
    venue_id: Optional[str],
    field_type_id: Optional[str],
    date: Optional[str],
    start_hour: Optional[int],
    show_full: bool,
    base_target: Optional[BookingTarget],
    all_dates: bool,
) -> SlotListResult:
    option = _get_preset(preset)
    if option and date is not None and not venue_id and not field_type_id:
        parsed = _parse_date_input(date)
        with _booking_mutex:
            manager = _get_booking_manager()
            manager.api.timings_ms.clear()
            slots = manager.query_day(option, parsed)
            for slot in slots:
                _normalise_slot_times(slot)
            slots = [SlotAvailability(parsed, slot) for slot in slots
                     if (show_full or slot.available) and (start_hour is None or int(slot.start[:2]) >= start_hour)]
            target = _clone_target(base_target or CFG.TARGET)
            target.venue_id, target.field_type_id = option.venue_id, option.field_type_id
            return SlotListResult(ResolvedTarget(target, option.venue_id, option.venue_name,
                                                option.field_type_id, option.field_type_name, option),
                                  slots, timings_ms=dict(manager.api.timings_ms))
    api = _create_api()
    try:
        preset_option = _get_preset(preset)
        reference_target = base_target or getattr(CFG, "TARGET", BookingTarget())
        target = _clone_target(reference_target)
        if preset_option:
            target.venue_id = preset_option.venue_id
            target.venue_keyword = preset_option.venue_name
            target.field_type_id = preset_option.field_type_id
            target.field_type_keyword = preset_option.field_type_name
            if preset_option.field_type_code:
                target.field_type_code = preset_option.field_type_code

        if venue_id:
            target.venue_id = venue_id
        if field_type_id:
            target.field_type_id = field_type_id

        if all_dates:
            target.fixed_dates = []
            target.use_all_dates = True
            target.date_offset = None

        if date is not None:
            parsed_date = _parse_date_input(str(date))
            target.fixed_dates = [parsed_date]
            target.use_all_dates = False
            target.date_offset = None

        monitor = SlotMonitor(api, target, MonitorPlan(enabled=False), console=None)
        raw_slots = monitor.run_once(include_full=show_full)
        venue_id = monitor._venue_id or target.venue_id or ""  # type: ignore[attr-defined]
        venue_name = monitor._venue_name or target.venue_keyword  # type: ignore[attr-defined]
        field_type_id = monitor._field_type_id or target.field_type_id or ""  # type: ignore[attr-defined]
        field_type_name = monitor._field_type_name or target.field_type_keyword  # type: ignore[attr-defined]
        if monitor._field_type_info and monitor._field_type_info.category and not target.field_type_code:  # type: ignore[attr-defined]
            target.field_type_code = monitor._field_type_info.category  # type: ignore[attr-defined]

        filtered = _filter_slots_by_start(raw_slots, start_hour)
        resolved = ResolvedTarget(
            target=target,
            venue_id=venue_id,
            venue_name=venue_name,
            field_type_id=field_type_id,
            field_type_name=field_type_name,
            preset=preset_option,
        )

        return SlotListResult(resolved=resolved, slots=filtered)
    finally:
        api.close()


async def list_slots(
    *,
    preset: Optional[int] = None,
    venue_id: Optional[str] = None,
    field_type_id: Optional[str] = None,
    date: Optional[str] = None,
    start_hour: Optional[int] = None,
    show_full: bool = False,
    base_target: Optional[BookingTarget] = None,
    all_dates: bool = False,
) -> SlotListResult:
    session = _session_key()
    queried_at = time.monotonic()
    result = await asyncio.to_thread(
        _list_slots_sync,
        preset=preset,
        venue_id=venue_id,
        field_type_id=field_type_id,
        date=date,
        start_hour=start_hour,
        show_full=show_full,
        base_target=base_target,
        all_dates=all_dates,
    )
    if session != _session_key():
        raise RuntimeError("查询期间登录会话发生变化，请重新查询")
    now = time.monotonic()
    for key, snapshot in list(_slot_snapshots.items()):
        if snapshot["expires"] <= now or snapshot["session"] != session:
            del _slot_snapshots[key]
    while len(_slot_snapshots) >= 32:
        del _slot_snapshots[next(iter(_slot_snapshots))]
    result.snapshot_id = uuid.uuid4().hex
    remaining = max(0, queried_at + _SNAPSHOT_SECONDS - now)
    result.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=remaining)).isoformat()
    _slot_snapshots[result.snapshot_id] = {
        "session": session, "expires": queried_at + _SNAPSHOT_SECONDS, "result": result,
    }
    return result


def _order_once_sync(
    *,
    preset: int,
    date: str,
    start_time: str,
    end_time: Optional[str],
    base_target: Optional[BookingTarget],
    cached_slot=None,
    expected_session=None,
    cached_slots=None,
    cascade=None,
    deadline=None,
) -> OrderResult:
    with _booking_mutex:
        if expected_session and expected_session != _session_key():
            return OrderResult(False, "登录会话已变化，请重新查询场次", status="not_submitted")
        manager = _get_booking_manager()
        manager.api.timings_ms.clear()
        parsed_date = _parse_date_input(date)
        start_label = _parse_time_input(start_time)
        if end_time:
            end_label = _parse_time_input(end_time)
        else:
            reference_target = base_target or getattr(CFG, "TARGET", BookingTarget())
            end_label = _next_hour(start_label, reference_target.duration_hours if reference_target.duration_hours else 1)
        def still_valid():
            return (expected_session == _session_key()
                    and (deadline is None or time.monotonic() < deadline))
        if cascade:
            option = _get_preset(preset)
            try:
                manager._get_field_type_info(option)
                slots = cached_slots if cached_slots is not None else manager.query_day(option, parsed_date)
            except (httpx.HTTPError, RuntimeError, ValueError):
                return OrderResult(False, "候选场次查询失败，本次未下单", status="not_submitted",
                                   timings_ms=dict(manager.api.timings_ms))
            for slot in slots:
                _normalise_slot_times(slot)
            return manager.place_candidates(option, parsed_date, slots, still_valid=still_valid, **cascade)
        if cached_slot is not None:
            option = _get_preset(preset)
            manager._get_field_type_info(option)
            if not still_valid():
                return OrderResult(False, "查询已过期或登录已变化，请重新查询场次", status="not_submitted")
            return manager.place_order(cached_slot, option, parsed_date, start_label, end_label)
        result = manager.place_order_by_preset(
            preset_index=preset,
            date=parsed_date,
            start_time=start_label,
            end_time=end_label,
            still_valid=still_valid,
        )
        return result


@dataclass
class LoginSession:
    session_id: str
    client: AuthClient
    state: AuthState
    username: str
    password: str
    created_at: datetime
    attempts: int = 0
    nickname: Optional[str] = None


async def start_login_session(
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    nickname: Optional[str] = None,
) -> Dict[str, Any]:
    """启动登录流程，必要时返回验证码图片。"""
    initialize_database()
    for pending_id in list(_qr_sessions):
        await cancel_qr_login(pending_id)
    for pending_id in list(_login_sessions):
        await cancel_login_session(pending_id)
    resolved_user, resolved_pass = _resolve_credentials(
        username,
        password,
        nickname=nickname,
    )
    if not resolved_user or not resolved_pass:
        return {"success": False, "message": "未配置登录凭据（用户名或密码缺失）"}

    client = AuthClient(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH)
    try:
        state = await client.prepare()
    except Exception as exc:  # pylint: disable=broad-except
        await client.close()
        return {"success": False, "message": f"登录初始化失败: {exc}"}

    session_id = f"login_{uuid.uuid4().hex}"
    session = LoginSession(
        session_id=session_id,
        client=client,
        state=state,
        username=resolved_user,
        password=resolved_pass,
        created_at=datetime.now(timezone.utc),
        nickname=nickname,
    )

    if state.captcha_required:
        try:
            image = await client.fetch_captcha(state)
        except Exception as exc:  # pylint: disable=broad-except
            await client.close()
            return {"success": False, "message": f"获取验证码失败: {exc}"}
        _login_sessions[session_id] = session
        return {
            "success": True,
            "captcha_required": True,
            "session_id": session_id,
            "captcha_image": image,
            "message": "已生成验证码，请在 5 分钟内输入",
            "username": resolved_user,
            "nickname": nickname,
        }

    # 无验证码，直接尝试登录
    try:
        submit_resp = await client.submit(state, resolved_user, resolved_pass, None)
        await client.follow_redirects(submit_resp)
        cookie_header = _cookie_header(client._client.cookies, url=f"{CFG.BASE_URL}{CFG.ENDPOINTS.current_user}")
        if not cookie_header:
            raise RuntimeError("登录失败，未获得 Cookie")

        resolved_nickname = await asyncio.to_thread(
            _save_verified_login, resolved_user, nickname, cookie_header,
            session_cookies=serialize_cookies(client._client.cookies),
        )

        await client.close()
        return {
            "success": True,
            "captcha_required": False,
            "message": "登录成功",
            "expires_at": None,
            "username": resolved_user,
            "nickname": resolved_nickname,
        }
    except Exception as exc:  # pylint: disable=broad-except
        await client.close()
        return {"success": False, "message": f"登录失败: {exc}"}


async def submit_login_session_code(session_id: str, code: str) -> Dict[str, Any]:
    """提交验证码，继续登录流程。"""
    session = _login_sessions.get(session_id)
    if not session:
        return {"success": False, "message": "登录会话不存在或已过期"}

    if datetime.now(timezone.utc) - session.created_at > _LOGIN_SESSION_TIMEOUT:
        await session.client.close()
        del _login_sessions[session_id]
        return {"success": False, "message": "登录会话已超时，请重新开始"}

    session.attempts += 1
    try:
        submit_resp = await session.client.submit(session.state, session.username, session.password, code)
        await session.client.follow_redirects(submit_resp)

        cookie_header = _cookie_header(session.client._client.cookies, url=f"{CFG.BASE_URL}{CFG.ENDPOINTS.current_user}")
        if not cookie_header:
            raise RuntimeError("验证码可能错误，未获取到 Cookie")

        resolved_nickname = await asyncio.to_thread(
            _save_verified_login, session.username, session.nickname, cookie_header,
            session_cookies=serialize_cookies(session.client._client.cookies),
        )

        await session.client.close()
        del _login_sessions[session_id]
        return {
            "success": True,
            "message": "登录成功",
            "expires_at": None,
            "username": session.username,
            "nickname": resolved_nickname,
        }
    except Exception as exc:  # pylint: disable=broad-except
        if session.attempts >= 5:  # 增加到5次重试
            await session.client.close()
            del _login_sessions[session_id]
            return {"success": False, "message": f"验证码错误次数过多（已尝试5次）: {exc}"}

        # 重试：等待10秒后重新获取验证码
        await asyncio.sleep(10.0)
        
        try:
            state = await session.client.prepare()
            session.state = state
            session.created_at = datetime.now(timezone.utc)
            if state.captcha_required:
                image = await session.client.fetch_captcha(state)
                return {
                    "success": False,
                    "retry": True,
                    "session_id": session_id,
                    "captcha_image": image,
                    "message": f"登录未完成，请核对账号、密码和新验证码后重试 ({session.attempts}/5): {exc}",
                    "username": session.username,
                    "nickname": session.nickname,
                }
            await session.client.close()
            del _login_sessions[session_id]
            return {"success": False, "message": f"验证码错误: {exc}"}
        except Exception as inner_exc:  # pylint: disable=broad-except
            await session.client.close()
            del _login_sessions[session_id]
            return {"success": False, "message": f"验证码处理失败: {inner_exc}"}


async def cancel_login_session(session_id: str) -> Dict[str, Any]:
    """取消正在进行的登录流程。"""
    session = _login_sessions.pop(session_id, None)
    if not session:
        return {"success": False, "message": "未找到对应的登录会话"}
    try:
        await session.client.close()
    except Exception:  # pylint: disable=broad-except
        pass
    return {"success": True, "message": "已取消登录流程"}


def initialize_database():
    db = get_db_manager()
    return {"initialized": True, "database": str(db.db_path)}


def current_account():
    record = _auth_manager.load_record()
    if record:
        CFG.AUTH.user = UserAuth(username=record.get("username"), nickname=record.get("nickname") or record.get("username") or "Account", cookie=record["cookie"])
    else:
        CFG.AUTH.user = None
    return record


def _create_api():
    current_account()
    # Freeze credentials for this request chain; keepalive may replace CFG.AUTH.
    auth = AuthConfig(user=dataclasses.replace(CFG.AUTH.user) if CFG.AUTH.user else None)
    return SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, auth, preset_targets=list(_iter_presets()))


def _session_key():
    record = _auth_manager.load_record() or {}
    return hashlib.sha256(f'{record.get("username", "")}\0{record.get("cookie", "")}'.encode()).hexdigest()


def _get_booking_manager():
    """Called under _booking_mutex; reuse a connection and metadata for ten minutes."""
    global _booking_manager, _booking_session, _booking_created
    session = _session_key()
    if _booking_manager is None or _booking_session != session or time.monotonic() - _booking_created > 600:
        if _booking_manager is not None:
            _booking_manager.api.close()
        _booking_manager = OrderManager(_create_api(), CFG.ENCRYPTION_CONFIG)
        _booking_session, _booking_created = session, time.monotonic()
    return _booking_manager


def _resolve_credentials(username, password, *, nickname=None):
    current_account()
    account = CFG.AUTH.user
    return (username or (account.username if account else None),
            password or (account.password if account and account.username == username else None))


def _save_verified_login(username, nickname, cookie_header, expires_at=None, *, session_cookies=None):
    resolved = nickname or username.split("@", 1)[0]
    candidate = UserAuth(username=username, nickname=resolved, cookie=cookie_header)
    api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, AuthConfig(user=candidate))
    try:
        if not api.check_auth_status():
            raise RuntimeError("登录校验失败，原凭据已保留")
    finally:
        api.close()
    _auth_manager.save_cookie(cookie_header, expires_at, username=username, nickname=resolved,
                              session_cookies=session_cookies)
    CFG.AUTH.user = candidate
    return resolved


async def login_status():
    result = await run_keep_alive_once(auth_manager=_auth_manager)
    if result.status in {"error", "session_changed"}:
        raise RuntimeError(result.message)
    record = current_account()
    account = None if not record else {
        "username": record.get("username"), "nickname": record.get("nickname"),
        "expires_at": None, "is_online": result.success,
        "sso_available": result.sso_available, "verified_at": record.get("verified_at"),
        "renewed_at": record.get("renewed_at"),
    }
    return {"success": result.success, "account": account, "status": result.status, "message": result.message}


async def require_authenticated():
    status = await login_status()
    if not status["success"]:
        raise PermissionError(status["message"])


async def fetch_user_info():
    def fetch():
        api = _create_api()
        cookie = CFG.AUTH.user.cookie if CFG.AUTH.user else None
        try:
            result = _normalize_user_payload(api.check_login())
            if result["success"] and result["profile"]:
                profile = result["profile"]
                _auth_manager.update_identity(cookie, username=profile["login_name"], nickname=profile["user_name"])
                current_account()
            return result
        finally:
            api.close()
    return await asyncio.to_thread(fetch)


def clear_account():
    global _booking_manager
    _auth_manager.clear()
    CFG.AUTH.user = None
    _slot_snapshots.clear()
    with _booking_mutex:
        if _booking_manager is not None:
            _booking_manager.api.close()
            _booking_manager = None
    return {"success": True, "message": "已退出登录"}


def _order_account_key(record):
    return hashlib.sha256(str(record.get("username") or "").strip().lower().encode()).hexdigest()


def _attempt_result(attempt):
    if attempt.get("result"):
        return OrderResult(**attempt["result"])
    return OrderResult(False, "之前的预约尚未确认结果，请先核对订单；当前请求不会再次下单",
                       status="unknown", request_id=attempt["request_id"])


async def order_once(*, preset, date, start_time, end_time=None, base_target=None,
                     request_id=None, snapshot_id=None, candidate_id=None, _cascade=None):
    global _order_lock
    if _order_lock is None:
        _order_lock = asyncio.Lock()
    async with _order_lock:
        account = current_account()
        if not account:
            raise PermissionError("请先登录")
        date = _parse_date_input(date)
        start_time = _parse_time_input(start_time)
        end_time = _parse_time_input(end_time) if end_time else _next_hour(start_time, (base_target or CFG.TARGET).duration_hours)
        option = _get_preset(preset)
        if not option:
            raise ValueError("无效的场馆预设")
        scope = f"{option.venue_id}:{option.field_type_id}"
        db = get_db_manager()
        account_key = _order_account_key(account)
        request_id = request_id or str(uuid.uuid4())
        intent = {"preset": preset, "date": date, "start_time": start_time, "end_time": end_time}
        if snapshot_id or candidate_id:
            intent.update(snapshot_id=snapshot_id, candidate_id=candidate_id)
        if _cascade:
            intent["cascade"] = _cascade
        previous = db.get("order_attempt", request_id)
        if previous:
            if previous["account_key"] != account_key or previous["intent"] != intent:
                raise ValueError("request_id 已用于另一个预约，请勿改变同一请求的参数")
            return _attempt_result(previous)
        pending = next((item for item in db.all("order_attempt")
                        if item["account_key"] == account_key and item["status"] in {"submitting", "unknown"}), None)
        if pending:
            return _attempt_result(pending)
        cached_slot = None
        cached_slots, deadline = None, None
        session = _session_key()
        if candidate_id and not snapshot_id:
            raise ValueError("candidate_id 必须与 snapshot_id 一起使用")
        if snapshot_id:
            snapshot = _slot_snapshots.get(snapshot_id)
            if not snapshot or snapshot["expires"] <= time.monotonic() or snapshot["session"] != session:
                return OrderResult(False, "场次查询已过期或登录已变化，请刷新余位后重新选择", status="not_submitted",
                                   request_id=request_id)
            prepared = snapshot["result"]
            deadline = snapshot["expires"]
            if (prepared.resolved.venue_id, prepared.resolved.field_type_id) != (option.venue_id, option.field_type_id):
                raise ValueError("snapshot_id 与场馆或运动不匹配")
            if _cascade:
                cached_slots = [entry.slot for entry in prepared.slots if entry.date == date]
            else:
                cached_slot = next((entry.slot for entry in prepared.slots
                                if entry.date == date and entry.start == start_time and entry.end == end_time
                                and entry.available and (not candidate_id or entry.slot.slot_id == candidate_id)), None)
            if cached_slot is None and not _cascade:
                return OrderResult(False, "该查询中没有匹配的可预约场次，请重新选择", status="not_submitted",
                                   request_id=request_id)
        existing = await db.get_reservation(scope, date)
        if existing:
            return OrderResult(False, "该项目当天已有预约，请先查询订单，避免重复下单", existing.get("order_id"),
                               status="not_submitted", request_id=request_id)
        attempt = {"request_id": request_id, "account_key": account_key, "scope": scope, "intent": intent,
                   "status": "submitting", "started_at": datetime.now(timezone.utc).isoformat()}
        # Persist before starting the thread: cancellation or a crash must not allow a second submission.
        db.put("order_attempt", request_id, attempt)
        async def execute():
            try:
                return await asyncio.to_thread(_order_once_sync, preset=preset, date=date, start_time=start_time,
                                               end_time=end_time, base_target=base_target, cached_slot=cached_slot,
                                               expected_session=session, cascade=_cascade,
                                               cached_slots=cached_slots, deadline=deadline)
            except Exception as exc:
                # An internal error may occur after the remote side effect.
                logger.error("Order execution interrupted (%s)", type(exc).__name__)
                return OrderResult(False, "预约执行异常，结果待核对，请先查询订单", status="unknown")

        execution = asyncio.create_task(execute())
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(execution)
                break
            except asyncio.CancelledError:
                # A synchronous HTTP request keeps running after task cancellation.
                # Keep the lock until its result is durably recorded.
                cancelled = True
                if execution.cancelled():
                    result = OrderResult(False, "预约任务被中断，结果待核对", status="unknown")
                    break
        result.request_id = request_id
        if result.status != "not_submitted" and snapshot_id:
            _slot_snapshots.pop(snapshot_id, None)
        order_id = result.order_id
        if result.attempts:
            start_time, end_time = result.attempts[-1]["start_time"], result.attempts[-1]["end_time"]
        await db.save_booking_record(order_id or "", preset, option.venue_name, option.field_type_name, date, start_time, end_time,
                                     result.status, result.message)
        if result.success:
            await db.save_reservation(scope, date, order_id, result.message)
        attempt.update(status=result.status, result={key: value for key, value in dataclasses.asdict(result).items()
                                                    if key != "raw_response"})
        db.put("order_attempt", request_id, attempt)
        emit("order", {"success": result.success, "status": result.status, "request_id": request_id,
                       "message": result.message, "order_id": order_id, "date": date,
                       "start_time": start_time, "end_time": end_time, "venue_name": option.venue_name})
        if cancelled:
            raise asyncio.CancelledError
        return result


async def order_cascade(*, preset, date, preferences, max_price, max_attempts, request_id,
                        snapshot_id=None, continue_on_codes=None):
    preferences = [{**p, "start_time": _parse_time_input(p["start_time"]),
                    "end_time": _parse_time_input(p["end_time"]) if p.get("end_time") else _next_hour(p["start_time"])}
                   for p in preferences]
    cascade = {"preferences": preferences, "max_price": max_price, "max_attempts": max_attempts,
               "continue_on_codes": continue_on_codes or []}
    return await order_once(preset=preset, date=date, start_time=preferences[0]["start_time"],
                            end_time=preferences[0]["end_time"], request_id=request_id, snapshot_id=snapshot_id,
                            _cascade=cascade)


async def cancel_order(order_id):
    api = _create_api()
    try:
        steps = await asyncio.to_thread(api.cancel_order, order_id)
        await get_db_manager().delete_reservation_by_order_id(order_id)
        emit("order_cancelled", {"order_id": order_id})
        return {"success": True, "message": "取消/退款流程已提交", "steps": steps}
    finally:
        api.close()


def _matching_order_sync(intent):
    """Find positive evidence only. No match does not prove that a POST failed."""
    option = _get_preset(intent["preset"])
    api = _create_api()
    preferences = intent.get("cascade", {}).get("preferences") or [intent]
    try:
        page, seen = 1, set()
        while True:
            payload = api.list_orders(page_no=page, page_size=100)
            if not isinstance(payload, dict) or payload.get("code") not in (None, 0, "0"):
                raise RuntimeError("订单核对失败，仍保留待确认状态")
            rows = payload.get("records")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise RuntimeError("订单列表格式异常，仍保留待确认状态")
            for row in rows:
                order_id = row.get("pOrderid")
                if (str(row.get("venueid")) == option.venue_id
                        and str(row.get("venid")) == option.field_type_id
                        and str(row.get("scDate") or row.get("scdate") or "")[:10] == intent["date"]
                        and any(re.search(rf'(?<!\d){re.escape(p["start_time"])}\s*-\s*{re.escape(p["end_time"])}(?!\d)',
                                          str(row.get("spaceInfo") or "")) for p in preferences)
                        and str(row.get("orderstateid")) in {"0", "1", "9"}
                        and isinstance(order_id, (str, int)) and not isinstance(order_id, bool)
                        and str(order_id)):
                    return str(order_id)
            ids = {str(row.get("pOrderid")) for row in rows}
            if not rows or len(rows) < 100:
                return None
            if ids <= seen or page >= 100:
                raise RuntimeError("订单分页未能完整核对，仍保留待确认状态")
            seen.update(ids)
            page += 1
    finally:
        api.close()


async def reconcile_order(*, request_id, confirm_not_created=False):
    global _order_lock
    if _order_lock is None:
        _order_lock = asyncio.Lock()
    async with _order_lock:
        record = current_account()
        if not record:
            raise PermissionError("请先登录")
        db = get_db_manager()
        attempt = db.get("order_attempt", request_id)
        if not attempt or attempt["account_key"] != _order_account_key(record):
            raise ValueError("当前账号不存在该预约请求")
        if attempt["status"] not in {"submitting", "unknown"}:
            return _attempt_result(attempt)
        response_info = (attempt.get("result") or {}).get("response_info", {})
        order_id = await asyncio.to_thread(_matching_order_sync, attempt["intent"])
        if order_id:
            result = OrderResult(True, "已查到目标时段的有效预约，已阻止重复提交", order_id,
                                 status="success", request_id=request_id, response_info=response_info)
            await db.save_reservation(attempt["scope"], attempt["intent"]["date"], order_id, result.message)
        elif confirm_not_created:
            result = OrderResult(False, "已记录用户确认未创建订单；再次预约请使用新的 request_id",
                                 status="not_submitted", request_id=request_id, response_info=response_info)
            attempt["resolved_by_user"] = True
        else:
            return OrderResult(False, "暂未查到目标订单，但不能排除仍在处理；保留未知状态并暂停自动预约",
                               status="unknown", request_id=request_id, response_info=response_info)
        attempt.update(status=result.status, reconciled_at=datetime.now(timezone.utc).isoformat(),
                       result={key: value for key, value in dataclasses.asdict(result).items() if key != "raw_response"})
        db.put("order_attempt", request_id, attempt)
        emit("order_reconciled", {"request_id": request_id, "status": result.status, "order_id": order_id})
        return result


def get_user_orders(page_no=1, page_size=100):
    api = _create_api()
    try:
        payload = api.list_orders(page_no=page_no, page_size=page_size)
        if payload.get("code") not in (None, 0, "0"):
            raise RuntimeError(payload.get("msg") or "订单查询失败，请检查登录状态")
        orders = payload.get("records", [])
        for order in orders:
            order["scDate"] = order.get("scDate") or order.get("scdate") or (order.get("ordercreatement") or "")[:10]
            # The campus flag is inverted: true means cancellation is blocked.
            blocked = str(order.get("cancelOrder", "")).strip().lower() in {"true", "1"}
            state = str(order.get("orderstateid"))
            order["can_cancel"] = state in {"0", "9"} or (state == "1" and not blocked)
        return {"success": True, "orders": orders, "total": payload.get("total", len(orders)), "page_no": page_no, "page_size": page_size}
    finally:
        api.close()


def _dashboard_availability_sync(card):
    """One date-summary request; fetch details only for days with availability."""
    option = _get_preset(card["preset"])
    if not option:
        raise ValueError("卡片的场馆项目已失效，请删除后重新添加")
    api = _create_api()
    try:
        summaries = {day.date: day for day in api.list_date_availability(option.venue_id, option.field_type_id)}
        field_type = None
        days = []
        today = datetime.now().date()
        for offset in range(card["days"]):
            date = (today + timedelta(days=offset)).isoformat()
            summary = summaries.get(date)
            day = {"date": date, "status": "unopened", "slots": []}
            if summary is None:
                days.append(day)
                continue
            if not summary.open:
                day["status"] = "closed"
            elif summary.is_all:
                day["status"] = "full"
            else:
                try:
                    if field_type is None:
                        detail = api.get_venue_detail(option.venue_id)
                        field_type = next((item for item in api.list_field_types(detail) if item.id == option.field_type_id), None)
                        if field_type is None:
                            raise RuntimeError("未找到该运动项目的场次配置")
                    slots = api.query_slots(option.venue_id, option.field_type_id, date,
                                            date_token=summary.token, original_field_type=field_type)
                    available = []
                    for slot in slots:
                        if slot.available and (slot.remain is None or slot.remain > 0):
                            _normalise_slot_times(slot)
                            available.append(slot)
                    day["slots"] = sorted(available, key=lambda slot: (slot.start, slot.end, slot.field_name or ""))
                    day["status"] = "available" if available else "full"
                except (RuntimeError, ValueError, httpx.HTTPError) as exc:
                    day["status"] = "error"
                    day["message"] = str(exc)
            days.append(day)
        return {"card_id": card["id"], "days": days, "updated_at": datetime.now().isoformat()}
    finally:
        api.close()


async def dashboard_availability(card):
    return await asyncio.to_thread(_dashboard_availability_sync, card)


def _spawn(name, coroutine):
    task = asyncio.create_task(coroutine, name=name)
    _task_handles[name] = task
    return task


async def _cancel_worker(name):
    task = _task_handles.pop(name, None)
    if task and task is not asyncio.current_task():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def start_monitor(monitor_id, *, preset=None, venue_id=None, field_type_id=None, date=None, start_hour=None,
                        interval_seconds=240, auto_book=False, long_running=False, operating_start_hour=0,
                        operating_end_hour=24, base_target=None, preferred_hours=None, preferred_days=None):
    if monitor_id in _active_monitors or monitor_id in _paused_monitors:
        return {"success": False, "message": "监控已存在，请暂停/恢复或先删除"}
    if auto_book and not _get_preset(preset):
        raise ValueError("自动预约监控需要有效预设")
    target = dataclasses.replace(base_target or CFG.TARGET)
    if preferred_days is not None:
        target.date_offset = list(preferred_days)
    info = {"id": monitor_id, "preset": preset, "venue_id": venue_id, "field_type_id": field_type_id,
            "date": date, "start_hour": start_hour, "interval_seconds": max(30, interval_seconds),
            "auto_book": auto_book, "long_running": long_running, "operating_start_hour": operating_start_hour,
            "operating_end_hour": operating_end_hour, "base_target": target, "preferred_hours": preferred_hours,
            "preferred_days": preferred_days, "status": "running", "start_time": datetime.now().isoformat(),
            "last_check": None, "found_slots": [], "successful_bookings": 0, "booking_attempts": 0}
    _active_monitors[monitor_id] = info
    await get_db_manager().save_monitor(info)
    _spawn(f"monitor:{monitor_id}", _monitor_worker(monitor_id))
    return {"success": True, "monitor_info": info}


async def _monitor_worker(monitor_id):
    info = _active_monitors[monitor_id]
    while info["status"] == "running":
        try:
            hour = datetime.now().hour
            start, end = info["operating_start_hour"], info["operating_end_hour"]
            active = start == end or start <= hour < end if start <= end else hour >= start or hour < end
            info["window_active"] = active
            if active:
                await require_authenticated()
                await _monitor_check(monitor_id)
            await get_db_manager().save_monitor(info)
        except Exception as exc:
            info["last_error"] = str(exc)
            emit("monitor_error", {"monitor_id": monitor_id, "message": str(exc)})
            await get_db_manager().save_monitor(info)
        if info["status"] != "running":
            break
        await asyncio.sleep(info["interval_seconds"])


async def _monitor_check(monitor_id):
    info = _active_monitors[monitor_id]
    result = await list_slots(preset=info["preset"], venue_id=info["venue_id"], field_type_id=info["field_type_id"],
                              date=info["date"], start_hour=info["start_hour"], base_target=info["base_target"])
    hours = info.get("preferred_hours")
    entries = [entry for entry in result.slots if not hours or int(entry.start.split(":")[0]) in hours]
    entries.sort(key=lambda entry: ((hours or []).index(int(entry.start.split(":")[0])) if hours else 0, entry.date, entry.start))
    info["last_check"] = datetime.now().isoformat()
    info["resolved"] = {"label": result.resolved.label, "venue_name": result.resolved.venue_name,
                        "field_type_name": result.resolved.field_type_name}
    info["found_slots"] = [dataclasses.asdict(dataclasses.replace(
        entry, slot=dataclasses.replace(entry.slot, sign=None, raw={}))) for entry in entries]
    signature = [(e.date, e.start, e.slot.slot_id) for e in entries]
    if signature and signature != info.get("last_signature"):
        emit("availability", {"monitor_id": monitor_id, "slots": info["found_slots"]})
    info["last_signature"] = signature
    if info["auto_book"]:
        for entry in entries:
            info["booking_attempts"] += 1
            result = await order_once(preset=info["preset"], date=entry.date, start_time=entry.start, end_time=entry.end,
                                      base_target=info["base_target"], snapshot_id=result.snapshot_id,
                                      candidate_id=entry.slot.slot_id)
            info["last_booking_result"] = {"success": result.success, "message": result.message,
                                          "order_id": result.order_id, "status": result.status,
                                          "request_id": result.request_id}
            if result.success:
                info["successful_bookings"] += 1
                if not info["long_running"]:
                    info["status"] = "completed"
                break
            if result.status in {"unknown", "login_required", "challenge_required"}:
                info["last_error"] = result.message
                await pause_monitor(monitor_id)
            # A failed confirmation never silently changes the selected slot.
            break


async def pause_monitor(monitor_id):
    info = _active_monitors.pop(monitor_id, None)
    if not info:
        return {"success": False, "message": "未找到运行中的监控"}
    await _cancel_worker(f"monitor:{monitor_id}")
    info["status"] = "paused"
    _paused_monitors[monitor_id] = info
    await get_db_manager().save_monitor(info)
    return {"success": True}


async def resume_monitor(monitor_id):
    info = _paused_monitors.pop(monitor_id, None)
    if not info:
        return {"success": False, "message": "未找到暂停的监控"}
    info["status"] = "running"
    _active_monitors[monitor_id] = info
    await get_db_manager().save_monitor(info)
    _spawn(f"monitor:{monitor_id}", _monitor_worker(monitor_id))
    return {"success": True, "monitor_info": info}


async def stop_monitor(monitor_id):
    await _cancel_worker(f"monitor:{monitor_id}")
    info = _active_monitors.pop(monitor_id, None) or _paused_monitors.pop(monitor_id, None)
    if info:
        info["status"] = "stopped"
        await get_db_manager().save_monitor(info)
    return {"success": bool(info), "message": "监控已停止" if info else "未找到监控"}


async def delete_monitor(monitor_id):
    await stop_monitor(monitor_id)
    return {"success": await get_db_manager().delete_monitor(monitor_id)}


async def monitor_status(monitor_id=None):
    if monitor_id:
        info = get_db_manager().get("monitor", monitor_id)
        return {"success": bool(info), "monitor_info": info}
    return {"success": True, "monitors": get_db_manager().all("monitor")}


def keep_alive_status():
    info = get_db_manager().get("settings", "keep_alive") or {"enabled": False, "interval_minutes": 15}
    record = _auth_manager.load_record() or {}
    return {**info, "session": {"sso_available": has_sso_session(record),
            "login_required": bool(record.get("login_required")),
            "verified_at": record.get("verified_at"), "renewed_at": record.get("renewed_at")}}


async def check_keep_alive():
    result = await run_keep_alive_once(auth_manager=_auth_manager)
    current_account()
    info = get_db_manager().get("settings", "keep_alive") or {"enabled": False, "interval_minutes": 15}
    info.update(last_run=result.checked_at, last_result=dataclasses.asdict(result))
    get_db_manager().put("settings", "keep_alive", info)
    emit("keep_alive", info["last_result"])
    return result


async def configure_keep_alive(*, enabled=True, interval_minutes=15):
    if interval_minutes < 1:
        raise ValueError("保活间隔至少 1 分钟")
    await _cancel_worker("keep-alive")
    info = get_db_manager().get("settings", "keep_alive") or {}
    info.update(enabled=enabled, interval_minutes=interval_minutes)
    get_db_manager().put("settings", "keep_alive", info)
    if enabled:
        _spawn("keep-alive", _keep_alive_worker())
    return keep_alive_status()


async def _keep_alive_worker():
    while True:
        info = keep_alive_status()
        try:
            await check_keep_alive()
        except Exception as exc:
            emit("keep_alive_error", {"message": str(exc)})
        await asyncio.sleep(info["interval_minutes"] * 60)


async def restore_state():
    initialize_database()
    current_account()
    for info in get_db_manager().all("monitor"):
        info["base_target"] = BookingTarget(**info.get("base_target", {}))
        if info["status"] == "paused":
            _paused_monitors[info["id"]] = info
        elif info["status"] in {"running", "starting"}:
            _active_monitors[info["id"]] = info
            _spawn(f"monitor:{info['id']}", _monitor_worker(info["id"]))
    if keep_alive_status()["enabled"]:
        _spawn("keep-alive", _keep_alive_worker())


async def shutdown():
    global _booking_manager
    for sid in list(_qr_sessions):
        await cancel_qr_login(sid)
    for name in list(_task_handles):
        await _cancel_worker(name)
    for sid in list(_login_sessions):
        await cancel_login_session(sid)
    with _booking_mutex:
        if _booking_manager is not None:
            _booking_manager.api.close()
            _booking_manager = None
    _slot_snapshots.clear()


def _save_qr_cookie(cookie, *, session_cookies=None):
    candidate = UserAuth(nickname="Account", cookie=cookie)
    api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, AuthConfig(user=candidate))
    try:
        profile = _normalize_user_payload(api.check_login())
        details = profile.get("profile") or {}
        username = details.get("login_name")
        if not profile.get("success") or not username:
            raise RuntimeError("扫码后未获得有效的体育站用户资料，请重新生成二维码")
    finally:
        api.close()
    return _save_verified_login(username, details.get("user_name"), cookie, session_cookies=session_cookies)


async def start_qr_login():
    initialize_database()
    for sid in list(_qr_sessions):
        await cancel_qr_login(sid)
    for sid in list(_login_sessions):
        await cancel_login_session(sid)
    client = AuthClient(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH)
    try:
        state = await client.prepare()
        url = state.metadata.get("qr_image_url")
        if not url:
            raise RuntimeError("当前统一身份认证页面未提供二维码登录")
        sid = "qr_" + uuid.uuid4().hex
        session = {"client": client, "state": state, "status": "connecting", "image": b"", "ready": asyncio.Event(),
                   "version": 0, "created_at": datetime.now(timezone.utc), "message": "正在连接扫码登录服务"}
        _qr_sessions[sid] = session
        session["task"] = asyncio.create_task(_qr_worker(sid), name=f"qr-login:{sid}")
        try:
            await asyncio.wait_for(session["ready"].wait(), 20)
        except asyncio.TimeoutError:
            await cancel_qr_login(sid)
            raise RuntimeError("二维码生成超时，请刷新或使用密码登录")
        return qr_login_status(sid)
    except Exception:
        await client.close()
        raise


def qr_login_status(session_id):
    session = _qr_sessions.get(session_id)
    if not session:
        return {"success": False, "status": "expired", "message": "二维码会话不存在，请重新生成"}
    result = {"success": session["status"] not in {"error", "expired", "cancelled"}, "status": session["status"],
              "session_id": session_id, "image_version": session["version"], "message": session["message"],
              "expires_at": (session["created_at"] + _LOGIN_SESSION_TIMEOUT).isoformat()}
    if session["status"] in {"connecting", "waiting", "confirming"}:
        result["qr_image"] = session["image"]
    return result


async def cancel_qr_login(session_id):
    session = _qr_sessions.pop(session_id, None)
    if session:
        task = session.get("task")
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await session["client"].close()
    return {"success": True, "status": "cancelled", "session_id": session_id, "message": "已取消扫码登录"}


async def _qr_worker(session_id):
    from websockets.asyncio.client import connect
    from websockets.exceptions import WebSocketException
    session = _qr_sessions[session_id]
    client, state = session["client"], session["state"]
    host = urlparse(state.prepare_url).hostname
    cookie = _cookie_header(client._client.cookies, domain=host)
    origin = f"{urlparse(state.prepare_url).scheme}://{host}"
    try:
        async with connect(state.metadata["qr_socket_url"], origin=origin,
                           additional_headers={"Cookie": cookie, "Referer": state.prepare_url},
                           user_agent_header="Mozilla/5.0", proxy=True if CFG.TRUST_ENV else None,
                           open_timeout=15, close_timeout=3) as socket:
            session.update(status="waiting", message="请使用交我办或微信扫码，并在手机上确认")
            await socket.send(json.dumps({"type": "UPDATE_QR_CODE"}))
            while True:
                remaining = (_LOGIN_SESSION_TIMEOUT - (datetime.now(timezone.utc) - session["created_at"])).total_seconds()
                if remaining <= 0:
                    session.update(status="expired", message="二维码已过期，请重新生成")
                    return
                try:
                    raw = await asyncio.wait_for(socket.recv(), min(60, remaining))
                except asyncio.TimeoutError:
                    await socket.send(json.dumps({"type": "UPDATE_QR_CODE"}))
                    continue
                message = json.loads(raw)
                if message.get("type") == "UPDATE_QR_CODE":
                    payload = message.get("payload") or {}
                    if "ts" not in payload or "sig" not in payload:
                        raise RuntimeError("扫码服务未返回有效的二维码更新参数")
                    from httpx import URL
                    image_url = URL(state.metadata["qr_image_url"]).copy_merge_params({"ts": str(payload["ts"]), "sig": str(payload["sig"])})
                    image = await client._client.get(image_url, headers={"Referer": state.prepare_url})
                    image.raise_for_status()
                    session["image"] = image.content
                    session["version"] += 1
                    session["ready"].set()
                elif message.get("type") == "LOGIN":
                    session.update(status="confirming", message="扫码已确认，正在连接体育预约平台")
                    response = await client._client.get(state.metadata["qr_express_url"], headers={"Referer": state.prepare_url})
                    await client.follow_redirects(response, max_jumps=10)
                    cookie = _cookie_header(client._client.cookies, url=f"{CFG.BASE_URL}{CFG.ENDPOINTS.current_user}")
                    if not cookie:
                        raise RuntimeError("扫码未换取到体育站会话，请重新生成二维码")
                    await asyncio.to_thread(_save_qr_cookie, cookie,
                                            session_cookies=serialize_cookies(client._client.cookies))
                    session.update(status="success", message="扫码登录成功", image=b"")
                    return
                elif message.get("type") == "ERROR_MESSAGE":
                    raise RuntimeError("扫码服务返回异常，请重新生成二维码；必要时使用密码登录")
    except asyncio.CancelledError:
        raise
    except (WebSocketException, httpx.HTTPError, OSError, ValueError, RuntimeError, KeyError) as exc:
        session.update(status="error", message=f"扫码连接未完成：{exc}", image=b"")
    finally:
        session["ready"].set()
        await client.close()
