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
from .models import BookingTarget, MonitorPlan, PresetOption, Slot, UserAuth
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

    target_identifier = active_user or active_username
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
        if start_hour is not None:
            try:
                slot_hour = int(str(slot.start).split(":")[0])
            except Exception:  # pylint: disable=broad-except
                continue
            if slot_hour != start_hour:
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
) -> OrderResult:
    result = await asyncio.to_thread(
        _order_once_sync,
        preset=preset,
        date=date,
        start_time=start_time,
        end_time=end_time,
        base_target=base_target,
        user=user,
    )
    
    # 保存预订记录到数据库
    if result:
        try:
            db_manager = get_db_manager()
            await db_manager.save_booking_record(
                order_id=result.order_id or "unknown",
                preset=preset,
                venue_name=f"预设{preset}",
                field_type_name="未知",
                date=date,
                start_time=start_time,
                end_time=end_time or f"{int(start_time.split(':')[0]) + 1}:00",
                status="success" if result.success else "failed",
                message=result.message if not user else f"[{user}] {result.message}",
            )
        except Exception as e:
            print(f"保存预订记录失败: {e}")

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
) -> Dict[str, Any]:
    """
    启动监控任务
    
    Args:
        monitor_id: 监控任务唯一标识
        preset: 预设序号
        venue_id: 场馆ID
        field_type_id: 运动类型ID
        date: 目标日期
        start_hour: 开始小时
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
        "status": "starting",
        "start_time": datetime.now().isoformat(),
        "last_check": None,
        "found_slots": [],
        "booking_attempts": 0,
        "successful_bookings": 0,
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
    start_hour: Optional[int] = None,
    base_target: Optional[BookingTarget] = None,
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
        "start_hour": start_hour,
        "base_target": base_target,
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
        
        if result["success"] and result["slots"]:
            monitor_info["found_slots"] = result["slots"]
            
            # 如果启用自动预订
            if monitor_info["auto_book"]:
                await _auto_book_from_monitor(monitor_id, result["slots"])
        else:
            monitor_info["found_slots"] = []
            
    except Exception as e:
        monitor_info["last_error"] = str(e)


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
                    end_time=slot.get("end", ""),
                    base_target=base_target,
                    user=user_id,
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
        target_users = list(getattr(base_target, "target_users", []) or [])
        exclude_users = set(getattr(base_target, "exclude_users", []) or [])

        available_users = [u for u in getattr(CFG.AUTH, "users", []) or [] if u.cookie]
        if target_users:
            user_sequence = [u for u in available_users if u.nickname in target_users]
        else:
            user_sequence = [u for u in available_users if u.nickname not in exclude_users]

        if not user_sequence:
            user_sequence = available_users[:1]

        for user in user_sequence:
            user_id = user.username or user.nickname
            result = await order_once(
                preset=job_info["preset"],
                date=job_info["date"] or "0",
                start_time=job_info["start_hour"] or "18",
                base_target=base_target,
                user=user_id,
            )

            if result.success:
                job_info["success_count"] += 1
            else:
                job_info.setdefault("last_error", result.message)

            await asyncio.sleep(2.5)
            
    except Exception as e:
        job_info["last_error"] = str(e)


# =============================================================================
# 登录协同 API
# =============================================================================


def _resolve_credentials(username: Optional[str], password: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    # 如果直接提供了用户名和密码，直接使用
    if username and password:
        return username, password
    
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
    resolved_user, resolved_pass = _resolve_credentials(username, password)
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
        if session.attempts >= 3:
            await session.client.close()
            del _login_sessions[session_id]
            return {"success": False, "message": f"验证码错误次数过多: {exc}"}

        # 重试：重新获取验证码
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
                    "message": f"验证码错误，请重试 ({session.attempts}/3)",
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
