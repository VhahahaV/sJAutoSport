from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .api import SportsAPI
from .models import (
    BookingTarget,
    MonitorPlan,
    PresetOption,
    Slot,
)
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


def _create_api() -> SportsAPI:
    return SportsAPI(
        CFG.BASE_URL,
        CFG.ENDPOINTS,
        CFG.AUTH,
        preset_targets=list(_iter_presets()),
    )


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
) -> OrderResult:
    api = _create_api()
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
) -> OrderResult:
    result = await asyncio.to_thread(
        _order_once_sync,
        preset=preset,
        date=date,
        start_time=start_time,
        end_time=end_time,
        base_target=base_target,
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
                message=result.message
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
    monitor_info = {
        "id": monitor_id,
        "preset": preset,
        "venue_id": venue_id,
        "field_type_id": field_type_id,
        "date": date,
        "start_hour": start_hour,
        "interval_seconds": interval_seconds,
        "auto_book": auto_book,
        "base_target": base_target,
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
    
    # 选择第一个可用时间段进行预订
    for slot in slots:
        if slot.get("available", False):
            try:
                # 执行预订
                result = await order_once(
                    preset=monitor_info["preset"],
                    date=slot.get("date", ""),
                    start_time=slot.get("start", ""),
                    end_time=slot.get("end", ""),
                    base_target=monitor_info["base_target"],
                )
                
                if result.success:
                    monitor_info["successful_bookings"] += 1
                    monitor_info["status"] = "completed"
                    break
                    
            except Exception as e:
                monitor_info["last_booking_error"] = str(e)


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
        # 执行预订
        result = await order_once(
            preset=job_info["preset"],
            date=job_info["date"] or "0",  # 默认今天
            start_time=job_info["start_hour"] or "18",
            base_target=job_info["base_target"],
        )
        
        if result.success:
            job_info["success_count"] += 1
            
    except Exception as e:
        job_info["last_error"] = str(e)


# =============================================================================
# 验证码协作 API
# =============================================================================

async def get_verification_code() -> Dict[str, Any]:
    """
    获取验证码（如果需要）
    
    Returns:
        验证码信息
    """
    try:
        # 这里可以集成真实的验证码获取逻辑
        # 例如：调用API获取验证码图片，OCR识别等
        
        # 模拟验证码获取
        import random
        code = str(random.randint(100000, 999999))
        
        # 保存验证码到数据库
        db_manager = get_db_manager()
        await db_manager.save_verification_code(code, "pending")
        
        return {
            "success": True, 
            "message": f"验证码已生成: {code}",
            "code": code,
            "expires_in": 300  # 5分钟过期
        }
    except Exception as e:
        return {"success": False, "message": f"获取验证码失败: {str(e)}"}


async def submit_verification_code(code: str) -> Dict[str, Any]:
    """
    提交验证码
    
    Args:
        code: 验证码
        
    Returns:
        提交结果
    """
    try:
        # 标记验证码为已使用
        db_manager = get_db_manager()
        success = await db_manager.mark_verification_code_used(code)
        
        if success:
            return {"success": True, "message": f"验证码 {code} 提交成功"}
        else:
            return {"success": False, "message": f"验证码 {code} 无效或已使用"}
    except Exception as e:
        return {"success": False, "message": f"提交验证码失败: {str(e)}"}


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
