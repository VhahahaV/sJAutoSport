"""
自动抢票系统
每天中午12点准时开始抢七天后的场地
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .api import SportsAPI
from .database import get_db_manager
from .models import BookingTarget, MonitorPlan, PresetOption, Slot
from .monitor import SlotMonitor
from .order import OrderManager, OrderResult

try:
    import config as CFG
except ImportError:
    CFG = None


@dataclass
class PreparedSlot:
    """预处理后的时间段快照"""
    slot: Slot
    start: str
    end: str
    remain: Optional[int]
    fetched_at: datetime


class AutoBookingSystem:
    """自动抢票系统"""

    def __init__(self) -> None:
        self.api: Optional[SportsAPI] = None
        self.order_manager: Optional[OrderManager] = None
        self.db_manager = get_db_manager()
        self.is_running = False
        self.booking_targets: List[Dict[str, Any]] = []
        self.booking_results: List[Dict[str, Any]] = []
        self.settings: Dict[str, Any] = {}
        self._preset_map: Dict[int, PresetOption] = {}
        self._prepared_slots: Dict[Tuple[int, str], List[PreparedSlot]] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._warmup_lock = asyncio.Lock()
        self._schedule_hour = 12
        self._schedule_minute = 0
        self._schedule_second = 0

    async def initialize(self) -> None:
        """初始化系统"""
        if not CFG:
            raise RuntimeError("配置模块未找到")

        self.settings = dict(getattr(CFG, "AUTO_BOOKING_SETTINGS", {}))
        self._preset_map = {preset.index: preset for preset in getattr(CFG, "PRESET_TARGETS", [])}

        schedule_plan = getattr(CFG, "SCHEDULE_PLAN", None)
        if schedule_plan:
            self._schedule_hour = getattr(schedule_plan, "hour", 12)
            self._schedule_minute = getattr(schedule_plan, "minute", 0)
            self._schedule_second = getattr(schedule_plan, "second", 0)

        self.api = SportsAPI(
            CFG.BASE_URL,
            CFG.ENDPOINTS,
            CFG.AUTH,
            preset_targets=CFG.PRESET_TARGETS,
            post_throttle_seconds=self.settings.get("post_throttle_seconds", 0.0),
        )
        self.order_manager = OrderManager(
            self.api,
            CFG.ENCRYPTION_CONFIG,
            request_timeout=self.settings.get("order_request_timeout", 3.0),
        )

        await self._load_booking_targets()

    async def _load_booking_targets(self) -> None:
        """加载抢票目标配置"""
        targets = await self.db_manager.load_auto_booking_targets()

        if not targets:
            self.booking_targets = [
                {
                    "preset": 13,
                    "priority": 1,
                    "enabled": True,
                    "time_slots": [18, 19, 20, 21],
                    "max_attempts": 3,
                    "description": "南洋北苑健身房",
                },
                {
                    "preset": 5,
                    "priority": 2,
                    "enabled": True,
                    "time_slots": [18, 19, 20],
                    "max_attempts": 3,
                    "description": "气膜体育中心羽毛球",
                },
                {
                    "preset": 18,
                    "priority": 3,
                    "enabled": True,
                    "time_slots": [18, 19, 20],
                    "max_attempts": 3,
                    "description": "霍英东体育中心羽毛球",
                },
            ]
            await self.db_manager.save_auto_booking_targets(self.booking_targets)
        else:
            self.booking_targets = targets

    async def start_auto_booking_scheduler(self) -> Dict[str, Any]:
        """启动自动抢票调度器"""
        if self.is_running:
            return {"success": False, "message": "自动抢票系统已在运行"}

        if not self.api or not self.order_manager:
            await self.initialize()

        self.is_running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_worker())
        return {"success": True, "message": "自动抢票调度器已启动"}

    async def stop_auto_booking_scheduler(self) -> Dict[str, Any]:
        """停止自动抢票调度器"""
        self.is_running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        return {"success": True, "message": "自动抢票调度器已停止"}

    async def _scheduler_worker(self) -> None:
        """调度器工作线程"""
        debug_mode = os.getenv("SCHEDULE_DEBUG", "false").lower() == "true"
        try:
            if debug_mode:
                print("🧪 调试模式：立即执行抢票流程")
                target_date = self._compute_target_date(datetime.now())
                await self._warmup_targets(target_date, reason="debug")
                await self._execute_auto_booking(target_date)
                return

            while self.is_running:
                now = datetime.now()
                run_time = now.replace(
                    hour=self._schedule_hour,
                    minute=self._schedule_minute,
                    second=self._schedule_second,
                    microsecond=0,
                )
                if run_time <= now:
                    run_time += timedelta(days=1)

                warmup_offset = max(5, int(self.settings.get("warmup_seconds", 35)))
                warmup_time = run_time - timedelta(seconds=warmup_offset)
                if warmup_time < now:
                    warmup_time = now

                target_date = self._compute_target_date(run_time)
                await self._sleep_until(warmup_time)
                if not self.is_running:
                    break

                await self._warmup_targets(target_date)
                await self._sleep_until(run_time)
                if not self.is_running:
                    break

                await self._execute_auto_booking(target_date)
                self._prepared_slots.clear()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print("⏹️ 自动抢票调度器已取消")
            raise
        except Exception as exc:  # pylint: disable=broad-except
            print(f"❌ 调度器异常: {exc}")
        finally:
            self.is_running = False

    async def _sleep_until(self, target: datetime) -> None:
        """精确睡眠至指定时间点"""
        while self.is_running:
            now = datetime.now()
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 0.5 if remaining < 5 else 2.0))

    def _compute_target_date(self, base_time: datetime) -> str:
        offset_days = int(self.settings.get("target_offset_days", 7))
        target_datetime = base_time + timedelta(days=offset_days)
        return target_datetime.strftime("%Y-%m-%d")

    async def _warmup_targets(self, target_date: str, *, reason: str = "schedule") -> None:
        """执行抢票前的预热流程"""
        async with self._warmup_lock:
            enabled_targets = [t for t in self.booking_targets if t.get("enabled", True)]
            if not enabled_targets:
                print("⚠️ 没有启用的抢票目标，跳过预热")
                return

            print(f"🔥 开始预热（原因: {reason}），目标日期: {target_date}，共 {len(enabled_targets)} 个目标")
            tasks = []
            for target in enabled_targets:
                preset_index = target.get("preset")
                if not preset_index:
                    continue
                tasks.append(
                    asyncio.create_task(
                        self._get_available_slots(
                            preset_index,
                            target_date,
                            use_cache=False,
                            refresh=True,
                        )
                    )
                )

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for idx, result in enumerate(results):
                    target = enabled_targets[idx]
                    if isinstance(result, Exception):
                        print(f"⚠️ 预热失败: {target.get('description')} - {result}")
                    elif not result.get("success"):
                        print(f"⚠️ 预热未获取到可用时间段: {target.get('description')} - {result.get('message')}")
                    else:
                        slot_count = len(result.get("slots") or [])
                        print(f"✅ 预热成功: {target.get('description')} - 预加载 {slot_count} 个时间段")

    async def _execute_auto_booking(self, target_date: str) -> None:
        """执行自动抢票"""
        print(f"🚀 开始执行自动抢票，目标日期 {target_date}")
        enabled_targets = [t for t in self.booking_targets if t.get("enabled", True)]
        enabled_targets.sort(key=lambda x: x.get("priority", 999))
        self.booking_results = []

        for target in enabled_targets:
            description = target.get("description") or f"预设{target.get('preset')}"
            print(f"🏟️ 尝试抢票: {description}")
            try:
                result = await self._book_target(target, target_date)
                self.booking_results.append(result)
                if result["success"]:
                    print(f"✅ 抢票成功: {description} - {result['message']}")
                else:
                    print(f"❌ 抢票失败: {description} - {result['message']}")
            except Exception as exc:  # pylint: disable=broad-except
                print(f"❌ 抢票异常: {description} - {exc}")
                self.booking_results.append(
                    {
                        "target": target,
                        "success": False,
                        "message": f"异常: {exc}",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        await self._save_booking_results(target_date)
        print(f"🏁 自动抢票完成，共尝试 {len(self.booking_results)} 个目标")

    async def _book_target(self, target: Dict[str, Any], target_date: str) -> Dict[str, Any]:
        """针对单个目标执行抢票逻辑"""
        preset_index = target.get("preset")
        if preset_index is None:
            return {
                "target": target,
                "success": False,
                "message": "缺少预设编号",
                "timestamp": datetime.now().isoformat(),
            }

        preset = self._preset_map.get(preset_index)
        if not preset:
            return {
                "target": target,
                "success": False,
                "message": f"未找到预设 {preset_index}",
                "timestamp": datetime.now().isoformat(),
            }

        preferred_hours = target.get("time_slots") or [18, 19, 20, 21]
        max_attempts = max(1, int(target.get("max_attempts", 3)))
        refresh_rounds = max(1, int(self.settings.get("slot_refresh_rounds", 6)))
        refresh_interval = max(0.1, float(self.settings.get("slot_refresh_interval_seconds", 0.35)))
        retry_delay = max(0.2, float(self.settings.get("retry_delay_seconds", 0.8)))

        attempt_messages: List[str] = []
        for attempt in range(max_attempts):
            slots: List[PreparedSlot] = []
            for refresh_round in range(refresh_rounds):
                use_cache = attempt == 0 and refresh_round == 0
                slots_result = await self._get_available_slots(
                    preset_index,
                    target_date,
                    use_cache=use_cache,
                    refresh=not use_cache,
                )
                if not slots_result["success"]:
                    attempt_messages.append(slots_result["message"])
                    if refresh_round < refresh_rounds - 1:
                        await asyncio.sleep(refresh_interval)
                    continue

                slots = self._prioritize_slots(slots_result["slots"], preferred_hours)
                if not slots:
                    attempt_messages.append("没有符合条件的可用时间段")
                    if refresh_round < refresh_rounds - 1:
                        await asyncio.sleep(refresh_interval)
                    continue
                break

            if not slots:
                continue

            success_pair, attempt_details = await self._attempt_slots(preset, slots, target_date)
            if success_pair:
                prepared_slot, order_result = success_pair
                return {
                    "target": target,
                    "success": True,
                    "message": order_result.message,
                    "order_id": order_result.order_id,
                    "slot": self._serialize_slot(prepared_slot),
                    "attempt": attempt + 1,
                    "timestamp": datetime.now().isoformat(),
                }

            formatted_msg = self._format_attempt_failures(attempt_details)
            attempt_messages.append(formatted_msg)
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay)

        unique_messages = [msg for idx, msg in enumerate(attempt_messages) if msg and msg not in attempt_messages[:idx]]
        failure_message = "; ".join(unique_messages) if unique_messages else "所有时间段预订失败"
        return {
            "target": target,
            "success": False,
            "message": failure_message,
            "timestamp": datetime.now().isoformat(),
        }

    async def _attempt_slots(
        self,
        preset: PresetOption,
        slots: List[PreparedSlot],
        target_date: str,
    ) -> Tuple[Optional[Tuple[PreparedSlot, OrderResult]], List[Tuple[PreparedSlot, OrderResult]]]:
        """并发尝试预订多个时间段"""
        if not self.order_manager:
            raise RuntimeError("OrderManager 尚未初始化")

        concurrency = max(1, int(self.settings.get("max_parallel_orders", 6)))
        order_retries = max(1, int(self.settings.get("order_retry_attempts", 1)))
        refresh_before_attempt = bool(self.settings.get("order_refresh_before_attempt", True))
        selected_slots = slots[:concurrency]
        if not selected_slots:
            return None, []
        labels = ", ".join(f"{item.start}-{item.end}" for item in selected_slots)
        print(f"  ⚡ 并发尝试 {len(selected_slots)} 个时间段: {labels}")
        semaphore = asyncio.Semaphore(concurrency)
        success_event = asyncio.Event()
        attempt_results: List[Tuple[PreparedSlot, OrderResult]] = []

        async def worker(prepared_slot: PreparedSlot) -> Tuple[PreparedSlot, OrderResult]:
            async with semaphore:
                if success_event.is_set():
                    return prepared_slot, OrderResult(False, "已由其他任务抢占成功")
                try:
                    order_result: OrderResult = await asyncio.to_thread(
                        self.order_manager.place_order,
                        prepared_slot.slot,
                        preset,
                        target_date,
                        prepared_slot.start,
                        prepared_slot.end,
                        order_retries,
                        refresh_before_attempt=refresh_before_attempt,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    order_result = OrderResult(False, f"异常: {exc}")
                return prepared_slot, order_result

        tasks = [asyncio.create_task(worker(slot)) for slot in selected_slots]
        success_pair: Optional[Tuple[PreparedSlot, OrderResult]] = None

        try:
            for task in asyncio.as_completed(tasks):
                prepared_slot, result = await task
                attempt_results.append((prepared_slot, result))
                if result.success and not success_event.is_set():
                    print(f"  ✅ 成功占到时间段 {prepared_slot.start}-{prepared_slot.end}")
                    success_pair = (prepared_slot, result)
                    success_event.set()
                    break
                if not result.success:
                    print(f"  ❌ 时间段 {prepared_slot.start}-{prepared_slot.end} 失败: {result.message}")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        return success_pair, attempt_results

    async def _get_available_slots(
        self,
        preset_index: int,
        target_date: str,
        *,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """获取可用时间段，支持缓存"""
        cache_key = (preset_index, target_date)
        cache_ttl = float(self.settings.get("slot_cache_ttl_seconds", 25))
        now = datetime.now()
        if use_cache:
            cached = self._prepared_slots.get(cache_key)
            if cached:
                newest = max(slot.fetched_at for slot in cached)
                if (now - newest).total_seconds() <= cache_ttl:
                    return {"success": True, "slots": cached}

        preset = self._preset_map.get(preset_index)
        if not preset:
            return {"success": False, "message": f"未找到预设 {preset_index}"}

        try:
            slots = await asyncio.to_thread(self._collect_slots_sync, preset, target_date)
            if not slots:
                if refresh:
                    return {"success": False, "message": "尚无可用时间段"}
                return {"success": True, "slots": []}
            self._prepared_slots[cache_key] = slots
            return {"success": True, "slots": slots}
        except Exception as exc:  # pylint: disable=broad-except
            return {"success": False, "message": f"获取时间段异常: {exc}"}

    def _collect_slots_sync(self, preset: PresetOption, target_date: str) -> List[PreparedSlot]:
        """同步收集最新的时间段信息"""
        if not self.api:
            raise RuntimeError("SportsAPI 尚未初始化")

        target = BookingTarget(
            venue_id=preset.venue_id,
            field_type_id=preset.field_type_id,
            fixed_dates=[target_date],
        )
        monitor = SlotMonitor(self.api, target, MonitorPlan(enabled=False))
        rows = monitor.run_once(include_full=True)
        prepared: List[PreparedSlot] = []
        fetched_at = datetime.now()
        for date_str, slot in rows:
            if date_str != target_date:
                continue
            if not slot.sign:
                continue
            if not slot.available and (slot.remain is None or slot.remain <= 0):
                continue
            start, end = self._normalize_slot_times(slot)
            if not start or not end:
                continue
            prepared.append(
                PreparedSlot(
                    slot=slot,
                    start=start,
                    end=end,
                    remain=slot.remain,
                    fetched_at=fetched_at,
                )
            )
        return prepared

    def _prioritize_slots(self, slots: List[PreparedSlot], preferred_hours: List[int]) -> List[PreparedSlot]:
        """根据优先时间段对 slots 排序"""
        preferred_map = {hour: idx for idx, hour in enumerate(preferred_hours)}

        def sort_key(item: PreparedSlot) -> Tuple[int, int]:
            hour = self._parse_hour(item.start)
            priority = preferred_map.get(hour, len(preferred_map))
            remain = item.remain if isinstance(item.remain, int) else 0
            return (priority, -remain)

        filtered = [
            slot for slot in slots if slot.slot.available or (slot.remain is not None and slot.remain > 0)
        ]
        return sorted(filtered, key=sort_key)

    def _format_attempt_failures(self, details: List[Tuple[PreparedSlot, OrderResult]]) -> str:
        """格式化失败原因"""
        messages: List[str] = []
        for prepared_slot, result in details:
            if result.success:
                continue
            label = f"{prepared_slot.start}-{prepared_slot.end}"
            messages.append(f"{label}: {result.message}")
        unique = []
        for msg in messages:
            if msg not in unique:
                unique.append(msg)
        return "; ".join(unique) if unique else "所有时间段预订失败"

    def _serialize_slot(self, prepared_slot: PreparedSlot) -> Dict[str, Any]:
        return {
            "start": prepared_slot.start,
            "end": prepared_slot.end,
            "remain": prepared_slot.remain,
            "price": prepared_slot.slot.price,
            "field": prepared_slot.slot.field_name,
        }

    async def _save_booking_results(self, target_date: str) -> None:
        """保存抢票结果"""
        try:
            payload = {
                "target_date": target_date,
                "execution_time": datetime.now().isoformat(),
                "total_targets": len(self.booking_results),
                "successful_bookings": len([r for r in self.booking_results if r["success"]]),
                "results": self.booking_results,
            }
            await self.db_manager.save_auto_booking_result(payload)
            print("💾 抢票结果已保存到数据库")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"❌ 保存抢票结果失败: {exc}")

    async def get_booking_status(self) -> Dict[str, Any]:
        """获取抢票状态"""
        return {
            "is_running": self.is_running,
            "targets_count": len(self.booking_targets),
            "enabled_targets": len([t for t in self.booking_targets if t.get("enabled", True)]),
            "last_results": self.booking_results[-5:] if self.booking_results else [],
        }

    async def update_booking_targets(self, targets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """更新抢票目标配置"""
        self.booking_targets = targets
        await self.db_manager.save_auto_booking_targets(targets)
        return {"success": True, "message": "抢票目标配置已更新"}

    @staticmethod
    def _parse_hour(value: str) -> int:
        try:
            if ":" in value:
                hour_str = value.split(":", 1)[0]
            else:
                hour_str = value
            hour = int(hour_str)
            if 0 <= hour <= 23:
                return hour
        except (TypeError, ValueError):
            pass
        return 99

    @staticmethod
    def _normalize_slot_times(slot: Slot) -> Tuple[str, str]:
        raw = slot.raw if isinstance(slot.raw, dict) else {}
        decoded_val = raw.get("decoded_sign")
        decoded = decoded_val if isinstance(decoded_val, dict) else {}
        price_entry_val = raw.get("price_entry")
        price_entry = price_entry_val if isinstance(price_entry_val, dict) else {}

        start = AutoBookingSystem._coerce_time_str(
            slot.start,
            decoded.get("start"),
            decoded.get("beginTime"),
            price_entry.get("startTime"),
            price_entry.get("beginTime"),
        )
        end = AutoBookingSystem._coerce_time_str(
            slot.end,
            decoded.get("end"),
            decoded.get("finishTime"),
            price_entry.get("endTime"),
            price_entry.get("finishTime"),
        )
        return start, end

    @staticmethod
    def _coerce_time_str(*values: Optional[str]) -> str:
        for value in values:
            if not value:
                continue
            text = str(value)
            if ":" in text:
                parts = text.split(":")
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                except (TypeError, ValueError):
                    continue
                return f"{hour:02d}:{minute:02d}"
            if text.isdigit():
                hour = int(text)
                if 0 <= hour <= 23:
                    return f"{hour:02d}:00"
        return ""


# 全局自动抢票系统实例
_auto_booking_system: Optional[AutoBookingSystem] = None


def get_auto_booking_system() -> AutoBookingSystem:
    """获取自动抢票系统实例"""
    global _auto_booking_system
    if _auto_booking_system is None:
        _auto_booking_system = AutoBookingSystem()
    return _auto_booking_system
