from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .api import SportsAPI
from urllib.parse import urlparse

from .auth import AuthManager, AuthClient, AuthState, _cookie_header
from .models import BookingTarget, FieldType, MonitorPlan, PresetOption, Slot, UserAuth, Venue
from .monitor import SlotMonitor
from .order import OrderManager, OrderResult
from .database import get_db_manager
from .auto_booking import get_auto_booking_system

try:
    import config as CFG
except ImportError as exc:  # pragma: no cover - configuration should exist
    raise RuntimeError("service module requires top-level config.py") from exc


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
    if hour is not None:
        slot.start = f"{hour:02d}:00"

    end_hour = _slot_label_to_hour(slot.end)
    if end_hour is not None:
        slot.end = f"{end_hour:02d}:00"
    elif hour is not None:
        slot.end = f"{(hour + 1) % 24:02d}:00"
    return hour


def _availability_to_dict(entry: SlotAvailability) -> Dict[str, Any]:
    slot = entry.slot
    return {
        "date": entry.date,
        "start": slot.start,
        "end": slot.end,
        "available": slot.available,
        "remain": slot.remain,
        "price": slot.price,
        "field_name": slot.field_name,
        "area_name": slot.area_name,
        "slot_id": slot.slot_id,
        "sign": slot.sign,
    }


def _slot_dict_hour(slot: Dict[str, Any]) -> Optional[int]:
    value = slot.get("start")
    if isinstance(value, str):
        if value.startswith("slot-"):
            try:
                return (7 + int(value.split("-", 1)[1])) % 24
            except Exception:  # pylint: disable=broad-except
                return None
        parts = value.split(":", 1)
        if parts and parts[0].isdigit():
            return int(parts[0])
    return None


def _slot_dict_day_offset(slot: Dict[str, Any]) -> Optional[int]:
    value = slot.get("date")
    if isinstance(value, str):
        try:
            slot_date = datetime.strptime(value, "%Y-%m-%d").date()
            return (slot_date - datetime.now().date()).days
        except Exception:  # pylint: disable=broad-except
            return None
    return None


def _filter_slots_by_preferences_dict(slots: List[Dict[str, Any]], monitor_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    preferred_hours = monitor_info.get("preferred_hours") or []
    preferred_days = monitor_info.get("preferred_days") or []

    if not preferred_hours and not preferred_days:
        return list(slots)

    filtered: List[Dict[str, Any]] = []
    for slot in slots:
        hour = _slot_dict_hour(slot)
        day_offset = _slot_dict_day_offset(slot)

        if preferred_hours and (hour is None or hour not in preferred_hours):
            continue
        if preferred_days and (day_offset is None or day_offset not in preferred_days):
            continue
        filtered.append(slot)
    return filtered


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


def _fetch_user_info_sync(identifier: Optional[str]) -> Dict[str, Any]:
    api = _create_api(active_user=identifier)
    try:
        payload = api.check_login()
    finally:
        api.close()
    return payload


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
    if code in (None, 0, "0"):
        result["success"] = True
    else:
        result["message"] = payload.get("msg") or payload.get("message")

    user_info: Any = payload
    if isinstance(user_info, dict):
        for key in ("data", "user", "userInfo", "result", "payload"):
            candidate = user_info.get(key)
            if isinstance(candidate, dict) and candidate:
                user_info = candidate
                break

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
        result["profile"] = profile
    return result


async def fetch_user_infos() -> List[Dict[str, Any]]:
    cookies_map, active_username = _auth_manager.load_all_cookies()
    if not cookies_map:
        try:
            payload = await asyncio.to_thread(_fetch_user_info_sync, None)
            normalized = _normalize_user_payload(payload)
            normalized.update({
                "key": None,
                "username": None,
                "nickname": None,
                "is_active": True,
            })
            return [normalized]
        except Exception as exc:  # pylint: disable=broad-except
            return [
                {
                    "key": None,
                    "username": None,
                    "nickname": None,
                    "is_active": True,
                    "success": False,
                    "message": str(exc),
                    "profile": None,
                    "raw": None,
                }
            ]

    results: List[Dict[str, Any]] = []
    for key, record in cookies_map.items():
        identifier = record.get("username") or key
        nickname = record.get("nickname")
        try:
            payload = await asyncio.to_thread(_fetch_user_info_sync, identifier)
            normalized = _normalize_user_payload(payload)
        except Exception as exc:  # pylint: disable=broad-except
            normalized = {
                "success": False,
                "message": str(exc),
                "profile": None,
                "raw": None,
            }
        normalized.update(
            {
                "key": key,
                "username": record.get("username"),
                "nickname": nickname,
                "is_active": identifier == active_username,
            }
        )
        results.append(normalized)
    return results


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


def _find_user(identifier: Optional[str]) -> Optional[UserAuth]:
    if not identifier:
        return None
    for user in getattr(CFG.AUTH, "users", []) or []:
        if identifier in {user.nickname, user.username}:
            return user
    return None


def _sync_users_from_store(store: Dict[str, Dict[str, Any]]) -> None:
    users: List[UserAuth] = getattr(CFG.AUTH, "users", []) or []

    for user in users:
        entry = None
        if user.username and user.username in store:
            entry = store[user.username]
        elif user.nickname and user.nickname in store:
            entry = store[user.nickname]
        elif user.username is None and "__default__" in store:
            entry = store["__default__"]
        if entry:
            user.cookie = entry.get("cookie") or user.cookie
            if entry.get("nickname"):
                user.nickname = entry["nickname"]

    for key, entry in store.items():
        username = entry.get("username")
        nickname = entry.get("nickname") or (
            username.split("@")[0] if username and "@" in username else username or key
        )
        if username and not any(u.username == username for u in users):
            users.append(UserAuth(nickname=nickname or "用户", username=username, cookie=entry.get("cookie")))
        elif key == "__default__" and not username:
            if not users:
                users.append(UserAuth(nickname=nickname or "默认用户", username=None, cookie=entry.get("cookie")))

    CFG.AUTH.users = users


def _create_api(*, active_user: Optional[str] = None) -> SportsAPI:
    try:
        cookies_map, active_username = _auth_manager.load_all_cookies()
        if cookies_map:
            _sync_users_from_store(cookies_map)
        else:
            active_username = None
    except Exception:  # pylint: disable=broad-except
        active_username = None

    api = SportsAPI(
        CFG.BASE_URL,
        CFG.ENDPOINTS,
        CFG.AUTH,
        preset_targets=list(_iter_presets()),
    )

    # 优先使用传入的 active_user 参数，如果没有则使用 active_username
    target_identifier = active_user if active_user is not None else active_username
    target_user = _find_user(target_identifier)
    if target_user:
        try:
            api.switch_to_user(target_user)
        except Exception:  # pylint: disable=broad-except
            pass

    return api


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
) -> SlotListResult:
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
) -> SlotListResult:
    return await asyncio.to_thread(
        _list_slots_sync,
        preset=preset,
        venue_id=venue_id,
        field_type_id=field_type_id,
        date=date,
        start_hour=start_hour,
        show_full=show_full,
        base_target=base_target,
    )


