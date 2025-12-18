from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import random
import re
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time
from time import monotonic
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

from .api import SportsAPI
from urllib.parse import urlparse

from .auth import AuthManager, AuthClient, AuthState, _cookie_header
from .models import DateAvailability, BookingTarget, FieldType, MonitorPlan, PresetOption, Slot, UserAuth, Venue
from .monitor import SlotMonitor
from .order import OrderManager, OrderResult
from .database import get_db_manager
from .auto_booking import get_auto_booking_system

try:
    import config as CFG
except ImportError as exc:  # pragma: no cover - configuration should exist
    raise RuntimeError("service module requires top-level config.py") from exc


_ORDER_ID_KEYS: Tuple[str, ...] = (
    "orderId",
    "order_id",
    "orderID",
    "orderid",
    "pOrderId",
    "pOrderid",
    "porderid",
    "id",
    "data",
)

_PARALLEL_ORDER_JITTER_RANGE: Tuple[float, float] = (0.05, 0.35)
_SCHEDULE_ORDER_MAX_RETRIES: int = 3


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _extract_order_identifier(payload: Any) -> Optional[str]:
    """Best-effort extraction of order identifiers from nested payloads."""
    if payload is None:
        return None
    if isinstance(payload, (int, float)):
        value = int(payload)
        return str(value) if value else None
    if isinstance(payload, str):
        text = payload.strip()
        return text or None
    if isinstance(payload, dict):
        for key in _ORDER_ID_KEYS:
            if key not in payload:
                continue
            candidate = _extract_order_identifier(payload[key])
            if candidate:
                return candidate
    return None


def _resolve_order_identifier(result: OrderResult) -> Optional[str]:
    direct = _extract_order_identifier(result.order_id)
    if direct:
        return direct
    return _extract_order_identifier(result.raw_response)


def resolve_order_identifier(result: OrderResult) -> Optional[str]:
    """Public wrapper to expose order id extraction to API layer."""
    return _resolve_order_identifier(result)


@dataclass(frozen=True)
class OrderScopeInfo:
    key: str
    category: str
    venue_id: Optional[str]
    venue_name: Optional[str]
    field_type_id: Optional[str]
    field_type_name: Optional[str]


_ACTIVE_ORDER_STATES: Set[str] = {"pending_payment", "confirmed"}


def _normalize_label(value: Optional[str]) -> str:
    return str(value or "").strip()


def _detect_activity_category(
    venue_name: Optional[str],
    field_type_name: Optional[str],
) -> str:
    text = f"{venue_name or ''} {field_type_name or ''}".lower()
    if any(keyword in text for keyword in ("健身", "gym", "fitness")):
        return "gym"
    if "羽毛球" in text or "badminton" in text:
        return "badminton"
    if "网球" in text or "tennis" in text:
        return "tennis"
    if "篮球" in text or "basketball" in text:
        return "basketball"
    return (_normalize_label(field_type_name) or _normalize_label(venue_name) or "unknown").lower()


def _build_order_scope(
    *,
    venue_id: Optional[str],
    venue_name: Optional[str],
    field_type_id: Optional[str],
    field_type_name: Optional[str],
) -> OrderScopeInfo:
    venue_component = _normalize_label(venue_id) or _normalize_label(venue_name) or "unknown-venue"
    field_component = _normalize_label(field_type_id) or _normalize_label(field_type_name) or "any"
    category = _detect_activity_category(venue_name, field_type_name)
    scope_key = f"{venue_component.lower()}|{field_component.lower()}|{category}"
    return OrderScopeInfo(
        key=scope_key,
        category=category,
        venue_id=venue_id,
        venue_name=venue_name,
        field_type_id=field_type_id,
        field_type_name=field_type_name,
    )


def _normalize_user_key(user_obj: Optional[UserAuth], identifier: Optional[str]) -> str:
    for candidate in (
        _normalize_label(identifier),
        _normalize_label(getattr(user_obj, "username", None)),
        _normalize_label(getattr(user_obj, "nickname", None)),
    ):
        if candidate:
            return candidate
    return "anonymous"


def _reservation_index_key(user_key: str, scope_key: str, date: str) -> str:
    return f"{user_key}|{scope_key}|{date}"


def _ensure_reservation_index(container: Dict[str, Any]) -> Dict[str, Any]:
    index = container.get("reservation_index")
    if not isinstance(index, dict):
        index = {}
        container["reservation_index"] = index
    return index


async def _record_order_status_entry(
    *,
    user_key: str,
    scope: OrderScopeInfo,
    date: str,
    status: str,
    order_id: Optional[str],
    source: Optional[str],
    message: Optional[str],
) -> None:
    db_manager = get_db_manager()
    await db_manager.upsert_order_status(
        user_key=user_key,
        scope_key=scope.key,
        venue_id=scope.venue_id,
        venue_name=scope.venue_name,
        field_type_id=scope.field_type_id,
        field_type_name=scope.field_type_name,
        category=scope.category,
        date=date,
        status=status,
        order_id=order_id,
        source=source,
        message=message,
    )


async def _get_existing_order_status(
    *,
    user_key: str,
    scope_key: str,
    date: str,
) -> Optional[Dict[str, Any]]:
    db_manager = get_db_manager()
    record = await db_manager.get_order_status(user_key, scope_key, date)
    if record and str(record.get("status") or "") in _ACTIVE_ORDER_STATES:
        return record
    return None