def _order_once_sync(
    *,
    preset: int,
    date: str,
    start_time: str,
    end_time: Optional[str],
    base_target: Optional[BookingTarget],
    user: Optional[str],
) -> OrderResult:
    api = _create_api(active_user=user)
    manager = OrderManager(api, CFG.ENCRYPTION_CONFIG)
    try:
        parsed_date = _parse_date_input(date)
        start_label = _parse_time_input(start_time)
        if end_time:
            end_label = _parse_time_input(end_time)
        else:
            reference_target = base_target or getattr(CFG, "TARGET", BookingTarget())
            end_label = _next_hour(start_label, reference_target.duration_hours if reference_target.duration_hours else 1)
        result = manager.place_order_by_preset(
            preset_index=preset,
            date=parsed_date,
            start_time=start_label,
            end_time=end_label,
        )
        return result
    finally:
        api.close()


async def order_once(
    *,
    preset: int,
    date: str,
    start_time: str,
    end_time: Optional[str] = None,
    base_target: Optional[BookingTarget] = None,
    user: Optional[str] = None,
    notification_context: Optional[str] = None,
) -> OrderResult:
    # 规范化日期与时间，便于通知与记录展示
    try:
        normalized_date = _parse_date_input(date)
    except Exception:  # pylint: disable=broad-except
        normalized_date = date.strip()

    try:
        normalized_start = _parse_time_input(start_time)
    except Exception:  # pylint: disable=broad-except
        normalized_start = start_time.strip()

    reference_target = base_target or getattr(CFG, "TARGET", BookingTarget())
    effective_duration = getattr(reference_target, "duration_hours", 1) or 1

    if end_time:
        try:
            normalized_end = _parse_time_input(end_time)
        except Exception:  # pylint: disable=broad-except
            normalized_end = end_time.strip()
    else:
        try:
            normalized_end = _next_hour(normalized_start, effective_duration)
        except Exception:  # pylint: disable=broad-except
            normalized_end = normalized_start

    result = await asyncio.to_thread(
        _order_once_sync,
        preset=preset,
        date=normalized_date,
        start_time=normalized_start,
        end_time=normalized_end,
        base_target=base_target,
        user=user,
    )
    
    # 保存预订记录到数据库
    if result:
        try:
            db_manager = get_db_manager()
            record_message = result.message
            if notification_context:
                record_message = f"{notification_context} - {record_message}"
            if user:
                record_message = f"[{user}] {record_message}"

            await db_manager.save_booking_record(
                order_id=result.order_id or "unknown",
                preset=preset,
                venue_name=f"预设{preset}",
                field_type_name="未知",
                date=normalized_date,
                start_time=normalized_start,
                end_time=normalized_end,
                status="success" if result.success else "failed",
                message=record_message,
            )
        except Exception as e:
            print(f"保存预订记录失败: {e}")
        
        if result.success and CFG.ENABLE_ORDER_NOTIFICATION:
            try:
                from .notification import send_order_notification

                user_nickname: Optional[str] = None
                identifier_candidates: List[Optional[str]] = [user]

                cookies_map: Dict[str, Dict[str, Any]] = {}
                active_username: Optional[str] = None
                try:
                    cookies_map, active_username = _auth_manager.load_all_cookies()
                except Exception:  # pylint: disable=broad-except
                    cookies_map = {}

                if not user and active_username:
                    identifier_candidates.append(active_username)

                for ident in identifier_candidates:
                    if not ident:
                        continue
                    for auth_user in getattr(CFG.AUTH, "users", []) or []:
                        if ident in {auth_user.username, auth_user.nickname}:
                            user_nickname = auth_user.nickname or auth_user.username
                            break
                    if user_nickname:
                        break
                    for entry in cookies_map.values():
                        if ident in {entry.get("username"), entry.get("nickname")}:
                            user_nickname = entry.get("nickname") or entry.get("username")
                            break
                    if user_nickname:
                        break

                if not user_nickname and active_username and active_username in cookies_map:
                    record = cookies_map[active_username]
                    user_nickname = record.get("nickname") or record.get("username")

                if not user_nickname:
                    user_nickname = "未知用户"

                venue_name = f"预设{preset}"
                field_type_name = "未知"
                for preset_option in CFG.PRESET_TARGETS:
                    if preset_option.index == preset:
                        venue_name = preset_option.venue_name
                        field_type_name = preset_option.field_type_name
                        break

                notify_message = result.message
                if notification_context:
                    notify_message = f"{notification_context}\n{result.message}"

                order_identifier = (
                    result.order_id
                    or (result.raw_response or {}).get("orderId")
                    or (result.raw_response or {}).get("data")
                )

                await send_order_notification(
                    order_id=str(order_identifier or "unknown"),
                    user_nickname=user_nickname,
                    venue_name=venue_name,
                    field_type_name=field_type_name,
                    date=normalized_date,
                    start_time=normalized_start,
                    end_time=normalized_end,
                    success=result.success,
                    message=notify_message,
                    target_groups=CFG.NOTIFICATION_TARGETS.get("groups"),
                    target_users=CFG.NOTIFICATION_TARGETS.get("users"),
                )
            except Exception as e:
                print(f"发送订单通知失败: {e}")

    return result