async def _get_existing_order_status_for_dates(
    *,
    user_key: str,
    scope_key: str,
    dates: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    db_manager = get_db_manager()
    records = await db_manager.get_order_status_for_dates(user_key, scope_key, list(dates))
    filtered: Dict[str, Dict[str, Any]] = {}
    for date_key, record in records.items():
        if str(record.get("status") or "") in _ACTIVE_ORDER_STATES:
            filtered[date_key] = record
    return filtered


def _format_existing_order_message(
    *,
    venue_name: Optional[str],
    field_type_name: Optional[str],
    date: str,
    status: Optional[str],
    order_id: Optional[str],
) -> str:
    status_label = "待支付" if status == "pending_payment" else "已预订"
    order_label = order_id or "未知订单"
    venue_label = venue_name or "该场馆"
    field_label = field_type_name or "项目"
    return f"{venue_label} · {field_label} {date} 已存在{status_label}订单（{order_label}），跳过重复下单。"


async def _notify_existing_order(
    *,
    user_label: str,
    venue_name: Optional[str],
    field_type_name: Optional[str],
    date: str,
    order_id: Optional[str],
    message: str,
) -> None:
    if not getattr(CFG, "ENABLE_NOTIFICATION", True):
        return
    try:
        from .notification import send_order_notification
    except Exception:  # pylint: disable=broad-except
        return
    try:
        await send_order_notification(
            order_id=order_id or f"existing-{date}",
            user_nickname=user_label or "未知用户",
            venue_name=venue_name or "未知场馆",
            field_type_name=field_type_name or "未知项目",
            date=date,
            start_time="-",
            end_time="-",
            success=True,
            message=message,
            target_groups=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("groups"),
            target_users=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("users"),
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug("发送已有订单通知失败", exc_info=True)


def _normalise_operating_hours(
    start_raw: Optional[Any],
    end_raw: Optional[Any],
) -> Tuple[int, int]:
    try:
        start = int(start_raw) if start_raw is not None else 0
    except (TypeError, ValueError):
        start = 0
    try:
        end = int(end_raw) if end_raw is not None else 24
    except (TypeError, ValueError):
        end = 24

    start = max(0, min(24, start))
    end = max(0, min(24, end))

    if start == end:
        return 0, 24
    if start > end:
        start, end = end, start
    return start, end


def _seconds_until_operating_window(monitor_info: Dict[str, Any]) -> Tuple[int, Optional[datetime]]:
    start_hour, end_hour = _normalise_operating_hours(
        monitor_info.get("operating_start_hour"),
        monitor_info.get("operating_end_hour"),
    )

    if start_hour <= 0 and end_hour >= 24:
        return 0, None

    now = datetime.now()
    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
    start_seconds = start_hour * 3600
    end_seconds = end_hour * 3600

    if start_seconds <= current_seconds < end_seconds:
        return 0, None

    if current_seconds < start_seconds:
        wait_seconds = start_seconds - current_seconds
    else:
        wait_seconds = 24 * 3600 - current_seconds + start_seconds

    next_start = now + timedelta(seconds=wait_seconds)
    return wait_seconds, next_start


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
    if hour is not None:
        slot.start = f"{hour:02d}:00"

    end_hour = _slot_label_to_hour(slot.end)
    if end_hour is not None:
        slot.end = f"{end_hour:02d}:00"
    elif hour is not None:
        slot.end = f"{(hour + 1) % 24:02d}:00"
    return hour


def _resolve_slot_labels(slot: Slot, fallback_hour: Optional[int]) -> Tuple[str, str]:
    """Return normalized start/end labels for a slot, falling back to hour when missing."""
    start_label = slot.start or (f"{int(fallback_hour):02d}:00" if fallback_hour is not None else "00:00")
    if ":" not in start_label:
        try:
            start_value = int(float(start_label)) % 24
            start_label = f"{start_value:02d}:00"
        except (TypeError, ValueError):
            start_label = "00:00"

    end_label = slot.end or _next_hour(start_label, 1)
    if ":" not in end_label:
        try:
            end_value = int(float(end_label)) % 24
            end_label = f"{end_value:02d}:00"
        except (TypeError, ValueError):
            end_label = _next_hour(start_label, 1)

    return start_label, end_label


def _availability_to_dict(entry: SlotAvailability) -> Dict[str, Any]:
    slot = entry.slot
    resolved_hour = _normalise_slot_times(slot)
    start_label = slot.start or (f"{resolved_hour:02d}:00" if resolved_hour is not None else "-")
    end_label = slot.end
    if (not end_label or end_label == "-") and start_label not in {None, "-"}:
        end_label = _next_hour(start_label, getattr(slot, "duration_hours", 1))

    return {
        "date": entry.date,
        "start": start_label,
        "end": end_label,
        "available": slot.available,
        "remain": slot.remain,
        "price": slot.price,
        "field_name": slot.field_name,
        "area_name": slot.area_name,
        "slot_id": slot.slot_id,
        "sign": slot.sign,
        "sub_site_id": slot.sub_site_id,
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


_SPACE_INFO_TIME_PATTERN = re.compile(r"(\d{1,2})[:：](\d{2})")


def _extract_hour_from_space_info(space_info: Optional[str]) -> Optional[int]:
    if not space_info:
        return None
    match = _SPACE_INFO_TIME_PATTERN.search(space_info)
    if not match:
        return None
    try:
        hour = int(match.group(1))
    except ValueError:
        return None
    if 0 <= hour <= 23:
        return hour
    return None


def _hour_within_gap(reference: int, candidate: Optional[int], max_gap: int) -> bool:
    if candidate is None:
        return False
    return abs(candidate - reference) <= max_gap


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


def _list_date_availability_sync(
    venue_id: str,
    field_type_id: str,
    *,
    active_user: Optional[str] = None,
) -> List[DateAvailability]:
    api = _create_api(active_user=active_user)
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
    active_user = await _next_query_user_identifier()
    dates = await asyncio.to_thread(
        _list_date_availability_sync,
        resolved.venue_id,
        resolved.field_type_id,
        active_user=active_user,
    )
    # Ensure consistent ordering and deduplicate by date
    seen: Dict[str, DateAvailability] = {}
    for entry in dates:
        if entry.date not in seen or entry.selectable:
            seen[entry.date] = entry
    ordered_all = sorted(seen.values(), key=lambda item: item.date)
    ordered = [entry for entry in ordered_all if entry.selectable]
    return DateAvailabilityResult(resolved=resolved, dates=ordered)


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
    all_dates: bool,
    active_user: Optional[str] = None,
) -> SlotListResult:
    api = _create_api(active_user=active_user)
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
    active_user = await _next_query_user_identifier()
    return await asyncio.to_thread(
        _list_slots_sync,
        preset=preset,
        venue_id=venue_id,
        field_type_id=field_type_id,
        date=date,
        start_hour=start_hour,
        show_full=show_full,
        base_target=base_target,
        all_dates=all_dates,
        active_user=active_user,
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

    preset_option = _get_preset(preset)
    if not preset_option:
        return OrderResult(success=False, message=f"未找到预设 {preset}")

    user_obj = _find_user(user)
    user_key = _normalize_user_key(user_obj, user)
    scope = _build_order_scope(
        venue_id=preset_option.venue_id,
        venue_name=preset_option.venue_name,
        field_type_id=preset_option.field_type_id,
        field_type_name=preset_option.field_type_name,
    )

    enforce_user_limit = user_key != "anonymous"

    if enforce_user_limit:
        existing_record = await _get_existing_order_status(
            user_key=user_key,
            scope_key=scope.key,
            date=normalized_date,
        )
        if existing_record:
            message = _format_existing_order_message(
                venue_name=scope.venue_name,
                field_type_name=scope.field_type_name,
                date=normalized_date,
                status=existing_record.get("status"),
                order_id=existing_record.get("order_id"),
            )
            user_label = _normalize_label(getattr(user_obj, "nickname", None)) or user_key
            await _notify_existing_order(
                user_label=user_label,
                venue_name=scope.venue_name,
                field_type_name=scope.field_type_name,
                date=normalized_date,
                order_id=existing_record.get("order_id"),
                message=message,
            )
            return OrderResult(
                success=False,
                message=message,
                order_id=existing_record.get("order_id"),
                raw_response={"skipped": "existing_order"},
            )

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

            resolved_order_id = _resolve_order_identifier(result) or "unknown"

            await db_manager.save_booking_record(
                order_id=resolved_order_id,
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
        
        if result.success and enforce_user_limit:
            await _record_order_status_entry(
                user_key=user_key,
                scope=scope,
                date=normalized_date,
                status="pending_payment",
                order_id=_resolve_order_identifier(result),
                source=notification_context or "manual",
                message=result.message,
            )
        
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

                venue_name = scope.venue_name or f"预设{preset}"
                field_type_name = scope.field_type_name or "未知"

                notify_message = result.message
                if notification_context:
                    notify_message = f"{notification_context}\n{result.message}"

                await send_order_notification(
                    order_id=resolved_order_id,
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


async def cancel_order(order_id: str, *, user: Optional[str] = None) -> Dict[str, Any]:
    """取消指定订单，触发退款流程"""
    order_id_text = str(order_id or "").strip()
    if not order_id_text:
        return {"success": False, "message": "订单ID不能为空"}

    api = _create_api(active_user=user)
    try:
        responses = api.cancel_order(order_id_text)
        messages: List[str] = []
        success = True
        for entry in responses:
            if isinstance(entry, dict):
                code = str(entry.get("code") or entry.get("status") or entry.get("codeEn") or "")
                msg = entry.get("msg") or entry.get("message") or entry.get("msgEn") or ""
                if code and code not in {"1", "2", "3"}:
                    success = False
                if msg:
                    messages.append(str(msg))
                elif code:
                    messages.append(f"code={code}")
            else:
                messages.append(str(entry))
        if not messages:
            messages.append("退款流程已提交")
        
        # 取消订单成功后，删除对应的订单状态索引
        if success:
            try:
                db_manager = get_db_manager()
                deleted = await db_manager.delete_order_status_by_order_id(order_id_text)
                if deleted:
                    logger.info("已删除订单状态索引: order_id=%s", order_id_text)
                else:
                    logger.debug("未找到对应的订单状态索引: order_id=%s", order_id_text)
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("删除订单状态索引时出错: order_id=%s, error=%s", order_id_text, e)
        
        return {
            "success": success,
            "message": "；".join(messages),
            "steps": responses,
        }
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("取消订单失败: %s (user=%s)", order_id_text, user)
        return {"success": False, "message": str(exc)}
    finally:
        try:
            api.close()
        except Exception:  # pylint: disable=broad-except
            pass


# =============================================================================
# 监控和调度相关接口
# =============================================================================

# 全局任务存储（初期使用内存字典）
_active_monitors: Dict[str, Dict] = {}
_scheduled_jobs: Dict[str, Dict] = {}
_pending_payment_tasks: Dict[str, asyncio.Task] = {}
_paused_monitors: Dict[str, Dict[str, Any]] = {}
_auth_manager = AuthManager()
_QUERY_USER_CYCLE_TTL = 180.0  # seconds
_query_user_cycle: Deque[str] = deque()
_query_user_cycle_refreshed_at: float = 0.0
_query_cycle_lock: Optional[asyncio.Lock] = None
_query_cycle_last_used: Optional[str] = None


def _get_query_cycle_lock() -> asyncio.Lock:
    global _query_cycle_lock
    if _query_cycle_lock is None:
        _query_cycle_lock = asyncio.Lock()
    return _query_cycle_lock


def _resolve_cycle_identifier(entry: Dict[str, Any]) -> Optional[str]:
    candidates: List[str] = []
    for key in ("nickname", "username", "key"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    for candidate in candidates:
        if _find_user(candidate):
            return candidate
    return None


async def _refresh_query_user_cycle_locked() -> None:
    global _query_user_cycle, _query_user_cycle_refreshed_at, _query_cycle_last_used
    candidate_identifiers: List[str] = []
    status: Optional[Dict[str, Any]] = None
    try:
        status = await asyncio.to_thread(login_status)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("刷新在线用户列表失败，将回退到本地凭据: %s", exc)

    users_payload = status.get("users") if isinstance(status, dict) else None
    if isinstance(users_payload, list):
        for entry in users_payload:
            if not isinstance(entry, dict):
                continue
            identifier = _resolve_cycle_identifier(entry)
            if identifier:
                candidate_identifiers.append(identifier)

    cookies_map, _ = _auth_manager.load_all_cookies()
    for key, record in cookies_map.items():
        identifier = _resolve_cycle_identifier(
            {
                "nickname": record.get("nickname"),
                "username": record.get("username"),
                "key": key,
            }
        )
        if identifier:
            candidate_identifiers.append(identifier)

    for user in getattr(CFG.AUTH, "users", []) or []:
        if not (user.cookie or user.token):
            continue
        identifier = user.nickname or user.username
        if identifier:
            candidate_identifiers.append(identifier)

    deduped: List[str] = []
    seen: Set[str] = set()
    for identifier in candidate_identifiers:
        normalized = identifier.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    if _query_cycle_last_used and _query_cycle_last_used in deduped and len(deduped) > 1:
        start_idx = (deduped.index(_query_cycle_last_used) + 1) % len(deduped)
        deduped = deduped[start_idx:] + deduped[:start_idx]

    _query_user_cycle = deque(deduped)
    _query_user_cycle_refreshed_at = monotonic()


async def _next_query_user_identifier() -> Optional[str]:
    global _query_cycle_last_used
    lock = _get_query_cycle_lock()
    async with lock:
        now = monotonic()
        needs_refresh = not _query_user_cycle or (now - _query_user_cycle_refreshed_at) >= _QUERY_USER_CYCLE_TTL
        if needs_refresh:
            await _refresh_query_user_cycle_locked()
        if not _query_user_cycle:
            return None
        identifier = _query_user_cycle[0]
        _query_user_cycle.rotate(-1)
        _query_cycle_last_used = identifier
        return identifier


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
_TEST_FIELD_CACHE: Dict[str, Dict[str, Any]] = {}
_TEST_FIELD_FAIL_THRESHOLD = 3
_TEST_FIELD_CACHE_TTL = 3 * 3600  # seconds


def _pending_task_key(user_identifier: Optional[str], order_id: Optional[str]) -> Optional[str]:
    if not order_id:
        return None
    owner = (user_identifier or "").strip() or "__default__"
    return f"{owner}:{order_id}"


def _cleanup_test_field_cache(now: Optional[float] = None) -> None:
    """Remove expired cached test fields."""
    current = now or monotonic()
    expired_keys: List[str] = []
    for key, entry in _TEST_FIELD_CACHE.items():
        expires_at = entry.get("expires_at")
        try:
            if expires_at is not None and float(expires_at) <= current:
                expired_keys.append(key)
        except Exception:
            expired_keys.append(key)
    for key in expired_keys:
        _TEST_FIELD_CACHE.pop(key, None)


def _test_field_key(slot: Dict[str, Any], monitor_info: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Build a stable key to identify a slot/field across attempts."""
    venue_id = None
    resolved = monitor_info.get("resolved") if isinstance(monitor_info, dict) else None
    if isinstance(resolved, dict):
        venue_id = resolved.get("venue_id") or resolved.get("venueId")
    if not venue_id and isinstance(monitor_info, dict):
        venue_id = monitor_info.get("venue_id") or monitor_info.get("venueId")

    field_marker = (
        slot.get("slot_id")
        or slot.get("sign")
        or slot.get("sub_site_id")
        or slot.get("subSiteId")
        or slot.get("field_name")
    )
    date_str = slot.get("date") or (monitor_info.get("date") if isinstance(monitor_info, dict) else None)
    start_label = slot.get("start")
    if not field_marker:
        return None
    return "|".join(
        str(part or "").strip()
        for part in (venue_id or "unknown", field_marker, date_str or "", start_label or "")
    )


def _should_skip_test_field(cache_key: Optional[str]) -> bool:
    if not cache_key:
        return False
    _cleanup_test_field_cache()
    entry = _TEST_FIELD_CACHE.get(cache_key)
    if not entry:
        return False
    count = entry.get("count", 0)
    return count >= _TEST_FIELD_FAIL_THRESHOLD


def _record_test_field_failure(cache_key: Optional[str], reason: Optional[str] = None) -> None:
    if not cache_key:
        return
    _cleanup_test_field_cache()
    entry = _TEST_FIELD_CACHE.setdefault(cache_key, {"count": 0})
    entry["count"] = int(entry.get("count", 0) or 0) + 1
    if reason:
        entry["reason"] = reason
    entry["expires_at"] = monotonic() + _TEST_FIELD_CACHE_TTL


def _clear_test_field_flag(cache_key: Optional[str]) -> None:
    if not cache_key:
        return
    _TEST_FIELD_CACHE.pop(cache_key, None)


async def _fetch_order_record(user_identifier: Optional[str], order_id: str) -> Optional[Dict[str, Any]]:
    api = _create_api(active_user=user_identifier)
    try:
        response = api.list_orders(page_no=1, page_size=100)
        records: List[Dict[str, Any]] = []
        if isinstance(response, dict):
            payload = response.get("records") or response.get("orders") or []
            if isinstance(payload, list):
                records = [entry for entry in payload if isinstance(entry, dict)]

        order_id_text = str(order_id)
        for record in records:
            candidates = [
                record.get("orderId"),
                record.get("order_id"),
                record.get("pOrderid"),
                record.get("porderid"),
                record.get("orderid"),
                record.get("id"),
            ]
            if any(str(candidate) == order_id_text for candidate in candidates if candidate is not None):
                return record
        return None
    except Exception:  # pylint: disable=broad-except
        return None
    finally:
        try:
            api.close()
        except Exception:  # pylint: disable=broad-except
            pass


async def _send_pending_payment_reminder(
    *,
    monitor_id: str,
    user_nickname: str,
    order: Dict[str, Any],
) -> bool:
    if not getattr(CFG, "ENABLE_NOTIFICATION", True):
        return False

    try:
        from .notification import get_notification_service
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("无法加载通知模块，跳过待支付提醒: %s", exc)
        return False

    service = get_notification_service()
    payment_link = getattr(CFG, "NOTIFICATION_TEMPLATE", {}).get(
        "payment_link",
        "https://sports.sjtu.edu.cn/pc/order/list",
    )

    order_id_value = (
        order.get("pOrderid")
        or order.get("orderId")
        or order.get("order_id")
        or order.get("id")
        or "未知"
    )
    venue_name = order.get("venuename") or order.get("venname") or "未知场馆"
    activity = order.get("venname") or order.get("fieldTypeName") or order.get("field_name") or "未知项目"
    date_text = order.get("scDate") or order.get("ordercreatement", "")[:10]
    time_text = order.get("spaceInfo") or order.get("spaceInfoEn") or "-"

    lines = [
        f"⏰ 监控任务 {monitor_id} 仍有待支付订单",
        f"🆔 订单ID: {order_id_value}",
        f"👤 用户: {user_nickname}",
        f"🏟️ 场馆: {venue_name}",
        f"🏃 项目: {activity}",
    ]
    if date_text:
        lines.append(f"📅 日期: {date_text}")
    if time_text and time_text != "-":
        lines.append(f"⏰ 时间: {time_text}")
    lines.extend(
        [
            "",
            "💗 请尽快完成支付，逾期系统将自动取消订单。",
            f"🔗 支付链接: {payment_link}",
        ]
    )

    message = "\n".join(lines)
    targets = getattr(CFG, "NOTIFICATION_TARGETS", {}) or {}
    return await service.broadcast(
        message,
        target_groups=targets.get("groups"),
        target_users=targets.get("users"),
    )


async def _pending_payment_reminder_loop(
    *,
    monitor_id: str,
    user_identifier: Optional[str],
    user_nickname: str,
    order_id: str,
    preferred_hours: Optional[Iterable[int]],
    max_time_gap_hours: int,
    slot_hour: Optional[int],
    interval_seconds: int = 270,
    max_attempts: int = 5,
) -> None:
    preferred_set: Set[int] = set()
    for entry in preferred_hours or []:
        try:
            hour_value = int(entry)
        except (TypeError, ValueError):
            continue
        if 0 <= hour_value <= 23:
            preferred_set.add(hour_value)

    attempt = 0
    try:
        while attempt < max_attempts:
            attempt += 1
            if attempt > 1:
                await asyncio.sleep(interval_seconds)

            order = await _fetch_order_record(user_identifier, order_id)
            if not order:
                return

            state = str(order.get("orderstateid") or order.get("orderStateId") or "")
            if state != "0":
                return

            order_hour = _extract_hour_from_space_info(order.get("spaceInfo") or order.get("spaceInfoEn"))

            if slot_hour is not None and not _hour_within_gap(slot_hour, order_hour, max_time_gap_hours):
                return

            if preferred_set and (order_hour is None or order_hour not in preferred_set):
                return

            await _send_pending_payment_reminder(
                monitor_id=monitor_id,
                user_nickname=user_nickname,
                order=order,
            )
    finally:
        key = _pending_task_key(user_identifier, order_id)
        if key:
            _pending_payment_tasks.pop(key, None)


async def _schedule_pending_payment_reminder(
    *,
    monitor_id: str,
    user: UserAuth,
    order_id: Optional[str],
    slot: Dict[str, Any],
    monitor_info: Dict[str, Any],
) -> None:
    key = _pending_task_key(user.username or user.nickname, order_id)
    if not key or key in _pending_payment_tasks or not order_id:
        return

    preferred_hours = monitor_info.get("preferred_hours")

    slot_hour = _slot_dict_hour(slot)
    max_gap = max(0, int(monitor_info.get("max_time_gap_hours", 1) or 0))

    task = asyncio.create_task(
        _pending_payment_reminder_loop(
            monitor_id=monitor_id,
            user_identifier=user.username or user.nickname,
            user_nickname=user.nickname or user.username or "未知用户",
            order_id=str(order_id),
            preferred_hours=preferred_hours,
            max_time_gap_hours=max_gap,
            slot_hour=slot_hour,
        )
    )
    _pending_payment_tasks[key] = task


async def _attempt_order_with_backoff(
    *,
    job_id: str,
    preset: int,
    date: str,
    start_label: str,
    base_target: Optional[BookingTarget],
    user_id: Optional[str],
) -> OrderResult:
    """Place an order with adaptive retries to tolerate rate limits and empty slot windows."""
    max_attempts = 3
    rate_limit_keywords = ["请求过于频繁", "非法请求", "频率", "The read operation timed out", "超时"]
    existing_order_keywords = ["已有个人预约", "已存在订单", "冲突预定"]
    last_result: Optional[OrderResult] = None

    for attempt in range(1, max_attempts + 1):
        result = await order_once(
            preset=preset,
            date=date,
            start_time=start_label,
            base_target=base_target,
            user=user_id,
            notification_context=f"来自定时任务 {job_id}",
        )

        message = result.message or ""
        normalized_message = message.replace(" ", "")

        if result.success:
            return result

        if any(keyword in normalized_message for keyword in existing_order_keywords):
            print(f"[schedule:{job_id}] 用户 {user_id or '-'} 已有该时段订单，视为成功: {message}")
            return OrderResult(
                success=True,
                message=message,
                order_id=result.order_id,
                raw_response=result.raw_response,
            )

        last_result = result

        if any(keyword in normalized_message for keyword in rate_limit_keywords):
            wait_seconds = min(6.0, 2.0 + (attempt - 1) * 1.6)
            print(
                f"[schedule:{job_id}] 频率限制或网络波动，第 {attempt}/{max_attempts} 次失败，等待 {wait_seconds:.1f} 秒后重试: {message}"
            )
            await asyncio.sleep(wait_seconds)
            continue

        if "查询时间段失败" in message:
            wait_seconds = min(5.0, 1.5 + attempt * 1.2)
            print(
                f"[schedule:{job_id}] 查询时间段失败，第 {attempt}/{max_attempts} 次尝试后等待 {wait_seconds:.1f} 秒: {message}"
            )
            await asyncio.sleep(wait_seconds)
            continue

        return result

    return last_result or OrderResult(success=False, message="下单失败（查询或频率限制）", raw_response=None)


def _user_api_identifier(user: UserAuth) -> Optional[str]:
    if user.nickname:
        return user.nickname
    if user.username:
        return user.username
    return None


def _user_display_name(user: UserAuth) -> str:
    return user.nickname or user.username or "未命名用户"


async def _preload_slots_early(
    *,
    preset_option: Optional[PresetOption],
    date: str,
    start_hours: Optional[List[int]],
    base_target: Optional[BookingTarget],
) -> Dict[int, List[Slot]]:
    """提前预加载场次信息（带超时机制）"""
    if not preset_option:
        return {}

    # 🔥 优化2: 设置更短的超时时间，避免长时间等待
    try:
        result = await asyncio.wait_for(
            list_slots(
                preset=preset_option.index,
                date=date,
                start_hour=None,
                show_full=True,
                base_target=base_target,
            ),
            timeout=10.0  # 10秒超时
        )
    except asyncio.TimeoutError:
        logger.warning("预加载场次超时，跳过预加载")
        return {}
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("预加载定时任务场次失败: %s", exc)
        return {}

    hours_set: Optional[Set[int]] = None
    if start_hours:
        hours_set = {int(hour) for hour in start_hours}
    slot_map: Dict[int, List[Slot]] = {}

    for entry in result.slots:
        slot_hour = _normalise_slot_times(entry.slot)
        if slot_hour is None:
            continue
        if hours_set is not None and slot_hour not in hours_set:
            continue
        if not entry.slot.sign:
            continue
        slot_copy = dataclasses.replace(entry.slot)
        slot_map.setdefault(slot_hour, []).append(slot_copy)

    for hour, slots in slot_map.items():
        slots.sort(
            key=lambda s: (
                -(s.remain or 0),
                s.field_name or "",
                s.sign or "",
            )
        )
    return slot_map


async def _preload_slots_for_job(job_id: str, *, valid_window_seconds: float = 3.0) -> None:
    """为指定任务提前预加载场次信息"""
    job_info = _scheduled_jobs.get(job_id)
    if not job_info:
        return

    try:
        # 解析任务配置
        preset_option = _get_preset(job_info.get("preset"))
        if not preset_option:
            return

        target_date = _parse_date_input(str(job_info.get("date") or "0"))
        start_hours = job_info.get("start_hours")
        base_target = job_info.get("base_target") or BookingTarget()

        # 🔥 优化4: 使用更短的超时时间进行预加载
        logger.info(
            "[schedule:%s] 开始预加载场次信息: %s %s",
            job_id,
            target_date,
            start_hours if start_hours else "所有时段",
        )

        preloaded_slots = await _preload_slots_early(
            preset_option=preset_option,
            date=target_date,
            start_hours=list(start_hours) if start_hours else None,
            base_target=base_target,
        )

        # 保存预加载结果到任务信息中
        now = datetime.now()
        expire_delta = timedelta(seconds=max(0.5, float(valid_window_seconds)))
        job_info["preloaded_slots"] = preloaded_slots
        job_info["preload_time"] = now.isoformat()
        job_info["preload_expires_at"] = (now + expire_delta).isoformat()
        job_info["preload_success"] = bool(preloaded_slots)

        logger.info(
            "[schedule:%s] 预加载完成，获取到 %d 个时间段的场次",
            job_id,
            len(preloaded_slots)
        )

        # 保存到数据库
        await get_db_manager().save_scheduled_job(job_info)

    except Exception as e:
        logger.error("[schedule:%s] 预加载场次信息失败: %s", job_id, e)
        job_info["preload_success"] = False
        job_info["preload_error"] = str(e)


async def _get_slots_with_fallback(
    *,
    preset_option: Optional[PresetOption],
    date: str,
    start_hours: Optional[List[int]],
    base_target: Optional[BookingTarget],
    job_id: str,
) -> Dict[int, List[Slot]]:
    """快速获取场次信息，如果失败则返回空字典让系统继续下单"""
    try:
        # 🔥 优化6: 使用更短的超时时间（5秒），如果超时立即继续
        slot_pool = await asyncio.wait_for(
            _preload_slots_early(
                preset_option=preset_option,
                date=date,
                start_hours=start_hours,
                base_target=base_target,
            ),
            timeout=5.0  # 5秒超时
        )
        logger.info("[schedule:%s] 快速获取场次完成", job_id)
        return slot_pool
    except asyncio.TimeoutError:
        logger.warning("[schedule:%s] 获取场次超时，继续下单流程", job_id)
        return {}
    except Exception as e:
        logger.warning("[schedule:%s] 获取场次失败: %s，继续下单流程", job_id, e)
        return {}


async def _prepare_schedule_slots(
    *,
    preset_option: Optional[PresetOption],
    date: str,
    start_hours: List[int],
    base_target: Optional[BookingTarget],
) -> Dict[int, List[Slot]]:
    """原有的_prepare_schedule_slots函数（作为备用）"""
    return await _get_slots_with_fallback(
        preset_option=preset_option,
        date=date,
        start_hours=start_hours,
        base_target=base_target,
        job_id="manual",  # 手动调用时的任务ID
    )


async def _refresh_slot_pool(
    *,
    job_id: str,
    preset_option: Optional[PresetOption],
    date: str,
    hours: Optional[Iterable[int]],
    base_target: Optional[BookingTarget],
) -> Dict[int, List[Slot]]:
    """实时拉取场次，填充/更新 slot_pool。"""
    if not preset_option:
        return {}

    hours_set: Optional[Set[int]] = None
    if hours is not None:
        hours_set = set()
        for entry in hours:
            try:
                hours_set.add(int(entry))
            except Exception:  # pylint: disable=broad-except
                continue

    try:
        result = await list_slots(
            preset=preset_option.index,
            date=date,
            start_hour=None,
            show_full=True,
            base_target=base_target,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("[schedule:%s] 实时刷新场次失败: %s", job_id, exc)
        return {}

    refreshed: Dict[int, List[Slot]] = {}
    for entry in result.slots:
        slot_hour = _normalise_slot_times(entry.slot)
        if slot_hour is None:
            continue
        if hours_set is not None and slot_hour not in hours_set:
            continue
        if not entry.slot.available:
            continue
        slot_copy = dataclasses.replace(entry.slot)
        refreshed.setdefault(slot_hour, []).append(slot_copy)

    for hour, slots in refreshed.items():
        slots.sort(
            key=lambda s: (
                -(s.remain or 0),
                s.field_name or "",
                s.sign or "",
            )
        )

    return refreshed


async def _direct_order_attempt(
    *,
    job_id: str,
    hour: int,
    users: List[UserAuth],
    preset_option: PresetOption,
    date: str,
    request_timeout: float,
    base_target: Optional[BookingTarget],
) -> Dict[str, Dict[str, Any]]:
    """在无缓存时，直接查询目标小时的场次并并行抢票。"""
    try:
        live_slots = await list_slots(
            preset=preset_option.index,
            date=date,
            start_hour=hour,
            show_full=False,
            base_target=base_target,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("[schedule:%s] 直接查询小时 %s 失败: %s", job_id, hour, exc)
        return {}

    available_slots: List[Slot] = []
    for entry in live_slots.slots:
        slot_hour = _normalise_slot_times(entry.slot)
        if slot_hour is None or slot_hour != hour:
            continue
        if not entry.slot.available:
            continue
        available_slots.append(dataclasses.replace(entry.slot))

    # 如果目标小时仍然没有场次，尝试使用全量结果中对应小时的场次
    if not available_slots:
        for entry in live_slots.slots:
            slot_hour = _normalise_slot_times(entry.slot)
            if slot_hour is None or slot_hour != hour:
                continue
            available_slots.append(dataclasses.replace(entry.slot))

    if not available_slots:
        return {}

    available_slots.sort(
        key=lambda s: (
            -(s.remain or 0),
            s.field_name or "",
            s.sign or "",
        )
    )

    # 只挑一两个代表性场次进行并行下单，避免过多请求
    trimmed_slots = available_slots[:2]
    aggregated_results: Dict[str, Dict[str, Any]] = {}
    for slot in trimmed_slots:
        attempt_results = await _parallel_attempt_for_slot(
            job_id=job_id,
            hour=hour,
            slot=slot,
            users=users,
            preset_option=preset_option,
            date=date,
            request_timeout=request_timeout,
            max_retries=_SCHEDULE_ORDER_MAX_RETRIES,
        )
        # 合并结果：后续尝试不覆盖已成功的用户
        for identifier, payload in attempt_results.items():
            if identifier in aggregated_results and aggregated_results[identifier]["result"].success:
                continue
            aggregated_results[identifier] = payload

        # 如果至少有一个成功且不要求所有用户，这个小时可提前结束
        if any(payload["result"].success for payload in attempt_results.values()):
            break

        await asyncio.sleep(0.08)

    return aggregated_results


def _place_order_with_slot_sync(
    user_identifier: str,
    slot: Slot,
    preset_option: PresetOption,
    date: str,
    start_label: str,
    end_label: str,
    request_timeout: float,
    max_retries: int,
) -> OrderResult:
    api = _create_api(active_user=user_identifier)
    manager = OrderManager(
        api,
        CFG.ENCRYPTION_CONFIG,
        request_timeout=request_timeout,
    )
    try:
        slot_copy = dataclasses.replace(slot)
        return manager.place_order(
            slot_copy,
            preset_option,
            date,
            start_label,
            end_label,
            max_retries=max(1, int(max_retries)),
        )
    finally:
        api.close()


async def _place_order_with_slot_async(
    user_identifier: str,
    slot: Slot,
    preset_option: PresetOption,
    date: str,
    start_label: str,
    end_label: str,
    request_timeout: float,
    max_retries: int,
    jitter_range: Tuple[float, float] = (0.0, 0.0),
) -> OrderResult:
    upper = max(0.0, float(jitter_range[1])) if jitter_range else 0.0
    if upper > 0.0:
        lower = max(0.0, float(jitter_range[0]))
        lower = min(lower, upper)
        await asyncio.sleep(random.uniform(lower, upper))
    return await asyncio.to_thread(
        _place_order_with_slot_sync,
        user_identifier,
        slot,
        preset_option,
        date,
        start_label,
        end_label,
        request_timeout,
        max_retries,
    )


async def _parallel_attempt_for_slot(
    *,
    job_id: str,
    hour: int,
    slot: Slot,
    users: List[UserAuth],
    preset_option: PresetOption,
    date: str,
    request_timeout: float,
    max_retries: int,
    ) -> Dict[str, Dict[str, Any]]:
    if not users:
        return {}

    start_label, end_label = _resolve_slot_labels(slot, hour)
    print(
        f"[schedule:{job_id}] ⚡ 并行尝试 {start_label}-{end_label}，用户: "
        + ", ".join(_user_display_name(u) for u in users)
    )

    tasks: Dict[str, asyncio.Task[OrderResult]] = {}
    for user in users:
        identifier = _user_api_identifier(user)
        if not identifier:
            logger.warning("[schedule:%s] 用户 %s 缺少可用于下单的标识，已跳过", job_id, user)
            continue
        slot_copy = dataclasses.replace(slot)
        tasks[identifier] = asyncio.create_task(
            _place_order_with_slot_async(
                identifier,
                slot_copy,
                preset_option,
                date,
                start_label,
                end_label,
                request_timeout,
                max_retries,
                _PARALLEL_ORDER_JITTER_RANGE,
            )
        )

    results: Dict[str, Dict[str, Any]] = {}
    for user in users:
        identifier = _user_api_identifier(user)
        if not identifier or identifier not in tasks:
            continue
        try:
            order_result = await tasks[identifier]
        except Exception as exc:  # pylint: disable=broad-except
            order_result = OrderResult(False, f"并行下单异常: {exc}")
        if order_result.success:
            print(f"[schedule:{job_id}] ✅ 用户 {identifier} 下单成功: {order_result.message}")
        else:
            print(f"[schedule:{job_id}] ❌ 用户 {identifier} 下单失败: {order_result.message}")
        results[identifier] = {
            "result": order_result,
            "start": start_label,
            "end": end_label,
            "attempt_type": "parallel",
            "slot_hour": hour,
        }
    return results


async def _attempt_user_with_cached_slots(
    *,
    job_id: str,
    identifier: str,
    user: UserAuth,
    candidate_hours: Iterable[int],
    slot_pool: Dict[int, List[Slot]],
    preset_option: PresetOption,
    date: str,
    request_timeout: float,
    attempt_counts: Dict[str, int],
) -> Dict[str, Any]:
    """Sequentially attempt booking for a single user using cached slot information."""
    last_payload: Optional[Dict[str, Any]] = None
    attempted = False

    for hour in candidate_hours:
        slots_for_hour = slot_pool.get(hour, [])
        if not slots_for_hour:
            continue

        for candidate in slots_for_hour:
            attempted = True
            attempt_counts[identifier] = attempt_counts.get(identifier, 0) + 1
            start_label, end_label = _resolve_slot_labels(candidate, hour)
            slot_copy = dataclasses.replace(candidate)

            try:
                order_result = await _place_order_with_slot_async(
                    identifier,
                    slot_copy,
                    preset_option,
                    date,
                    start_label,
                    end_label,
                    request_timeout,
                    _SCHEDULE_ORDER_MAX_RETRIES,
                    (0.0, 0.0),
                )
            except Exception as exc:  # pylint: disable=broad-except
                order_result = OrderResult(False, f"缓存下单异常: {exc}")

            payload = {
                "result": order_result,
                "start": start_label,
                "end": end_label,
                "attempt_type": "cached",
                "slot_hour": hour,
                "attempts": attempt_counts[identifier],
            }
            last_payload = payload

            if order_result.success:
                print(
                    f"[schedule:{job_id}] ✅ 用户 {identifier} 在 {start_label}-{end_label} 成功（缓存场次）: {order_result.message}"
                )
                return payload

            print(
                f"[schedule:{job_id}] ❌ 用户 {identifier} 在 {start_label}-{end_label} 失败（缓存场次）: {order_result.message}"
            )

        await asyncio.sleep(0.18)

    if last_payload:
        return last_payload

    return {
        "result": OrderResult(False, "缓存的场次中未找到匹配时间段"),
        "start": "-",
        "end": "-",
        "attempt_type": "cached",
        "slot_hour": None,
        "attempts": attempt_counts.get(identifier, 0),
    }


async def _notify_schedule_failures(
    *,
    job_id: str,
    preset_option: Optional[PresetOption],
    date: str,
    failures: Dict[str, Dict[str, Any]],
    user_display_map: Dict[str, str],
) -> None:
    if not failures:
        return
    if not getattr(CFG, "ENABLE_ORDER_NOTIFICATION", True):
        return
    try:
        from .notification import send_order_notification
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("加载通知模块失败，无法发送定时任务失败通知: %s", exc)
        return

    venue_name = preset_option.venue_name if preset_option else "未知场馆"
    field_type_name = preset_option.field_type_name if preset_option else "未知项目"

    for identifier, payload in failures.items():
        display_name = user_display_map.get(identifier, identifier)
        result: OrderResult = payload["result"]
        start_label = payload.get("start") or "-"
        end_label = payload.get("end") or "-"
        attempts = payload.get("attempts", 1)
        message = (
            f"[定时任务 {job_id}] 用户 {display_name} 在 {start_label}-{end_label} "
            f"尝试 {attempts} 次仍未成功：{result.message}"
        )
        order_identifier = _resolve_order_identifier(result) or "unknown"
        try:
            await send_order_notification(
                order_id=order_identifier,
                user_nickname=display_name,
                venue_name=venue_name,
                field_type_name=field_type_name,
                date=date,
                start_time=start_label,
                end_time=end_label,
                success=False,
                message=message,
                target_groups=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("groups"),
                target_users=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("users"),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("发送定时任务失败通知异常: %s", exc)


async def _notify_schedule_successes(
    *,
    job_id: str,
    preset_option: Optional[PresetOption],
    date: str,
    successes: Dict[str, Dict[str, Any]],
    user_display_map: Dict[str, str],
) -> None:
    if not successes:
        return
    if not getattr(CFG, "ENABLE_ORDER_NOTIFICATION", True):
        return
    try:
        from .notification import send_order_notification
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("加载通知模块失败，无法发送定时任务成功通知: %s", exc)
        return

    venue_name = preset_option.venue_name if preset_option else "未知场馆"
    field_type_name = preset_option.field_type_name if preset_option else "未知项目"

    for identifier, payload in successes.items():
        display_name = user_display_map.get(identifier, identifier)
        result: OrderResult = payload["result"]
        start_label = payload.get("start") or "-"
        end_label = payload.get("end") or "-"
        attempts = payload.get("attempts", 1)
        message = (
            f"[定时任务 {job_id}] 用户 {display_name} 在 {start_label}-{end_label} "
            f"第 {attempts} 次尝试成功：{result.message}"
        )
        order_identifier = _resolve_order_identifier(result) or "unknown"
        try:
            await send_order_notification(
                order_id=order_identifier,
                user_nickname=display_name,
                venue_name=venue_name,
                field_type_name=field_type_name,
                date=date,
                start_time=start_label,
                end_time=end_label,
                success=True,
                message=message,
                target_groups=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("groups"),
                target_users=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("users"),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("发送定时任务成功通知异常: %s", exc)

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
    long_running: bool = False,
    require_all_users_success: bool = False,
    max_time_gap_hours: Optional[int] = None,
    operating_start_hour: Optional[int] = None,
    operating_end_hour: Optional[int] = None,
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
        long_running: 是否在成功预订后持续运行
        base_target: 基础目标配置
        
    Returns:
        监控任务信息
    """
    if monitor_id in _active_monitors or monitor_id in _paused_monitors:
        return {"success": False, "message": f"监控任务 {monitor_id} 已存在，请先停止或恢复"}
    
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
    if preferred_hours:
        working_target.start_hour = preferred_hours[0]

    default_plan = getattr(CFG, "MONITOR_PLAN", MonitorPlan())
    if max_time_gap_hours is None:
        max_gap_hours = getattr(default_plan, "max_time_gap_hours", 1)
    else:
        try:
            max_gap_hours = int(max_time_gap_hours)
        except (TypeError, ValueError):
            max_gap_hours = getattr(default_plan, "max_time_gap_hours", 1)
    max_gap_hours = max(0, min(max_gap_hours, 4))

    # 处理每日运行时段
    # 如果收到 None，使用默认值 09:00 - 18:00
    # 如果收到 0 和 24，表示全天运行
    if operating_start_hour is None:
        start_window = 9
    else:
        start_window = int(max(0, min(24, operating_start_hour)))
    
    if operating_end_hour is None:
        end_window = 18
    else:
        end_window = int(max(0, min(24, operating_end_hour)))
    
    # 如果开始和结束时间相同，或者明确设置为 0 和 24，表示全天运行
    if start_window == end_window:
        start_window, end_window = 0, 24
    elif start_window == 0 and end_window == 24:
        # 明确的全天运行，保持 0 和 24
        pass
    elif start_window > end_window:
        start_window, end_window = end_window, start_window

    monitor_info = {
        "id": monitor_id,
        "preset": preset,
        "venue_id": venue_id,
        "field_type_id": field_type_id,
        "date": date,
        "start_hour": start_hour,
        "interval_seconds": interval_seconds,
        "auto_book": auto_book,
        "long_running": bool(long_running),
        "require_all_users_success": require_all_users_success,
        "max_time_gap_hours": max_gap_hours,
        "operating_start_hour": start_window,
        "operating_end_hour": end_window,
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
        "window_active": True,
        "user_booking_history": {},
        "last_cycle_completed_at": None,
        "reservation_index": {},
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
    if monitor_id in _paused_monitors:
        monitor_info = _paused_monitors.pop(monitor_id)
        monitor_info["status"] = "stopped"
        monitor_info["stop_time"] = datetime.now().isoformat()
        db_manager = get_db_manager()
        await db_manager.save_monitor(monitor_info)
        return {"success": True, "message": f"监控任务 {monitor_id} 已停止"}

    if monitor_id not in _active_monitors:
        return {"success": False, "message": f"监控任务 {monitor_id} 不存在"}

    monitor_info = _active_monitors[monitor_id]
    monitor_info["status"] = "stopped"
    monitor_info["stop_time"] = datetime.now().isoformat()
    monitor_info["window_active"] = False
    monitor_info.pop("next_window_start", None)
    
    # 更新数据库
    db_manager = get_db_manager()
    await db_manager.save_monitor(monitor_info)
    
    del _active_monitors[monitor_id]
    
    return {"success": True, "message": f"监控任务 {monitor_id} 已停止"}


async def pause_monitor(monitor_id: str) -> Dict[str, Any]:
    if monitor_id not in _active_monitors:
        if monitor_id in _paused_monitors:
            return {"success": False, "message": f"监控任务 {monitor_id} 已暂停"}
        return {"success": False, "message": f"监控任务 {monitor_id} 不存在或未运行"}

    monitor_info = _active_monitors.pop(monitor_id)
    monitor_info["status"] = "paused"
    monitor_info["paused_time"] = datetime.now().isoformat()
    monitor_info["window_active"] = False
    monitor_info.pop("next_window_start", None)

    _paused_monitors[monitor_id] = monitor_info

    db_manager = get_db_manager()
    await db_manager.save_monitor(monitor_info)

    return {"success": True, "message": f"监控任务 {monitor_id} 已暂停"}


async def resume_monitor(monitor_id: str) -> Dict[str, Any]:
    if monitor_id in _active_monitors:
        return {"success": False, "message": f"监控任务 {monitor_id} 已在运行"}

    monitor_info = _paused_monitors.get(monitor_id)
    if not monitor_info:
        return {"success": False, "message": f"监控任务 {monitor_id} 不存在或未暂停"}

    monitor_info["status"] = "running"
    monitor_info.pop("paused_time", None)
    monitor_info["resume_time"] = datetime.now().isoformat()
    monitor_info.pop("next_window_start", None)
    monitor_info["window_active"] = True

    _active_monitors[monitor_id] = monitor_info
    del _paused_monitors[monitor_id]

    db_manager = get_db_manager()
    await db_manager.save_monitor(monitor_info)

    asyncio.create_task(_monitor_worker(monitor_id))

    return {"success": True, "message": f"监控任务 {monitor_id} 已恢复", "monitor_info": monitor_info}


async def monitor_status(monitor_id: Optional[str] = None) -> Dict[str, Any]:
    """
    获取监控任务状态
    
    Args:
        monitor_id: 监控任务标识，为None时返回所有任务
        
    Returns:
        监控状态信息
    """
    if monitor_id:
        if monitor_id in _active_monitors:
            return {"success": True, "monitor_info": _active_monitors[monitor_id]}
        if monitor_id in _paused_monitors:
            return {"success": True, "monitor_info": _paused_monitors[monitor_id]}
        return {"success": False, "message": f"监控任务 {monitor_id} 不存在"}

    combined: List[Dict[str, Any]] = []
    combined.extend(_active_monitors.values())
    combined.extend(_paused_monitors.values())
    return {"success": True, "monitors": combined}


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
    require_all_users_success: bool = False,
    max_time_gap_hours: Optional[int] = None,
    base_target: Optional[BookingTarget] = None,
    target_users: Optional[List[str]] = None,
    exclude_users: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    创建每日定时任务
    
    Args:
        job_id: 任务唯一标识
        hour: 执行小时 (0-23)
        minute: 执行分钟 (0-59)
        second: 执行秒 (0-59)
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
    
    # 验证执行时间范围
    if not (0 <= hour <= 23):
        return {"success": False, "message": f"执行小时必须在0-23之间，当前值: {hour}"}
    if not (0 <= minute <= 59):
        return {"success": False, "message": f"执行分钟必须在0-59之间，当前值: {minute}"}
    if not (0 <= second <= 59):
        return {"success": False, "message": f"执行秒数必须在0-59之间，当前值: {second}"}
    
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
    default_plan = getattr(CFG, "MONITOR_PLAN", MonitorPlan())
    if max_time_gap_hours is None:
        max_gap_hours = getattr(default_plan, "max_time_gap_hours", 1)
    else:
        try:
            max_gap_hours = int(max_time_gap_hours)
        except (TypeError, ValueError):
            max_gap_hours = getattr(default_plan, "max_time_gap_hours", 1)
    max_gap_hours = max(0, min(max_gap_hours, 4))
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
        "require_all_users_success": require_all_users_success,
        "max_time_gap_hours": max_gap_hours,
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
    monitor_info.pop("auto_stop_at", None)
    monitor_info.pop("run_until", None)

    # 更新数据库状态
    db_manager = get_db_manager()
    await db_manager.save_monitor(monitor_info)

    retry_count = 0
    max_retries = 3
    
    try:
        while monitor_id in _active_monitors and monitor_info["status"] == "running":
            wait_seconds, next_start = _seconds_until_operating_window(monitor_info)
            if wait_seconds > 0:
                next_start_iso = next_start.isoformat() if next_start else None
                state_changed = False
                if monitor_info.get("window_active", True):
                    monitor_info["window_active"] = False
                    state_changed = True
                if next_start_iso and monitor_info.get("next_window_start") != next_start_iso:
                    monitor_info["next_window_start"] = next_start_iso
                    state_changed = True
                if state_changed:
                    await db_manager.save_monitor(monitor_info)
                await asyncio.sleep(min(wait_seconds, max(30, monitor_info["interval_seconds"])))
                continue
            else:
                if not monitor_info.get("window_active", True) or monitor_info.get("next_window_start"):
                    monitor_info["window_active"] = True
                    monitor_info.pop("next_window_start", None)
                    await db_manager.save_monitor(monitor_info)
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
            current_status = monitor_info.get("status")
            if current_status not in {"stopped", "completed", "paused"}:
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
                            "sub_site_id": slot_info.get("sub_site_id"),
                        }
                    )

        filtered_slots = _filter_slots_by_preferences_dict(slots_payload, monitor_info)
        slots_payload = filtered_slots

        slots_payload = sorted(
            slots_payload,
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("start") or ""),
            ),
        )

        blocked_slots: List[str] = []
        usable_slots: List[Dict[str, Any]] = []
        for slot in slots_payload:
            cache_key = _test_field_key(slot, monitor_info)
            if _should_skip_test_field(cache_key):
                if cache_key:
                    blocked_slots.append(cache_key)
                continue
            usable_slots.append(slot)

        if blocked_slots:
            monitor_info["skipped_test_fields"] = blocked_slots
        slots_payload = usable_slots

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


def _resolve_monitor_preset_index(monitor_info: Dict[str, Any]) -> Optional[int]:
    preset_value = monitor_info.get("preset")
    if preset_value is not None:
        try:
            return int(preset_value)
        except (TypeError, ValueError):
            pass

    resolved = monitor_info.get("resolved") or {}
    venue_id = str(resolved.get("venue_id") or monitor_info.get("venue_id") or "").strip()
    field_type_id = str(resolved.get("field_type_id") or monitor_info.get("field_type_id") or "").strip()
    venue_name = str(resolved.get("venue_name") or monitor_info.get("venue_keyword") or "").strip().lower()
    field_type_name = str(resolved.get("field_type_name") or monitor_info.get("field_type_keyword") or "").strip().lower()

    for option in _iter_presets():
        if venue_id and field_type_id:
            if str(option.venue_id) == venue_id and str(option.field_type_id) == field_type_id:
                return option.index
        if venue_name and field_type_name:
            opt_venue = (option.venue_name or "").strip().lower()
            opt_field = (option.field_type_name or "").strip().lower()
            if opt_venue == venue_name and opt_field == field_type_name:
                return option.index
    return None


async def _notify_monitor_skip_reason(monitor_info: Dict[str, Any], monitor_id: str, reason: str) -> None:
    """Notify user when auto-book is skipped so the reason is visible in bot messages."""
    if not reason or not getattr(CFG, "ENABLE_NOTIFICATION", True):
        return
    if monitor_info.get("_last_skip_reason") == reason:
        return
    monitor_info["_last_skip_reason"] = reason

    try:
        from .notification import get_notification_service
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("加载通知服务失败，无法发送跳过原因: %s", exc)
        return

    resolved = monitor_info.get("resolved") or {}
    venue_name = resolved.get("venue_name") or monitor_info.get("venue_name") or monitor_info.get("venue_keyword")
    field_type_name = resolved.get("field_type_name") or monitor_info.get("field_type_id") or monitor_info.get("field_type_keyword")
    lines = [f"📡 监控任务 {monitor_id} 自动预订未执行"]
    if venue_name or field_type_name:
        lines.append(f"目标：{venue_name or '-'} / {field_type_name or '-'}")
    lines.append(f"原因：{reason}")

    try:
        service = get_notification_service()
        await service.broadcast(
            "\n".join(lines),
            target_groups=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("groups"),
            target_users=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("users"),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("发送监控跳过通知失败: %s", exc)


async def _auto_book_from_monitor(monitor_id: str, slots: List[Dict]) -> None:
    """从监控结果自动预订"""
    monitor_info = _active_monitors.get(monitor_id)
    if not monitor_info:
        return

    monitor_info["booking_attempts"] += 1
    monitor_info.setdefault("last_booking_results", [])
    preset_index = _resolve_monitor_preset_index(monitor_info)
    if preset_index is None:
        reason = "监控未关联有效预设，无法自动下单"
        monitor_info["last_booking_results"].append(
            {
                "user": None,
                "username": None,
                "success": False,
                "message": reason,
            }
        )
        monitor_info["last_booking_error"] = reason
        await _notify_monitor_skip_reason(monitor_info, monitor_id, reason)
        return

    monitor_info["preset"] = preset_index
    resolved_ctx = monitor_info.get("resolved") or {}
    scope = _build_order_scope(
        venue_id=monitor_info.get("venue_id") or resolved_ctx.get("venue_id"),
        venue_name=resolved_ctx.get("venue_name") or monitor_info.get("venue_keyword"),
        field_type_id=monitor_info.get("field_type_id") or resolved_ctx.get("field_type_id"),
        field_type_name=resolved_ctx.get("field_type_name") or monitor_info.get("field_type_keyword"),
    )
    reservation_index = _ensure_reservation_index(monitor_info)

    base_target = monitor_info.get("base_target") or BookingTarget()
    target_users = list(getattr(base_target, "target_users", []) or [])
    exclude_users = set(getattr(base_target, "exclude_users", []) or [])

    history: Dict[str, Dict[str, Any]] = monitor_info.setdefault("user_booking_history", {})
    long_running = bool(monitor_info.get("long_running"))

    available_users = [u for u in getattr(CFG.AUTH, "users", []) or [] if (u.cookie or u.token)]
    if not available_users:
        reason = "没有可用的登录账号，已跳过自动预订"
        monitor_info["last_booking_results"].append(
            {"user": None, "username": None, "success": False, "message": reason}
        )
        monitor_info["last_booking_error"] = reason
        await _notify_monitor_skip_reason(monitor_info, monitor_id, reason)
        return

    if target_users:
        user_sequence = [u for u in available_users if u.nickname in target_users]
    else:
        user_sequence = [u for u in available_users if u.nickname not in exclude_users]

    if not user_sequence:
        user_sequence = available_users[:1]

    if not user_sequence:
        reason = "未找到符合条件的账号，已跳过自动预订"
        monitor_info["last_booking_results"].append(
            {"user": None, "username": None, "success": False, "message": reason}
        )
        monitor_info["last_booking_error"] = reason
        await _notify_monitor_skip_reason(monitor_info, monitor_id, reason)
        return

    def _history_key(user_obj: UserAuth) -> str:
        return user_obj.nickname or user_obj.username or "anonymous"

    user_sequence = sorted(
        user_sequence,
        key=lambda user_obj: 1 if _history_key(user_obj) in history else 0,
    )

    # 检查是否需要所有用户都成功
    require_all_success = monitor_info.get("require_all_users_success", False)
    max_gap_hours = max(0, int(monitor_info.get("max_time_gap_hours", 1) or 0))
    
    # 逐个用户尝试预订
    successful_users: List[str] = []
    used_slot_keys: Set[str] = set()
    slot_usage: Dict[str, int] = {}
    slot_capacity: Dict[str, int] = {}
    total_capacity = 0
    def _slot_capacity(slot_item: Dict[str, Any]) -> int:
        candidates = [slot_item.get("remain"), slot_item.get("capacity")]
        for value in candidates:
            try:
                parsed = int(value)
                if parsed > 0:
                    return parsed
            except Exception:  # pylint: disable=broad-except
                continue
        return 1

    def _slot_key(slot_item: Dict[str, Any]) -> str:
        return str(
            slot_item.get("slot_id")
            or slot_item.get("sign")
            or f"{slot_item.get('date')}|{slot_item.get('start')}|{slot_item.get('field_name')}"
        )

    for slot in slots:
        if not slot.get("available", False):
            continue
        key = _slot_key(slot)
        cap = _slot_capacity(slot)
        slot_capacity[key] = max(1, cap)
        total_capacity += max(1, cap)

    slot_dates_all = sorted(
        {
            str(slot.get("date"))
            for slot in slots
            if slot.get("date") and slot.get("available", False)
        }
    )

    if require_all_success and total_capacity < len(user_sequence):
        monitor_info["last_booking_results"].append(
            {
                "user": None,
                "username": None,
                "success": False,
                "message": f"可用场次数 ({total_capacity}) 少于用户数 ({len(user_sequence)}), 本轮跳过自动预订",
            }
        )
        monitor_info["last_booking_error"] = "可用场次数不足，已跳过"
        await _notify_monitor_skip_reason(
            monitor_info,
            monitor_id,
            f"可用场次数 ({total_capacity}) 少于用户数 ({len(user_sequence)})，已跳过自动预订",
        )
        return

    reference_hour: Optional[int] = None

    for user_index, user in enumerate(user_sequence, 1):
        last_message = "未尝试"
        success_for_user = False
        user_id = user.username or user.nickname
        user_key = _normalize_user_key(user, user_id)

        history_key = _history_key(user)
        booking_record = history.get(history_key)

        if slot_dates_all:
            existing_status_map = await _get_existing_order_status_for_dates(
                user_key=user_key,
                scope_key=scope.key,
                dates=slot_dates_all,
            )
        else:
            existing_status_map = {}

        existing_block = None
        for date_key in sorted(existing_status_map.keys()):
            record = existing_status_map.get(date_key)
            if record:
                existing_block = (date_key, record)
                break

        if existing_block:
            date_key, record = existing_block
            message = _format_existing_order_message(
                venue_name=scope.venue_name,
                field_type_name=scope.field_type_name,
                date=date_key,
                status=record.get("status"),
                order_id=record.get("order_id"),
            )
            index_key = _reservation_index_key(user_key, scope.key, date_key)
            cached = reservation_index.get(index_key)
            if not cached or cached.get("order_id") != record.get("order_id") or cached.get("status") != "existing":
                user_label = user.nickname or user.username or user_key
                await _notify_existing_order(
                    user_label=user_label,
                    venue_name=scope.venue_name,
                    field_type_name=scope.field_type_name,
                    date=date_key,
                    order_id=record.get("order_id"),
                    message=message,
                )
            reservation_index[index_key] = {
                "status": "existing",
                "order_id": record.get("order_id"),
                "date": date_key,
                "updated_at": datetime.now().isoformat(),
            }
            monitor_info["last_booking_results"].append(
                {
                    "user": user.nickname,
                    "username": user.username,
                    "slot": {"date": date_key, "start": None, "end": None},
                    "success": True,
                    "message": message,
                    "order_id": record.get("order_id"),
                }
            )
            success_for_user = True
            successful_users.append(user.nickname or user.username or user_key)
            history[history_key] = {
                "date": date_key,
                "hour": None,
                "timestamp": datetime.now().isoformat(),
            }
            monitor_info["last_booking_error"] = None
            continue

        filtered_slots: List[Dict[str, Any]] = []
        for slot in slots:
            if not slot.get("available", False):
                continue
            key = _slot_key(slot)
            if key in used_slot_keys:
                continue
            capacity_left = slot_capacity.get(key, 1) - slot_usage.get(key, 0)
            if capacity_left <= 0:
                continue
            slot_hour = _slot_dict_hour(slot)
            if require_all_success and reference_hour is not None and not _hour_within_gap(reference_hour, slot_hour, max_gap_hours):
                continue
            if booking_record:
                last_date = booking_record.get("date")
                last_hour = booking_record.get("hour")
                if last_date and slot.get("date") == last_date:
                    continue
                if last_hour is not None and (slot_hour is None or abs(slot_hour - last_hour) > 1):
                    continue
            cache_key = _test_field_key(slot, monitor_info)
            if _should_skip_test_field(cache_key):
                continue
            filtered_slots.append(slot)

        for slot_index, slot in enumerate(filtered_slots, 1):
            slot_hour = _slot_dict_hour(slot)
            if require_all_success and reference_hour is not None and not _hour_within_gap(reference_hour, slot_hour, max_gap_hours):
                continue
            cache_key = _test_field_key(slot, monitor_info)
            if _should_skip_test_field(cache_key):
                continue
            key = _slot_key(slot)
            capacity_left = slot_capacity.get(key, 1) - slot_usage.get(key, 0)
            if capacity_left <= 0:
                continue

            logger.info(
                "#CZQ_DEBUG monitor-order attempt monitor=%s user=%s slot_date=%s start=%s available=%s remain=%s",
                monitor_id,
                user.nickname or user.username,
                slot.get("date"),
                slot.get("start"),
                slot.get("available"),
                slot.get("remain"),
            )
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

                resolved_order_id = _resolve_order_identifier(result)

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
                        "order_id": resolved_order_id,
                    }
                )
                last_result_entry = monitor_info["last_booking_results"][-1]
                date_label = slot.get("date") or monitor_info.get("date") or "-"
                skipped_existing = isinstance(result.raw_response, dict) and result.raw_response.get("skipped") == "existing_order"

                if result.success:
                    monitor_info["successful_bookings"] += 1
                    success_for_user = True
                    successful_users.append(user.nickname or user.username or user_key)
                    slot_usage[key] = slot_usage.get(key, 0) + 1
                    if slot_usage[key] >= slot_capacity.get(key, 1):
                        used_slot_keys.add(key)

                    if reference_hour is None and slot_hour is not None:
                        reference_hour = slot_hour
                    _clear_test_field_flag(cache_key)

                    history[history_key] = {
                        "date": slot.get("date"),
                        "hour": slot_hour,
                        "timestamp": datetime.now().isoformat(),
                    }
                    index_key = _reservation_index_key(user_key, scope.key, date_label)
                    reservation_index[index_key] = {
                        "status": "pending_payment",
                        "order_id": resolved_order_id,
                        "date": date_label,
                        "updated_at": datetime.now().isoformat(),
                    }
                    
                    await _schedule_pending_payment_reminder(
                        monitor_id=monitor_id,
                        user=user,
                        order_id=resolved_order_id,
                        slot=slot,
                        monitor_info=monitor_info,
                    )
                    await _notify_monitor_booking_result(
                        monitor_info=monitor_info,
                        monitor_id=monitor_id,
                        user=user,
                        slot=slot,
                        result=result,
                    )
                    break
                if skipped_existing:
                    success_for_user = True
                    successful_users.append(user.nickname or user.username or user_key)
                    last_result_entry["success"] = True
                    index_key = _reservation_index_key(user_key, scope.key, date_label)
                    reservation_index[index_key] = {
                        "status": "existing",
                        "order_id": resolved_order_id,
                        "date": date_label,
                        "updated_at": datetime.now().isoformat(),
                    }
                    history[history_key] = {
                        "date": date_label,
                        "hour": slot_hour,
                        "timestamp": datetime.now().isoformat(),
                    }
                    monitor_info["last_booking_error"] = None
                    break

            except Exception as exc:  # pylint: disable=broad-except
                last_message = str(exc)
                _record_test_field_failure(cache_key, last_message)
                monitor_info["last_booking_error"] = last_message
                logger.warning(
                    "#CZQ_DEBUG monitor-order exception monitor=%s user=%s error=%s",
                    monitor_id,
                    user.nickname or user.username,
                    exc,
                )
            else:
                if not result.success:
                    _record_test_field_failure(cache_key, last_message)

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

            await _notify_monitor_booking_result(
                monitor_info=monitor_info,
                monitor_id=monitor_id,
                user=user,
                slot=None,
                result=OrderResult(False, last_message),
            )
            
            # 如果需要所有用户成功但当前用户失败了，停止尝试
            if require_all_success and not success_for_user:
                break
        elif success_for_user and not require_all_success:
            break

        if user_index < len(user_sequence) and monitor_info.get("status") != "completed":
            await asyncio.sleep(2.5)
    
    if require_all_success:
        cycle_completed = len(successful_users) == len(user_sequence) and bool(user_sequence)
    else:
        cycle_completed = len(successful_users) > 0

    if cycle_completed:
        if long_running:
            monitor_info["status"] = "running"
            monitor_info["last_cycle_completed_at"] = datetime.now().isoformat()
        else:
            monitor_info["status"] = "completed"
    else:
        monitor_info["status"] = "running"

    monitor_info["user_booking_history"] = history

    try:
        await get_db_manager().save_monitor(monitor_info)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("保存监控任务状态失败: %s", exc)


async def _notify_monitor_booking_result(
    *,
    monitor_info: Dict[str, Any],
    monitor_id: str,
    user: UserAuth,
    slot: Optional[Dict[str, Any]],
    result: OrderResult,
) -> None:
    if not getattr(CFG, "ENABLE_ORDER_NOTIFICATION", True):
        return
    try:
        from .notification import send_order_notification
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("发送监控下单结果通知失败（加载模块失败）: %s", exc)
        return

    resolved = monitor_info.get("resolved") or {}
    venue_name = resolved.get("venue_name") or monitor_info.get("venue_name") or "未知场馆"
    field_type_name = resolved.get("field_type_name") or monitor_info.get("field_type_id") or "未知项目"
    start_label = "-"
    end_label = "-"
    date_label = "-"
    if slot:
        start_label = slot.get("start") or "-"
        end_label = slot.get("end") or "-"
        date_label = slot.get("date") or monitor_info.get("date") or "-"
    else:
        date_label = monitor_info.get("date") or "-"

    notification_message = (
        f"[监控 {monitor_id}] 用户 {user.nickname or user.username}"
        f" {'成功' if result.success else '失败'}：{result.message}"
    )

    order_identifier = _resolve_order_identifier(result) or "monitor-auto"
    try:
        await send_order_notification(
            order_id=order_identifier,
            user_nickname=user.nickname or user.username or "未知",
            venue_name=venue_name,
            field_type_name=field_type_name,
            date=date_label,
            start_time=start_label,
            end_time=end_label,
            success=result.success,
            message=notification_message,
            target_groups=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("groups"),
            target_users=getattr(CFG, "NOTIFICATION_TARGETS", {}).get("users"),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("发送监控下单结果通知失败: %s", exc)


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

            # 计算等待时间，提前执行以应对系统高并发
            wait_seconds = (target_time - now).total_seconds()

            preload_lead_seconds = float(getattr(CFG, "SCHEDULE_PRELOAD_SECONDS", 2.5))
            preload_lead_seconds = max(0.5, min(preload_lead_seconds, 10.0))
            if wait_seconds > preload_lead_seconds:
                sleep_before_preload = wait_seconds - preload_lead_seconds
                if sleep_before_preload > 0:
                    await asyncio.sleep(sleep_before_preload)

                logger.info("[schedule:%s] 等待执行，还有%.1f秒，开始预加载场次信息", job_id, wait_seconds)
                # 开始预加载
                try:
                    await _preload_slots_for_job(
                        job_id,
                        valid_window_seconds=preload_lead_seconds + 0.5,
                    )
                    logger.info("[schedule:%s] 场次信息预加载完成", job_id)
                except Exception as e:
                    logger.warning("[schedule:%s] 预加载失败: %s", job_id, e)

                remaining_wait = (target_time - datetime.now()).total_seconds()
                if remaining_wait > 0:
                    await asyncio.sleep(remaining_wait)
            else:
                # 如果剩余时间不足预加载窗口，直接等待到执行时间
                await asyncio.sleep(max(0.0, wait_seconds))
            
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

    db_manager = get_db_manager()

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
        start_hours: List[int] = []
        if raw_start_hours:
            for entry in raw_start_hours:
                try:
                    value = int(entry)
                except (TypeError, ValueError):
                    continue
                if 0 <= value <= 23:
                    start_hours.append(value)
        else:
            fallback = job_info.get("start_hour")
            if fallback is not None:
                try:
                    value = int(fallback)
                    if 0 <= value <= 23:
                        start_hours.append(value)
                except (TypeError, ValueError):
                    start_hours = []

        start_hours = sorted(dict.fromkeys(start_hours))
        job_info["start_hours"] = start_hours
        job_info["start_hour"] = start_hours[0] if start_hours else None

        available_users = [u for u in getattr(CFG.AUTH, "users", []) or [] if (u.cookie or u.token)]
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

        identifier_map: Dict[str, UserAuth] = {}
        user_display_map: Dict[str, str] = {}
        filtered_sequence: List[UserAuth] = []
        for user in user_sequence:
            identifier = _user_api_identifier(user)
            if not identifier:
                logger.warning("[schedule:%s] 用户缺少标识信息，跳过该用户。", job_id)
                continue
            if identifier in identifier_map:
                continue
            identifier_map[identifier] = user
            user_display_map[identifier] = _user_display_name(user)
            filtered_sequence.append(user)
        user_sequence = filtered_sequence

        if not user_sequence:
            job_info["last_error"] = "没有可用的用户凭据"
            job_info["last_results"] = []
            return

        try:
            target_date = _parse_date_input(str(job_info.get("date") or "0"))
        except Exception as exc:  # pylint: disable=broad-except
            job_info["last_error"] = f"解析目标日期失败: {exc}"
            job_info["last_results"] = []
            return

        try:
            preset_option = _get_preset(job_info.get("preset"))
        except Exception as exc:  # pylint: disable=broad-except
            job_info["last_error"] = f"预设配置无效: {exc}"
            job_info["last_results"] = []
            return

        if not preset_option:
            job_info["last_error"] = "定时任务缺少预设配置"
            job_info["last_results"] = []
            return

        auto_settings = getattr(CFG, "AUTO_BOOKING_SETTINGS", {})
        request_timeout = float(auto_settings.get("order_request_timeout", 3.0))

        # 🔥 优化1: 优先使用预加载的场次信息（仅在仍然有效时）
        slot_pool: Dict[int, List[Slot]] = {}
        preloaded_slots = job_info.get("preloaded_slots")
        if preloaded_slots:
            expires_at = _parse_iso_datetime(job_info.get("preload_expires_at"))
            if expires_at and expires_at >= datetime.now():
                logger.info("[schedule:%s] 使用预加载的场次信息，开始抢票", job_id)
                slot_pool = preloaded_slots
            else:
                logger.info("[schedule:%s] 预加载数据已过期，放弃使用并重新获取", job_id)
        if not slot_pool:
            logger.info("[schedule:%s] 没有预加载数据，实时获取场次信息...", job_id)
            # 🔥 优化5: 异步获取场次信息，不阻塞下单流程
            slot_pool = await _get_slots_with_fallback(
                preset_option=preset_option,
                date=target_date,
                start_hours=start_hours if start_hours else None,
                base_target=base_target,
                job_id=job_id,
            )
        if not slot_pool:
            refreshed = await _refresh_slot_pool(
                job_id=job_id,
                preset_option=preset_option,
                date=target_date,
                hours=start_hours if start_hours else None,
                base_target=base_target,
            )
            if refreshed:
                slot_pool = refreshed

        attempt_counts: Dict[str, int] = {identifier: 0 for identifier in identifier_map}
        results_map: Dict[str, Dict[str, Any]] = {}
        remaining_identifiers: List[str] = list(identifier_map.keys())

        require_all_success = job_info.get("require_all_users_success", False)
        max_gap_hours = max(0, int(job_info.get("max_time_gap_hours", 1) or 0))
        reference_hour: Optional[int] = None

        hours_to_try = start_hours if start_hours else sorted(slot_pool.keys())

        for hour in hours_to_try:
            if not remaining_identifiers:
                break
            if require_all_success and reference_hour is not None and not _hour_within_gap(reference_hour, hour, max_gap_hours):
                continue
            slots_for_hour = slot_pool.get(hour, [])

            current_users = [
                identifier_map[identifier]
                for identifier in remaining_identifiers
                if identifier in identifier_map
            ]
            if not current_users:
                continue

            # 🔥 优化7: 如果没有预加载到场次信息，立即尝试直接下单
            if not slots_for_hour and not slot_pool:
                logger.warning("[schedule:%s] 没有场次信息，尝试直接下单 %s", job_id, hour)
                # 直接尝试下单（可能会失败，但不应该阻塞）
                try:
                    direct_results = await _direct_order_attempt(
                        job_id=job_id,
                        hour=hour,
                        users=list(current_users),
                        preset_option=preset_option,
                        date=target_date,
                        request_timeout=request_timeout,
                        base_target=base_target,
                    )
                    if direct_results:
                        for identifier, payload in direct_results.items():
                            attempt_counts[identifier] = attempt_counts.get(identifier, 0) + 1
                            payload["attempts"] = attempt_counts[identifier]
                            results_map[identifier] = payload
                            if payload["result"].success:
                                job_info["success_count"] += 1
                                if reference_hour is None:
                                    reference_hour = hour

                        remaining_identifiers = [
                            identifier
                            for identifier in remaining_identifiers
                            if not (
                                identifier in direct_results
                                and direct_results[identifier]["result"].success
                            )
                        ]
                except Exception as e:
                    logger.warning("[schedule:%s] 直接下单尝试失败: %s", job_id, e)
                continue

            if not slots_for_hour:
                refreshed = await _refresh_slot_pool(
                    job_id=job_id,
                    preset_option=preset_option,
                    date=target_date,
                    hours=[hour],
                    base_target=base_target,
                )
                if refreshed:
                    slot_pool.update(refreshed)
                    slots_for_hour = slot_pool.get(hour, [])
                if not slots_for_hour:
                    continue

            for slot in slots_for_hour:
                parallel_results = await _parallel_attempt_for_slot(
                    job_id=job_id,
                    hour=hour,
                    slot=slot,
                    users=current_users,
                    preset_option=preset_option,
                    date=target_date,
                    request_timeout=request_timeout,
                    max_retries=_SCHEDULE_ORDER_MAX_RETRIES,
                )
                if not parallel_results:
                    continue

                for identifier, payload in parallel_results.items():
                    attempt_counts[identifier] = attempt_counts.get(identifier, 0) + 1
                    payload["attempts"] = attempt_counts[identifier]
                    results_map[identifier] = payload
                    if payload["result"].success:
                        job_info["success_count"] += 1
                        if reference_hour is None:
                            reference_hour = hour

                remaining_identifiers = [
                    identifier
                    for identifier in remaining_identifiers
                    if not (
                        identifier in parallel_results
                        and parallel_results[identifier]["result"].success
                    )
                ]
                if not remaining_identifiers:
                    break

                await asyncio.sleep(0.12)

            if not remaining_identifiers:
                break

        if remaining_identifiers:
            candidate_hours = list(start_hours if start_hours else hours_to_try)
            if require_all_success and reference_hour is not None:
                constrained = [
                    hour for hour in start_hours if _hour_within_gap(reference_hour, hour, max_gap_hours)
                ]
                if constrained:
                    candidate_hours = constrained

            if slot_pool and candidate_hours:
                missing_hours = [hour for hour in candidate_hours if hour not in slot_pool]
                if missing_hours:
                    refreshed = await _refresh_slot_pool(
                        job_id=job_id,
                        preset_option=preset_option,
                        date=target_date,
                        hours=missing_hours,
                        base_target=base_target,
                    )
                    if refreshed:
                        slot_pool.update(refreshed)
                        hours_to_try = sorted(set(hours_to_try + list(refreshed.keys())))

            for identifier in list(remaining_identifiers):
                user = identifier_map.get(identifier)
                if not user:
                    remaining_identifiers.remove(identifier)
                    continue

                payload = await _attempt_user_with_cached_slots(
                    job_id=job_id,
                    identifier=identifier,
                    user=user,
                    candidate_hours=candidate_hours,
                    slot_pool=slot_pool,
                    preset_option=preset_option,
                    date=target_date,
                    request_timeout=request_timeout,
                    attempt_counts=attempt_counts,
                )

                results_map[identifier] = payload
                result = payload["result"]
                if result.success:
                    job_info["success_count"] += 1
                    slot_hour = payload.get("slot_hour")
                    if reference_hour is None and isinstance(slot_hour, int):
                        reference_hour = slot_hour
                else:
                    if payload.get("slot_hour") is None:
                        print(
                            f"[schedule:{job_id}] 用户 {identifier} 未在缓存场次中找到匹配时段: {result.message}"
                        )

                remaining_identifiers.remove(identifier)

        for identifier in identifier_map:
            if identifier not in results_map:
                results_map[identifier] = {
                    "result": OrderResult(False, "未执行下单尝试"),
                    "start": "-",
                    "end": "-",
                    "attempt_type": "skipped",
                    "attempts": attempt_counts.get(identifier, 0),
                }

        job_info["last_results"] = [
            {
                "user": user_display_map.get(identifier, identifier),
                "success": payload["result"].success,
                "message": payload["result"].message,
                "attempts": payload.get("attempts", 1),
                "start": payload.get("start"),
                "end": payload.get("end"),
                "mode": payload.get("attempt_type"),
            }
            for identifier, payload in results_map.items()
        ]

        success_entries = {
            identifier: payload
            for identifier, payload in results_map.items()
            if payload["result"].success
        }
        failure_entries = {
            identifier: payload
            for identifier, payload in results_map.items()
            if not payload["result"].success
        }

        if failure_entries:
            job_info["last_error"] = "; ".join(
                f"{user_display_map.get(identifier, identifier)}: {payload['result'].message}"
                for identifier, payload in failure_entries.items()
            )
        else:
            job_info.pop("last_error", None)

        if success_entries:
            await _notify_schedule_successes(
                job_id=job_id,
                preset_option=preset_option,
                date=target_date,
                successes=success_entries,
                user_display_map=user_display_map,
            )
        await _notify_schedule_failures(
            job_id=job_id,
            preset_option=preset_option,
            date=target_date,
            failures=failure_entries,
            user_display_map=user_display_map,
        )

    except Exception as e:
        job_info["last_error"] = str(e)
    finally:
        job_info.pop("preloaded_slots", None)
        job_info.pop("preload_time", None)
        job_info.pop("preload_expires_at", None)
        job_info.pop("preload_success", None)
        job_info.pop("preload_error", None)
        await db_manager.save_scheduled_job(job_info)


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
    """获取当前登录状态信息，并验证用户实际是否在线。"""
    cookies_map, active_username = _auth_manager.load_all_cookies()
    if not cookies_map:
        return {"success": False, "message": "尚未保存任何登录凭据"}

    entries: List[Dict[str, Any]] = []
    
    # 创建 API 实例用于验证
    api = _create_api()
    
    for key, record in cookies_map.items():
        expires_at = record.get("expires_at")
        if isinstance(expires_at, datetime):
            expires_str = expires_at.isoformat()
        else:
            expires_str = str(expires_at)
        
        # 检查 cookie 是否过期
        is_expired = False
        if isinstance(expires_at, datetime):
            now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
            is_expired = expires_at < now
        
        # 尝试检查用户是否真正在线
        is_online = False
        if not is_expired and record.get("cookie"):
            try:
                # 临时切换用户来检查状态
                old_active = active_username
                _auth_manager.set_active_user(key)
                test_api = _create_api(active_user=key)
                is_online = test_api.check_auth_status()
                _auth_manager.set_active_user(old_active)
            except Exception:
                is_online = False
        
        entries.append(
            {
                "key": key,
                "username": record.get("username"),
                "nickname": record.get("nickname"),
                "cookie": record.get("cookie"),
                "expires_at": expires_str,
                "is_active": key == active_username,
                "is_expired": is_expired,
                "is_online": is_online,
            }
        )

    return {
        "success": True,
        "active_user": active_username,
        "users": entries,
    }


def get_user_orders(page_no: int = 1, page_size: int = 10) -> Dict[str, Any]:
    """获取所有用户的订单列表"""
    cookies_map, _ = _auth_manager.load_all_cookies()
    all_orders: List[Dict[str, Any]] = []
    grouped_orders: Dict[str, Dict[str, Any]] = {}
    summaries: List[Dict[str, Any]] = []

    for key, record in cookies_map.items():
        username = record.get("username") or key
        nickname = record.get("nickname") or username or key
        api: Optional[SportsAPI] = None
        try:
            api = _create_api(active_user=key)
            response = api.list_orders(page_no=1, page_size=100)
            user_orders = response.get("records", []) or []
        except Exception as exc:
            logger.warning("Failed to get orders for user %s: %s", key, exc)
            summaries.append(
                {
                    "userId": username,
                    "name": nickname,
                    "count": 0,
                    "error": str(exc),
                }
            )
            continue
        finally:
            if api:
                try:
                    api.close()
                except Exception:  # pragma: no cover - defensive close
                    pass

        cleaned_orders: List[Dict[str, Any]] = []
        for order in user_orders:
            order["userId"] = username
            order["name"] = nickname
            booking_date = (
                order.get("scDate")
                or order.get("scdate")
                or order.get("orderDate")
                or order.get("orderdate")
                or order.get("order_day")
            )
            if isinstance(booking_date, str):
                booking_date = booking_date.strip()
            if not booking_date:
                created = order.get("ordercreatement")
                if isinstance(created, str) and len(created) >= 10:
                    booking_date = created[:10]
            order["scDate"] = booking_date
            cleaned_orders.append(order)

        cleaned_orders.sort(key=lambda x: x.get("ordercreatement", ""), reverse=True)
        grouped_orders[username] = {
            "userId": username,
            "name": nickname,
            "orders": cleaned_orders,
        }
        summaries.append(
            {
                "userId": username,
                "name": nickname,
                "count": len(cleaned_orders),
            }
        )
        all_orders.extend(cleaned_orders)

    all_orders.sort(key=lambda x: x.get("ordercreatement", ""), reverse=True)

    return {
        "success": True,
        "orders": all_orders,
        "total": len(all_orders),
        "grouped": grouped_orders,
        "summary": summaries,
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