# =============================================================================
# 监控和调度相关接口
# =============================================================================

# 全局任务存储（初期使用内存字典）
_active_monitors: Dict[str, Dict] = {}
_scheduled_jobs: Dict[str, Dict] = {}
_auth_manager = AuthManager()


@dataclass
class LoginSession:
    session_id: str
    client: AuthClient
    state: AuthState
    username: str
    password: str
    created_at: datetime
    user_id: Optional[str] = None
    attempts: int = 0
    nickname: Optional[str] = None


_login_sessions: Dict[str, LoginSession] = {}
_LOGIN_SESSION_TIMEOUT = timedelta(minutes=5)


async def start_monitor(
    monitor_id: str,
    *,
    preset: Optional[int] = None,
    venue_id: Optional[str] = None,
    field_type_id: Optional[str] = None,
    date: Optional[str] = None,
    start_hour: Optional[int] = None,
    interval_seconds: int = 240,
    auto_book: bool = False,
    base_target: Optional[BookingTarget] = None,
    target_users: Optional[List[str]] = None,
    exclude_users: Optional[List[str]] = None,
    preferred_hours: Optional[List[int]] = None,
    preferred_days: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    启动监控任务
    
    Args:
        monitor_id: 监控任务唯一标识
        preset: 预设序号
        venue_id: 场馆ID
        field_type_id: 运动类型ID
        date: 目标日期
        start_hours: 开始小时列表（例如 [18,19]）
        interval_seconds: 监控间隔（秒）
        auto_book: 是否自动预订
        base_target: 基础目标配置
        
    Returns:
        监控任务信息
    """
    if monitor_id in _active_monitors:
        return {"success": False, "message": f"监控任务 {monitor_id} 已存在"}
    
    # 创建监控任务信息
    working_target = dataclasses.replace(base_target or getattr(CFG, "TARGET", BookingTarget()))
    if target_users is not None:
        working_target.target_users = list(target_users)
    if exclude_users is not None:
        working_target.exclude_users = list(exclude_users)
    
    # 处理优先天数和时间段
    if preferred_days is not None:
        working_target.date_offset = list(preferred_days)
        working_target.use_all_dates = False
    if preferred_hours is not None:
        working_target.start_hour = preferred_hours[0] if preferred_hours else 18

    monitor_info = {
        "id": monitor_id,
        "preset": preset,
        "venue_id": venue_id,
        "field_type_id": field_type_id,
        "date": date,
        "start_hour": start_hour,
        "interval_seconds": interval_seconds,
        "auto_book": auto_book,
        "base_target": working_target,
        "preferred_hours": preferred_hours,
        "preferred_days": preferred_days,
        "status": "starting",
        "start_time": datetime.now().isoformat(),
        "last_check": None,
        "found_slots": [],
        "booking_attempts": 0,
        "successful_bookings": 0,
        "target_users": list(target_users or []),
        "exclude_users": list(exclude_users or []),
        "last_notified_signature": None,
        "resolved": None,
    }
    
    # 保存到数据库
    db_manager = get_db_manager()
    await db_manager.save_monitor(monitor_info)
    
    _active_monitors[monitor_id] = monitor_info
    
    # 启动监控任务（异步）
    asyncio.create_task(_monitor_worker(monitor_id))
    
    return {"success": True, "message": f"监控任务 {monitor_id} 已启动", "monitor_info": monitor_info}


async def stop_monitor(monitor_id: str) -> Dict[str, Any]:
    """
    停止监控任务
    
    Args:
        monitor_id: 监控任务标识
        
    Returns:
        操作结果
    """
    if monitor_id not in _active_monitors:
        return {"success": False, "message": f"监控任务 {monitor_id} 不存在"}
    
    monitor_info = _active_monitors[monitor_id]
    monitor_info["status"] = "stopped"
    monitor_info["stop_time"] = datetime.now().isoformat()
    
    # 更新数据库
    db_manager = get_db_manager()
    await db_manager.save_monitor(monitor_info)
    
    del _active_monitors[monitor_id]
    
    return {"success": True, "message": f"监控任务 {monitor_id} 已停止"}


async def monitor_status(monitor_id: Optional[str] = None) -> Dict[str, Any]:
    """
    获取监控任务状态
    
    Args:
        monitor_id: 监控任务标识，为None时返回所有任务
        
    Returns:
        监控状态信息
    """
    if monitor_id:
        if monitor_id not in _active_monitors:
            return {"success": False, "message": f"监控任务 {monitor_id} 不存在"}
        return {"success": True, "monitor_info": _active_monitors[monitor_id]}
    else:
        return {"success": True, "monitors": list(_active_monitors.values())}


async def schedule_daily_job(
    job_id: str,
    *,
    hour: int,
    minute: int = 0,
    second: int = 0,
    preset: Optional[int] = None,
    venue_id: Optional[str] = None,
    field_type_id: Optional[str] = None,
    date: Optional[str] = None,
    start_hours: Optional[List[int]] = None,
    base_target: Optional[BookingTarget] = None,
    target_users: Optional[List[str]] = None,
    exclude_users: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    创建每日定时任务
    
    Args:
        job_id: 任务唯一标识
        hour: 执行小时
        minute: 执行分钟
        second: 执行秒
        preset: 预设序号
        venue_id: 场馆ID
        field_type_id: 运动类型ID
        date: 目标日期
        start_hour: 开始小时
        base_target: 基础目标配置
        
    Returns:
        任务创建结果
    """
    if job_id in _scheduled_jobs:
        return {"success": False, "message": f"定时任务 {job_id} 已存在"}
    
    if base_target is None:
        base_target = BookingTarget()

    if target_users:
        base_target.target_users = list(dict.fromkeys(target_users))
    if exclude_users:
        base_target.exclude_users = list(dict.fromkeys(exclude_users))

    normalized_hours: List[int] = []
    if start_hours:
        for entry in start_hours:
            try:
                value = int(entry)
                if 0 <= value <= 23:
                    normalized_hours.append(value)
            except (TypeError, ValueError):
                continue
    elif getattr(base_target, "start_hour", None) is not None:
        normalized_hours.append(int(base_target.start_hour))

    if not normalized_hours:
        normalized_hours.append(18)

    normalized_hours = sorted(dict.fromkeys(normalized_hours))
    base_target.start_hour = normalized_hours[0]

    # 创建定时任务信息
    job_info = {
        "id": job_id,
        "hour": hour,
        "minute": minute,
        "second": second,
        "preset": preset,
        "venue_id": venue_id,
        "field_type_id": field_type_id,
        "date": date,
        "start_hour": normalized_hours[0],
        "start_hours": normalized_hours,
        "base_target": base_target,
        "target_users": list(getattr(base_target, "target_users", []) or []),
        "exclude_users": list(getattr(base_target, "exclude_users", []) or []),
        "status": "scheduled",
        "created_time": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
        "run_count": 0,
        "success_count": 0,
    }
    
    # 保存到数据库
    db_manager = get_db_manager()
    await db_manager.save_scheduled_job(job_info)
    
    _scheduled_jobs[job_id] = job_info
    
    # 启动定时任务
    asyncio.create_task(_schedule_worker(job_id))
    
    return {"success": True, "message": f"定时任务 {job_id} 已创建", "job_info": job_info}


async def cancel_scheduled_job(job_id: str) -> Dict[str, Any]:
    """
    取消定时任务
    
    Args:
        job_id: 任务标识
        
    Returns:
        操作结果
    """
    if job_id not in _scheduled_jobs:
        return {"success": False, "message": f"定时任务 {job_id} 不存在"}
    
    job_info = _scheduled_jobs[job_id]
    job_info["status"] = "cancelled"
    job_info["cancelled_time"] = datetime.now().isoformat()
    
    # 更新数据库
    db_manager = get_db_manager()
    await db_manager.save_scheduled_job(job_info)
    
    del _scheduled_jobs[job_id]
    
    return {"success": True, "message": f"定时任务 {job_id} 已取消"}


async def list_scheduled_jobs() -> Dict[str, Any]:
    """
    列出所有定时任务
    
    Returns:
        定时任务列表
    """
    return {"success": True, "jobs": list(_scheduled_jobs.values())}


# =============================================================================
# 内部工作函数
# =============================================================================

async def _monitor_worker(monitor_id: str) -> None:
    """监控工作线程"""
    monitor_info = _active_monitors.get(monitor_id)
    if not monitor_info:
        return
    
    monitor_info["status"] = "running"
    
    # 更新数据库状态
    db_manager = get_db_manager()
    await db_manager.save_monitor(monitor_info)
    
    retry_count = 0
    max_retries = 3
    
    try:
        while monitor_id in _active_monitors and monitor_info["status"] == "running":
            try:
                # 执行监控检查
                await _monitor_check(monitor_id)
                retry_count = 0  # 重置重试计数
                
                # 更新数据库
                await db_manager.save_monitor(monitor_info)
                
            except Exception as e:
                retry_count += 1
                monitor_info["last_error"] = str(e)
                
                if retry_count >= max_retries:
                    monitor_info["status"] = "error"
                    monitor_info["error"] = f"连续失败{max_retries}次: {str(e)}"
                    await db_manager.save_monitor(monitor_info)
                    break
                else:
                    # 等待后重试
                    await asyncio.sleep(min(30, retry_count * 10))
                    continue
            
            # 等待下次检查
            await asyncio.sleep(monitor_info["interval_seconds"])
            
    except Exception as e:
        monitor_info["status"] = "error"
        monitor_info["error"] = str(e)
        await db_manager.save_monitor(monitor_info)
    finally:
        if monitor_id in _active_monitors:
            monitor_info["status"] = "stopped"
            await db_manager.save_monitor(monitor_info)


async def _monitor_check(monitor_id: str) -> None:
    """执行单次监控检查"""
    monitor_info = _active_monitors.get(monitor_id)
    if not monitor_info:
        return
    
    try:
        # 查询可用时间段
        result = await list_slots(
            preset=monitor_info["preset"],
            venue_id=monitor_info["venue_id"],
            field_type_id=monitor_info["field_type_id"],
            date=monitor_info["date"],
            start_hour=monitor_info["start_hour"],
            show_full=False,
            base_target=monitor_info["base_target"],
        )
        
        monitor_info["last_check"] = datetime.now().isoformat()

        slots_payload: List[Dict[str, Any]] = []
        resolved_payload: Optional[Dict[str, Any]] = None

        if isinstance(result, SlotListResult):
            resolved = result.resolved
            resolved_payload = {
                "label": resolved.label,
                "venue_id": resolved.venue_id,
                "venue_name": resolved.venue_name,
                "field_type_id": resolved.field_type_id,
                "field_type_name": resolved.field_type_name,
            }
            slots_payload = [
                _availability_to_dict(entry)
                for entry in result.slots
                if entry.slot.available
            ]
        elif isinstance(result, dict):
            resolved_data = result.get("resolved")
            if isinstance(resolved_data, dict):
                resolved_payload = resolved_data
            raw_slots = result.get("slots") or []
            if isinstance(raw_slots, list):
                for entry in raw_slots:
                    if not isinstance(entry, dict):
                        continue
                    slot_info = entry.get("slot") or {}
                    available = bool(slot_info.get("available"))
                    if not available:
                        continue
                    slots_payload.append(
                        {
                            "date": entry.get("date"),
                            "start": slot_info.get("start"),
                            "end": slot_info.get("end"),
                            "available": available,
                            "remain": slot_info.get("remain"),
                            "price": slot_info.get("price"),
                            "field_name": slot_info.get("field_name"),
                            "area_name": slot_info.get("area_name"),
                            "slot_id": slot_info.get("slot_id"),
                            "sign": slot_info.get("sign"),
                        }
                    )

        filtered_slots = _filter_slots_by_preferences_dict(slots_payload, monitor_info)
        if filtered_slots:
            slots_payload = filtered_slots

        slots_payload = sorted(
            slots_payload,
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("start") or ""),
            ),
        )

        monitor_info["resolved"] = resolved_payload
        monitor_info["found_slots"] = slots_payload
        monitor_info.pop("last_error", None)

        if slots_payload:
            await _notify_monitor_slots(monitor_id, monitor_info, resolved_payload, slots_payload)
            if monitor_info.get("auto_book"):
                await _auto_book_from_monitor(monitor_id, slots_payload)
    except Exception as e:
        monitor_info["last_error"] = str(e)


async def _notify_monitor_slots(
    monitor_id: str,
    monitor_info: Dict[str, Any],
    resolved: Optional[Dict[str, Any]],
    slots: List[Dict[str, Any]],
) -> None:
    if not slots:
        return
    if not getattr(CFG, "ENABLE_NOTIFICATION", True):
        return

    signature = tuple(
        sorted(
            f"{slot.get('date')}|{slot.get('start')}|{slot.get('slot_id') or slot.get('field_name')}"
            for slot in slots
        )
    )
    if signature and signature == monitor_info.get("last_notified_signature"):
        return

    try:
        from .notification import send_monitor_notification
    except Exception as exc:  # pylint: disable=broad-except
        print(f"加载通知模块失败，跳过监控通知: {exc}")
        return

    venue_name = resolved.get("venue_name") if isinstance(resolved, dict) else None
    field_type_name = resolved.get("field_type_name") if isinstance(resolved, dict) else None

    try:
        success = await send_monitor_notification(
            monitor_id=monitor_id,
            venue_name=venue_name,
            field_type_name=field_type_name,
            slots=slots,
            auto_book=bool(monitor_info.get("auto_book")),
            target_groups=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("groups"),
            target_users=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("users"),
            preferred_hours=monitor_info.get("preferred_hours"),
            preferred_days=monitor_info.get("preferred_days"),
            booking_users=monitor_info.get("target_users"),
            excluded_users=monitor_info.get("exclude_users"),
        )
        if success:
            monitor_info["last_notified_signature"] = signature
    except Exception as exc:  # pylint: disable=broad-except
        print(f"发送监控通知失败: {exc}")


async def _auto_book_from_monitor(monitor_id: str, slots: List[Dict]) -> None:
    """从监控结果自动预订"""
    monitor_info = _active_monitors.get(monitor_id)
    if not monitor_info:
        return

    monitor_info["booking_attempts"] += 1
    monitor_info.setdefault("last_booking_results", [])

    base_target = monitor_info.get("base_target") or BookingTarget()
    target_users = list(getattr(base_target, "target_users", []) or [])
    exclude_users = set(getattr(base_target, "exclude_users", []) or [])

    available_users = [u for u in getattr(CFG.AUTH, "users", []) or [] if u.cookie]
    if target_users:
        user_sequence = [u for u in available_users if u.nickname in target_users]
    else:
        user_sequence = [u for u in available_users if u.nickname not in exclude_users]

    if not user_sequence:
        user_sequence = available_users[:1]

    # 逐个用户尝试预订
    for user_index, user in enumerate(user_sequence, 1):
        last_message = "未尝试"
        success_for_user = False
        user_id = user.username or user.nickname

        for slot_index, slot in enumerate(slots, 1):
            if not slot.get("available", False):
                continue

            try:
                result = await order_once(
                    preset=monitor_info["preset"],
                    date=slot.get("date", ""),
                    start_time=slot.get("start", ""),
                    end_time=slot.get("end") or None,
                    base_target=base_target,
                    user=user_id,
                    notification_context=f"来自监控任务 {monitor_id}",
                )
                last_message = result.message

                monitor_info["last_booking_results"].append(
                    {
                        "user": user.nickname,
                        "username": user.username,
                        "slot": {
                            "date": slot.get("date"),
                            "start": slot.get("start"),
                            "end": slot.get("end"),
                        },
                        "success": result.success,
                        "message": result.message,
                        "order_id": result.order_id,
                    }
                )

                if result.success:
                    monitor_info["successful_bookings"] += 1
                    monitor_info["status"] = "completed"
                    success_for_user = True
                    break

            except Exception as exc:  # pylint: disable=broad-except
                last_message = str(exc)
                monitor_info["last_booking_error"] = last_message

            await asyncio.sleep(min(6.0, 2.0 + slot_index * 1.5))

        if not success_for_user:
            monitor_info["last_booking_results"].append(
                {
                    "user": user.nickname,
                    "username": user.username,
                    "success": False,
                    "message": last_message,
                }
            )

        if user_index < len(user_sequence):
            await asyncio.sleep(2.5)


async def _schedule_worker(job_id: str) -> None:
    """定时任务工作线程"""
    job_info = _scheduled_jobs.get(job_id)
    if not job_info:
        return
    
    try:
        while job_id in _scheduled_jobs and job_info["status"] == "scheduled":
            now = datetime.now()
            target_time = now.replace(
                hour=job_info["hour"],
                minute=job_info["minute"],
                second=job_info["second"],
                microsecond=0
            )
            
            # 如果目标时间已过，设置为明天
            if target_time <= now:
                target_time += timedelta(days=1)
            
            job_info["next_run"] = target_time.isoformat()
            
            # 等待到目标时间
            wait_seconds = (target_time - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # 执行任务
            if job_id in _scheduled_jobs:
                await _execute_scheduled_job(job_id)
                
    except Exception as e:
        job_info["status"] = "error"
        job_info["error"] = str(e)


async def _execute_scheduled_job(job_id: str) -> None:
    """执行定时任务"""
    job_info = _scheduled_jobs.get(job_id)
    if not job_info:
        return
    
    job_info["last_run"] = datetime.now().isoformat()
    job_info["run_count"] += 1
    
    try:
        base_target = job_info.get("base_target") or BookingTarget()
        target_users = list(
            job_info.get("target_users")
            or getattr(base_target, "target_users", [])
            or []
        )
        exclude_users = set(
            job_info.get("exclude_users")
            or getattr(base_target, "exclude_users", [])
            or []
        )

        raw_start_hours = job_info.get("start_hours")
        if raw_start_hours:
            start_hours = []
            for entry in raw_start_hours:
                try:
                    value = int(entry)
                    if 0 <= value <= 23:
                        start_hours.append(value)
                except (TypeError, ValueError):
                    continue
        else:
            fallback = job_info.get("start_hour")
            if fallback is None:
                fallback = getattr(base_target, "start_hour", 18)
            try:
                start_hours = [int(fallback)]
            except (TypeError, ValueError):
                start_hours = []

        if not start_hours:
            start_hours = [18]

        # 去重并排序
        start_hours = [h for h in start_hours if 0 <= h <= 23]
        if not start_hours:
            start_hours = [18]
        start_hours = sorted(dict.fromkeys(start_hours))
        job_info["start_hours"] = start_hours
        job_info["start_hour"] = start_hours[0]

        available_users = [u for u in getattr(CFG.AUTH, "users", []) or [] if u.cookie]
        if target_users:
            lowered_targets = {item.lower() for item in target_users}
            user_sequence = [
                u
                for u in available_users
                if (u.nickname and u.nickname.lower() in lowered_targets)
                or (u.username and u.username.lower() in lowered_targets)
            ]
        else:
            lowered_excludes = {item.lower() for item in exclude_users}
            user_sequence = [
                u
                for u in available_users
                if not (
                    (u.nickname and u.nickname.lower() in lowered_excludes)
                    or (u.username and u.username.lower() in lowered_excludes)
                )
            ]

        if not user_sequence:
            user_sequence = available_users[:1]

        db_manager = get_db_manager()

        for user in user_sequence:
            user_id = user.username or user.nickname
            user_success = False

            for hour in start_hours:
                start_label = f"{int(hour):02d}:00"
                for attempt in range(5):
                    result = await order_once(
                        preset=job_info["preset"],
                        date=job_info["date"] or "0",
                        start_time=start_label,
                        base_target=base_target,
                        user=user_id,
                        notification_context=f"来自定时任务 {job_id}",
                    )

                    if result.success:
                        job_info["success_count"] += 1
                        user_success = True
                        job_info.pop("last_error", None)
                        print(f"[schedule:{job_id}] 用户 {user_id} 在 {start_label} 下单成功: {result.message}")
                        break

                    job_info.setdefault("last_error", result.message)
                    print(
                        f"[schedule:{job_id}] 用户 {user_id} 在 {start_label} 下单失败 ({attempt + 1}/5): {result.message}"
                    )
                    await asyncio.sleep(1.0)

                if user_success:
                    break

            if not user_success:
                print(
                    f"[schedule:{job_id}] 用户 {user_id} 在 {', '.join(f'{h:02d}:00' for h in start_hours)} 全部尝试失败: {job_info.get('last_error', '未知原因')}"
                )

            await asyncio.sleep(2.5)

        await db_manager.save_scheduled_job(job_info)
            
    except Exception as e:
        job_info["last_error"] = str(e)


# =============================================================================
# 登录协同 API
# =============================================================================


def _resolve_credentials(
    username: Optional[str],
    password: Optional[str],
    *,
    user_id: Optional[str] = None,
    nickname: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    # 如果直接提供了用户名和密码，直接使用
    if username and password:
        return username, password

    candidate_identifiers: List[str] = []
    for value in (username, user_id, nickname):
        if value and value not in candidate_identifiers:
            candidate_identifiers.append(value)

    # 在多用户配置中优先匹配指定的用户
    matched_users: List[UserAuth] = []
    if hasattr(CFG.AUTH, "users") and CFG.AUTH.users:
        for ident in candidate_identifiers:
            for user in CFG.AUTH.users:
                if ident in {user.username, user.nickname}:
                    matched_users.append(user)
        # 如果提供了密码，但用户名缺失，补齐用户名
        if password and matched_users:
            target_user = matched_users[0]
            return target_user.username or username or user_id, password
        # 如果配置中保存了该用户的密码，优先使用
        for user in matched_users:
            if user.username and user.password:
                return user.username, user.password
        # 没有密码时返回用户名，后续逻辑会提示输入密码
        if matched_users:
            target = matched_users[0]
            return target.username, password

    # 检查单个用户配置
    resolved_user = username or getattr(CFG.AUTH, "username", None) or os.getenv("SJABOT_USER")
    resolved_pass = password or getattr(CFG.AUTH, "password", None) or os.getenv("SJABOT_PASS")
    
    if resolved_user and resolved_pass:
        return resolved_user, resolved_pass
    
    # 检查多用户配置
    if hasattr(CFG.AUTH, "users") and CFG.AUTH.users:
        # 优先使用第一个有密码的用户
        for user in CFG.AUTH.users:
            if user.username and user.password:
                return user.username, user.password
        # 如果没有密码，使用第一个有用户名的用户（需要手动输入密码）
        for user in CFG.AUTH.users:
            if user.username:
                return user.username, None
    
    return resolved_user, resolved_pass


async def start_login_session(
    *,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    nickname: Optional[str] = None,
) -> Dict[str, Any]:
    """启动登录流程，必要时返回验证码图片。"""
    resolved_user, resolved_pass = _resolve_credentials(
        username,
        password,
        user_id=user_id,
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

    session_id = f"login_{uuid.uuid4().hex[:8]}"
    session = LoginSession(
        session_id=session_id,
        client=client,
        state=state,
        username=resolved_user,
        password=resolved_pass,
        created_at=datetime.now(timezone.utc),
        user_id=user_id,
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
        sports_domain = urlparse(CFG.BASE_URL).hostname
        cookie_header = _cookie_header(client._client.cookies, domain=sports_domain)  # type: ignore[attr-defined]
        if not cookie_header:
            raise RuntimeError("登录失败，未获得 Cookie")

        expires_at = datetime.now(timezone.utc) + timedelta(hours=8)

        resolved_nickname = nickname
        try:
            if getattr(CFG.AUTH, "users", None):
                for user in CFG.AUTH.users:
                    if user.username == resolved_user:
                        user.cookie = cookie_header
                        resolved_nickname = resolved_nickname or user.nickname
                        break
            if not resolved_nickname:
                from .models import UserAuth
                nickname_guess = nickname or (resolved_user.split("@")[0] if "@" in resolved_user else resolved_user)
                new_user = UserAuth(nickname=nickname_guess, cookie=cookie_header, username=resolved_user)
                if not getattr(CFG.AUTH, "users", None):
                    CFG.AUTH.users = [new_user]
                else:
                    # 避免重复添加
                    if not any(u.username == resolved_user for u in CFG.AUTH.users):
                        CFG.AUTH.users.append(new_user)
                resolved_nickname = nickname_guess
        except Exception:
            resolved_nickname = nickname

        _auth_manager.save_cookie(cookie_header, expires_at, username=resolved_user, nickname=resolved_nickname)

        # 校验登录态
        api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH)
        try:
            if not api.check_auth_status():
                raise RuntimeError("登录成功但校验失败，请稍后重试")
        finally:
            api.close()

        await client.close()
        return {
            "success": True,
            "captcha_required": False,
            "message": "登录成功",
            "cookie": cookie_header,
            "expires_at": expires_at.isoformat(),
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

        sports_domain = urlparse(CFG.BASE_URL).hostname
        cookie_header = _cookie_header(session.client._client.cookies, domain=sports_domain)  # type: ignore[attr-defined]
        if not cookie_header:
            raise RuntimeError("验证码可能错误，未获取到 Cookie")

        expires_at = datetime.now(timezone.utc) + timedelta(hours=8)

        resolved_nickname = session.nickname
        try:
            if getattr(CFG.AUTH, "users", None):
                for user in CFG.AUTH.users:
                    if user.username == session.username:
                        user.cookie = cookie_header
                        resolved_nickname = resolved_nickname or user.nickname
                        break
            if not resolved_nickname:
                from .models import UserAuth
                nickname_guess = session.nickname or (session.username.split("@")[0] if "@" in session.username else session.username)
                new_user = UserAuth(nickname=nickname_guess, cookie=cookie_header, username=session.username)
                if not getattr(CFG.AUTH, "users", None):
                    CFG.AUTH.users = [new_user]
                else:
                    if not any(u.username == session.username for u in CFG.AUTH.users):
                        CFG.AUTH.users.append(new_user)
                resolved_nickname = nickname_guess
        except Exception:
            resolved_nickname = session.nickname

        _auth_manager.save_cookie(cookie_header, expires_at, username=session.username, nickname=resolved_nickname)

        api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH)
        try:
            if not api.check_auth_status():
                raise RuntimeError("框架未验证通过，请重新尝试")
        finally:
            api.close()

        await session.client.close()
        del _login_sessions[session_id]
        return {
            "success": True,
            "message": "登录成功",
            "cookie": cookie_header,
            "expires_at": expires_at.isoformat(),
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
                    "message": f"验证码错误，请重试 ({session.attempts}/5)",
                    "username": session.username,
                    "nickname": resolved_nickname,
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


def login_status() -> Dict[str, Any]:
    """获取当前登录状态信息。"""
    cookies_map, active_username = _auth_manager.load_all_cookies()
    if not cookies_map:
        return {"success": False, "message": "尚未保存任何登录凭据"}

    entries: List[Dict[str, Any]] = []
    for key, record in cookies_map.items():
        expires_at = record.get("expires_at")
        if isinstance(expires_at, datetime):
            expires_str = expires_at.isoformat()
        else:
            expires_str = str(expires_at)

        entries.append(
            {
                "key": key,
                "username": record.get("username"),
                "nickname": record.get("nickname"),
                "cookie": record.get("cookie"),
                "expires_at": expires_str,
                "is_active": key == active_username,
            }
        )

    return {
        "success": True,
        "active_user": active_username,
        "users": entries,
    }


# =============================================================================
# 自动抢票系统接口
# =============================================================================

async def start_auto_booking() -> Dict[str, Any]:
    """
    启动自动抢票系统
    
    Returns:
        启动结果
    """
    try:
        auto_booking = get_auto_booking_system()
        await auto_booking.initialize()
        return await auto_booking.start_auto_booking_scheduler()
    except Exception as e:
        return {"success": False, "message": f"启动自动抢票失败: {str(e)}"}


async def stop_auto_booking() -> Dict[str, Any]:
    """
    停止自动抢票系统
    
    Returns:
        停止结果
    """
    try:
        auto_booking = get_auto_booking_system()
        return await auto_booking.stop_auto_booking_scheduler()
    except Exception as e:
        return {"success": False, "message": f"停止自动抢票失败: {str(e)}"}


async def get_auto_booking_status() -> Dict[str, Any]:
    """
    获取自动抢票状态
    
    Returns:
        状态信息
    """
    try:
        auto_booking = get_auto_booking_system()
        return await auto_booking.get_booking_status()
    except Exception as e:
        return {"success": False, "message": f"获取自动抢票状态失败: {str(e)}"}


async def update_auto_booking_targets(targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    更新自动抢票目标配置
    
    Args:
        targets: 目标配置列表
        
    Returns:
        更新结果
    """
    try:
        auto_booking = get_auto_booking_system()
        await auto_booking.initialize()
        return await auto_booking.update_booking_targets(targets)
    except Exception as e:
        return {"success": False, "message": f"更新自动抢票目标失败: {str(e)}"}


async def get_auto_booking_results(limit: int = 10) -> Dict[str, Any]:
    """
    获取自动抢票历史结果
    
    Args:
        limit: 返回结果数量限制
        
    Returns:
        历史结果
    """
    try:
        db_manager = get_db_manager()
        results = await db_manager.load_auto_booking_results(limit)
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "message": f"获取自动抢票结果失败: {str(e)}"}


async def execute_manual_booking(target_date: str = None) -> Dict[str, Any]:
    """
    手动执行抢票（用于测试）
    
    Args:
        target_date: 目标日期，默认为7天后
        
    Returns:
        执行结果
    """
    try:
        auto_booking = get_auto_booking_system()
        await auto_booking.initialize()
        
        if not target_date:
            from datetime import datetime, timedelta
            target_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        # 手动执行抢票
        await auto_booking._execute_auto_booking()
        
        return {
            "success": True, 
            "message": f"手动抢票执行完成，目标日期: {target_date}",
            "results": auto_booking.booking_results
        }
    except Exception as e:
        return {"success": False, "message": f"手动抢票执行失败: {str(e)}"}
