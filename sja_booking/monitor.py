from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from .api import SportsAPI
from .models import BookingTarget, FieldType, MonitorPlan, OrderIntent, Slot
from .multi_user import MultiUserManager, UserBookingResult


class SlotMonitor:
    def __init__(
        self,
        api: SportsAPI,
        target: BookingTarget,
        plan: MonitorPlan,
        *,
        console: Optional[Console] = None,
    ) -> None:
        self.api = api
        self.target = target
        self.plan = plan
        self.console = console or Console()
        self._venue_id: Optional[str] = target.venue_id
        self._field_type_id: Optional[str] = target.field_type_id
        self._venue_name: Optional[str] = None
        self._field_type_name: Optional[str] = None
        self._field_type_info: Optional[FieldType] = None
        self._summary_fingerprints: Dict[str, Tuple] = {}
        
        # 请求频率控制
        self._last_request_time = 0
        self._min_request_interval = 1.0  # 最小请求间隔1秒
        self._rate_limit_delay = 0  # 动态调整的延迟时间

    # -------------------- public API --------------------

    def resolve_context(self) -> None:
        if not self._venue_id:
            if not self.target.venue_keyword:
                raise ValueError("missing venue_id or venue_keyword")
            venue = self.api.find_venue(self.target.venue_keyword)
            if not venue:
                raise RuntimeError(f"venue not found: {self.target.venue_keyword}")
            self._venue_id = venue.id
            self._venue_name = venue.name
        else:
            venue_detail = self.api.get_venue_detail(self._venue_id)
            self._venue_name = (
                venue_detail.get("venueName")
                or venue_detail.get("name")
                or venue_detail.get("title")
            )
        if not self._field_type_id:
            match: Optional[FieldType] = None
            if self.target.field_type_keyword:
                match = self.api.get_field_type(self._venue_id, self.target.field_type_keyword)
            if not match:
                detail = self.api.get_venue_detail(self._venue_id)
                types = self.api.list_field_types(detail)
                match = types[0] if types else None
            if not match:
                raise RuntimeError("failed to resolve field type; please adjust configuration")
            self._field_type_id = match.id
            self._field_type_name = match.name
            self.target.field_type_code = self.target.field_type_code or match.category
            self._field_type_info = match
        else:
            detail = self.api.get_venue_detail(self._venue_id)
            field_types = self.api.list_field_types(detail)
            for ft in field_types:
                if ft.id == self._field_type_id:
                    self._field_type_name = ft.name
                    self.target.field_type_code = self.target.field_type_code or ft.category
                    self._field_type_info = ft
                    break

    def run_once(self, *, include_full: bool = False) -> List[Tuple[str, Slot]]:
        self.resolve_context()
        dates = self.api.resolve_target_dates(self.target)
        date_tokens: Dict[str, Optional[str]] = {}
        if self.target.date_token:
            for d in dates:
                date_tokens[d] = self.target.date_token
        else:
            tokens = self.api.list_available_dates(self._venue_id, self._field_type_id)
            for date_str_value, token in tokens:
                date_tokens[date_str_value] = token

        normalized_dates: List[str] = []
        if dates:
            for d in dates:
                if not date_tokens or d in date_tokens:
                    normalized_dates.append(d)
        elif date_tokens:
            normalized_dates = sorted(date_tokens.keys())
        if not normalized_dates and date_tokens:
            # fall back to the first available date if requested ones are unavailable
            normalized_dates = sorted(date_tokens.keys())[:1]

        results: List[Tuple[str, Slot]] = []
        for date_str in normalized_dates:
            token = date_tokens.get(date_str)
            prev_fingerprint = self._summary_fingerprints.get(date_str)
            summary_slots: List[Dict[str, Any]] = []
            summary_fingerprint: Optional[Tuple[Tuple[str, str, str, str, Optional[int], Optional[int], bool, str], ...]] = None
            summary_available = False

            supports_summary = bool(getattr(self.api.endpoints, "field_reserve", None))
            if not include_full and supports_summary:
                try:
                    summary_payload = self.api.query_reserve_summary(self._venue_id, self._field_type_id, date_str)
                    summary_slots = self.api.normalize_slot_summary(summary_payload)
                except Exception:  # pylint: disable=broad-except
                    summary_slots = []
                else:
                    for slot_info in summary_slots:
                        remain_value = slot_info.get("remain")
                        if slot_info.get("available") and (remain_value is None or (isinstance(remain_value, int) and remain_value > 0)):
                            summary_available = True
                            break
                    summary_fingerprint = tuple(
                        sorted(
                            (
                                str(slot_info.get("field") or ""),
                                str(slot_info.get("area") or ""),
                                str(slot_info.get("start") or ""),
                                str(slot_info.get("end") or ""),
                                slot_info.get("remain"),
                                slot_info.get("capacity"),
                                bool(slot_info.get("available")),
                                str(slot_info.get("status") or ""),
                            )
                            for slot_info in summary_slots
                        )
                    )

            should_fetch_details = include_full or not summary_slots
            if not include_full and summary_slots:
                if summary_available:
                    should_fetch_details = True
                elif prev_fingerprint is not None and summary_fingerprint is not None and summary_fingerprint != prev_fingerprint:
                    should_fetch_details = True
                else:
                    should_fetch_details = False

            if summary_fingerprint is not None:
                self._summary_fingerprints[date_str] = summary_fingerprint

            if not should_fetch_details:
                continue

            if self._field_type_info:
                field_type = self._field_type_info
            else:
                fallback_raw: Dict[str, Any] = {}
                if self.target.field_type_code:
                    fallback_raw["code"] = self.target.field_type_code
                field_type = FieldType(
                    id=self._field_type_id,
                    name=self._field_type_name or "",
                    category=self.target.field_type_code,
                    raw=fallback_raw,
                )
            try:
                slots = self.api.query_slots(
                    self._venue_id,
                    self._field_type_id,
                    date_str,
                    date_token=token,
                    original_field_type=field_type,
                )
            except Exception:  # pylint: disable=broad-except
                continue
            for slot in slots:
                if not include_full and not slot.available:
                    continue
                results.append((date_str, slot))
        return results

    def monitor_loop(
        self,
        *,
        stop_event: Optional[threading.Event] = None,
        on_available: Optional[Callable[[str, Slot], None]] = None,
    ) -> None:
        should_stop = stop_event or threading.Event()
        self.console.print(
            f"[cyan]Monitoring venue {self._venue_name or self.target.venue_keyword} / field {self._field_type_name or self.target.field_type_keyword}[/cyan]"
        )
        while not should_stop.is_set():
            try:
                hit_slots = self.run_once()
            except Exception as exc:
                self.console.print(f"[red]monitor failed: {exc}[/red]")
                time.sleep(self.plan.interval_seconds)
                continue
            if not hit_slots:
                self.console.print(
                    f"[yellow]{datetime.now():%H:%M:%S} no available slots[/yellow]"
                )
            else:
                # 如果有时间偏好，优先选择符合条件的时间段
                preferred_slots: List[Tuple[str, Slot]] = []

                # 复制一份优先时间段设置，避免就地修改配置
                preferred_hours = list(getattr(self.plan, "preferred_hours", None) or [])

                # 当未显式设置优先时间段时，沿用 target.start_hour 作为默认偏好
                if not preferred_hours and self.target.start_hour is not None:
                    preferred_hours.append(self.target.start_hour)

                preferred_hours_set = set()
                for item in preferred_hours:
                    try:
                        preferred_hours_set.add(int(item))
                    except Exception:  # pylint: disable=broad-except
                        continue

                if preferred_hours_set:
                    for date_str, slot in hit_slots:
                        slot_hour = self._extract_slot_hour(slot)
                        if slot_hour is None:
                            continue

                        if slot_hour in preferred_hours_set:
                            preferred_slots.append((date_str, slot))

                    # 仅在存在优先时间段时尝试预订这些时间
                    slots_to_process = preferred_slots
                else:
                    slots_to_process = hit_slots
                
                # 先显示所有可用时间段
                for date_str, slot in hit_slots:
                    # 格式化时间显示
                    time_display = self._format_slot_time(slot)
                    preference_indicator = ""
                    
                    # 检查是否为优先时间段
                    try:
                        slot_hour = self._extract_slot_hour(slot)
                        if preferred_hours_set and slot_hour in preferred_hours_set:
                            preference_indicator = " [PREFERRED]"
                    except Exception:
                        pass
                    
                    self.console.print(
                        f"[green]{datetime.now():%H:%M:%S} found availability: {date_str} {time_display}{preference_indicator}[/green]"
                    )
                    if on_available:
                        on_available(date_str, slot)
                
                # 然后尝试自动下单
                if self.plan.auto_book:
                    self.console.print(f"[yellow]{datetime.now():%H:%M:%S} 开始尝试自动下单...[/yellow]")
                    if preferred_hours_set:
                        if not slots_to_process:
                            self.console.print("[yellow]未找到匹配的优先时间段，本轮不进行预订[/yellow]")
                            time.sleep(self.plan.interval_seconds)
                            continue
                        self.console.print(
                            f"[yellow]将尝试 {len(slots_to_process)} 个优先时间段: {sorted(preferred_hours_set)}[/yellow]"
                        )
                    else:
                        self.console.print(f"[yellow]将按优先级尝试 {len(slots_to_process)} 个时间段[/yellow]")

                    multi_user_manager = MultiUserManager(self.api.auth, self.console)
                    target_users = multi_user_manager.get_users_for_booking(self.target)
                    if not target_users:
                        self.console.print("[yellow]没有可用的用户进行自动预订[/yellow]")
                        time.sleep(2.0)
                        continue

                    booking_results: List[UserBookingResult] = []
                    any_success = False

                    for user_index, user in enumerate(target_users, 1):
                        self.console.print(
                            f"[blue]=== 为用户 {user.nickname} 自动下单 ({user_index}/{len(target_users)}) ===[/blue]"
                        )
                        try:
                            self.api.switch_to_user(user)
                        except Exception as switch_exc:  # pylint: disable=broad-except
                            message = f"无法切换用户: {switch_exc}"
                            self.console.print(f"[red]{message}[/red]")
                            booking_results.append(
                                UserBookingResult(
                                    nickname=user.nickname,
                                    success=False,
                                    message="预订失败",
                                    error=message,
                                )
                            )
                            continue

                        success_for_user = False
                        last_message = "未能完成预订"

                        for slot_index, (date_str, slot) in enumerate(slots_to_process, 1):
                            self.console.print(
                                f"[yellow]--- 尝试第 {slot_index}/{len(slots_to_process)} 个时间段 ---[/yellow]"
                            )
                            ok, msg = self._attempt_booking(date_str, slot)
                            last_message = msg
                            if ok:
                                success_for_user = True
                                any_success = True
                                break

                            self.console.print(f"[yellow]等待中以避免频率限制...[/yellow]")
                            wait_seconds = min(8.0, 2.5 + slot_index * 1.5)
                            time.sleep(wait_seconds)

                        booking_results.append(
                            UserBookingResult(
                                nickname=user.nickname,
                                success=success_for_user,
                                message=last_message,
                                order_id=None,
                                error=None if success_for_user else last_message,
                            )
                        )

                        if not success_for_user:
                            self.console.print(f"[yellow]用户 {user.nickname} 本轮未成功: {last_message}[/yellow]")

                        if user_index < len(target_users):
                            gap = 3.0
                            self.console.print(f"[blue]等待 {gap:.1f} 秒后尝试下一位用户[/blue]")
                            time.sleep(gap)

                    if booking_results:
                        multi_user_manager.print_user_status(booking_results)

                    if any_success:
                        should_stop.set()
                    else:
                        self.console.print("[yellow]本轮未成功预订，等待下一周期继续监控[/yellow]")
            if should_stop.is_set():
                break
            time.sleep(self.plan.interval_seconds)

    def render_table(self, slots: List[Tuple[str, Slot]], *, include_full: bool = False) -> Table:
        table = Table(
            title=f"{self._venue_name or self.target.venue_keyword} - {self._field_type_name or self.target.field_type_keyword}",
            show_lines=False,
        )
        table.add_column("Venue")
        table.add_column("Field")
        table.add_column("Date")
        table.add_column("Time")
        table.add_column("Remaining")
        table.add_column("Price")

        venue_label = self._venue_name or self.target.venue_keyword or "-"

        def _format_label(label: str) -> Optional[str]:
            if not label:
                return None
            text = label.strip()
            if text.startswith("slot-"):
                suffix = text[5:]
                if suffix.isdigit():
                    hour = (7 + int(suffix)) % 24
                    return f"{hour:02d}:00"
            if text.isdigit() and len(text) == 4:
                hour = int(text[:2]) % 24
                minute = int(text[2:]) % 60
                return f"{hour:02d}:{minute:02d}"
            parts = text.split(":")
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                hour = int(parts[0]) % 24
                minute = int(parts[1]) % 60
                return f"{hour:02d}:{minute:02d}"
            return None

        def _time_label(slot: Slot) -> str:
            candidates: List[str] = []
            if slot.start not in (None, ""):
                candidates.append(str(slot.start))
            decoded = slot.raw.get("decoded_sign")
            if isinstance(decoded, dict):
                decoded_start = decoded.get("start") or decoded.get("startTime")
                if decoded_start:
                    candidates.append(str(decoded_start))
            for candidate in candidates:
                formatted = _format_label(candidate)
                if formatted:
                    return formatted
            return candidates[0] if candidates else "-"

        def _time_sort_key(label: str) -> Tuple[int, str]:
            try:
                parts = label.split(":")
                if len(parts) == 2 and all(part.isdigit() for part in parts):
                    hour = int(parts[0]) % 24
                    minute = int(parts[1]) % 60
                    return (hour * 60 + minute, label)
            except Exception:
                pass
            if label.startswith("slot-") and label[5:].isdigit():
                hour = (7 + int(label[5:])) % 24
                return (hour * 60, label)
            return (10_000, label)

        aggregates: Dict[Tuple[str, str, str, str, Optional[float]], int] = {}

        for date_str, slot in slots:
            remain = slot.remain if slot.remain is not None else 0
            if remain <= 0:
                continue
            time_label = _time_label(slot)
            price_val = slot.price
            field_label = slot.field_name or slot.area_name or slot.sub_site_id or "-"
            key = (venue_label, field_label, date_str, time_label, price_val)
            aggregates[key] = aggregates.get(key, 0) + remain

        sorted_entries = sorted(
            aggregates.items(),
            key=lambda item: (
                item[0][2],
                item[0][1],
                _time_sort_key(item[0][3]),
                item[0][4] if item[0][4] is not None else float("inf"),
            ),
        )

        for (venue_cell, field_cell, date_cell, time_cell, price_val), total_remain in sorted_entries:
            if total_remain <= 0:
                continue
            price_text = "-" if price_val is None else f"{price_val:.2f}"
            table.add_row(
                venue_cell,
                field_cell,
                date_cell,
                time_cell,
                str(total_remain),
                price_text,
            )
        return table

    def attempt_booking(self, date_str: str, slot: Slot) -> Tuple[bool, str]:
        return self._attempt_booking(date_str, slot)

    def _rate_limit_control(self) -> None:
        """请求频率控制"""
        import time
        current_time = time.time()
        time_since_last_request = current_time - self._last_request_time
        
        # 计算需要的等待时间
        required_wait = self._min_request_interval + self._rate_limit_delay - time_since_last_request
        
        if required_wait > 0:
            self.console.print(f"[blue]请求频率控制: 等待 {required_wait:.1f} 秒...[/blue]")
            time.sleep(required_wait)
        
        self._last_request_time = time.time()
    
    def _handle_rate_limit_error(self, error_msg: str) -> None:
        """处理频率限制错误"""
        if "请求过于频繁" in error_msg or "频率" in error_msg or "500" in error_msg:
            # 增加延迟时间
            self._rate_limit_delay = min(self._rate_limit_delay + 2.0, 10.0)  # 最大延迟10秒
            self.console.print(f"[yellow]检测到频率限制，增加延迟到 {self._rate_limit_delay:.1f} 秒[/yellow]")
        else:
            # 逐渐减少延迟时间
            self._rate_limit_delay = max(self._rate_limit_delay - 0.5, 0)

    def _format_slot_time(self, slot: Slot) -> str:
        """格式化时间段显示"""
        try:
            # 尝试解析时间
            start_time = self._parse_time_string(slot.start)
            
            # 如果没有结束时间，根据开始时间计算结束时间
            if slot.end and str(slot.end).strip():
                end_time = self._parse_time_string(slot.end)
            else:
                hour = self._extract_hour_from_text(start_time)
                if hour is not None:
                    next_hour = (hour + 1) % 24
                    end_time = f"{next_hour:02d}:00"
                else:
                    end_time = None
            
            if start_time and end_time:
                return f"{start_time}-{end_time}"
            elif start_time:
                return f"{start_time}-{end_time or '??:??'}"
            else:
                # 如果解析失败，显示原始值
                return f"{slot.start}-{slot.end or '??:??'}"
        except Exception as e:
            return f"{slot.start}-{slot.end or '??:??'}"
    
    def _parse_time_string(self, time_str: str) -> Optional[str]:
        """解析时间字符串，支持多种格式"""
        if not time_str:
            return None
            
        time_str = str(time_str).strip()
        
        # 如果已经包含冒号，尝试提取 HH:MM 格式
        if ":" in time_str and len(time_str) >= 4:
            core = time_str.split("-", 1)[0].strip()
            core = core.split(" ", 1)[-1]
            parts = core.split(":")
            if len(parts) >= 2:
                try:
                    hour = int(parts[0]) % 24
                    minute_raw = ''.join(ch for ch in parts[1] if ch.isdigit())
                    minute = int(minute_raw[:2]) if minute_raw else 0
                    return f"{hour:02d}:{minute:02d}"
                except Exception:  # pylint: disable=broad-except
                    return core[:5]
            return core
        
        # 如果是slot-X格式，尝试转换为时间
        if time_str.startswith("slot-"):
            try:
                slot_num = int(time_str.split("-")[1])
                # slot-0对应7:00，slot-1对应8:00，以此类推
                hour = 7 + slot_num
                return f"{hour:02d}:00"
            except (ValueError, IndexError):
                pass
        
        # 如果是纯数字，假设是小时
        try:
            hour = int(time_str)
            if 0 <= hour <= 23:
                return f"{hour:02d}:00"
        except ValueError:
            pass

        # 如果都无法解析，返回原始值
        return time_str

    def _extract_hour_from_text(self, time_text: Optional[str]) -> Optional[int]:
        if not time_text:
            return None
        try:
            return int(str(time_text).split(":")[0])
        except Exception:  # pylint: disable=broad-except
            return None

    def _extract_slot_hour(self, slot: Slot) -> Optional[int]:
        start_time = self._parse_time_string(slot.start)
        return self._extract_hour_from_text(start_time)

    # -------------------- internal helpers --------------------

    def _attempt_booking(self, date_str: str, slot: Slot) -> Tuple[bool, str]:
        """使用与order命令完全相同的下单逻辑，带请求频率控制"""
        try:
            from .order import OrderManager
            from .models import PresetOption
            import config as CFG
            
            # 请求频率控制
            self._rate_limit_control()
            
            self.console.print(f"[blue]正在处理时间段: {self._format_slot_time(slot)}[/blue]")
            
            # 创建OrderManager实例
            order_manager = OrderManager(self.api, CFG.ENCRYPTION_CONFIG)
            
            # 构建预设配置 - 使用与order命令相同的逻辑
            preset = PresetOption(
                index=0,  # 临时索引
                venue_id=self._venue_id,
                venue_name=self._venue_name or "未知场馆",
                field_type_id=self._field_type_id,
                field_type_name=self._field_type_name or "未知项目"
            )
            
            # 重新查询slot以确保数据最新 - 与order命令保持一致
            try:
                from .models import FieldType
                temp_field_type = FieldType(
                    id=self._field_type_id,
                    name=self._field_type_name or "未知项目",
                    category=None
                )
                
                self.console.print(f"[blue]正在获取日期token...[/blue]")
                # 获取日期token
                date_tokens = self.api.list_available_dates(self._venue_id, self._field_type_id)
                date_token = None
                for date_str_value, token in date_tokens:
                    if date_str_value == date_str:
                        date_token = token
                        break
                
                if not date_token:
                    return False, f"无法获取日期 {date_str} 的token"
                
                self.console.print(f"[blue]正在重新查询时间段数据...[/blue]")
                # 重新查询slots
                fresh_slots = self.api.query_slots(
                    venue_id=self._venue_id,
                    field_type_id=self._field_type_id,
                    date_str=date_str,
                    date_token=date_token,
                    original_field_type=temp_field_type
                )
                
                self.console.print(f"[blue]找到 {len(fresh_slots)} 个时间段，正在匹配目标时间段...[/blue]")
                
                # 显示所有可用时间段用于调试
                available_slots = [s for s in fresh_slots if s.available]
                self.console.print(f"[blue]其中 {len(available_slots)} 个时间段可用:[/blue]")
                for i, s in enumerate(available_slots[:5]):  # 只显示前5个
                    time_display = self._format_slot_time(s)
                    # 截断过长的slot_id用于显示
                    short_slot_id = s.slot_id[:20] + "..." if len(s.slot_id) > 20 else s.slot_id
                    self.console.print(f"[blue]  {i+1}. {time_display} (slot_id: {short_slot_id})[/blue]")
                if len(available_slots) > 5:
                    self.console.print(f"[blue]  ... 还有 {len(available_slots) - 5} 个时间段[/blue]")
                
                # 找到对应的slot - 使用时间匹配而不是slot_id
                target_slot = None
                original_time_display = self._format_slot_time(slot)
                self.console.print(f"[blue]正在匹配时间段: {original_time_display} (原始slot_id: {slot.slot_id})[/blue]")
                
                # 首先尝试通过slot_id匹配
                for fresh_slot in fresh_slots:
                    if fresh_slot.slot_id == slot.slot_id and fresh_slot.available:
                        target_slot = fresh_slot
                        self.console.print(f"[green]✅ 通过slot_id匹配成功: {fresh_slot.slot_id}[/green]")
                        break
                
                # 如果slot_id匹配失败，尝试通过时间匹配
                if not target_slot:
                    self.console.print(f"[yellow]slot_id匹配失败，尝试时间匹配...[/yellow]")
                    for fresh_slot in fresh_slots:
                        if fresh_slot.available:
                            fresh_time_display = self._format_slot_time(fresh_slot)
                            self.console.print(f"[blue]比较: {original_time_display} vs {fresh_time_display}[/blue]")
                            if fresh_time_display == original_time_display:
                                target_slot = fresh_slot
                                self.console.print(f"[green]✅ 通过时间匹配成功: {fresh_slot.slot_id}[/green]")
                                break
                
                if not target_slot:
                    return False, f"时间段 {original_time_display} 已不可用"
                
                # 使用与order命令相同的时间计算逻辑
                slot_index = None
                for i, s in enumerate(fresh_slots):
                    if s.slot_id == target_slot.slot_id:
                        slot_index = i
                        break
                
                if slot_index is None:
                    return False, f"无法确定时间段索引 (目标slot_id: {target_slot.slot_id})"
                
                # 根据slot索引计算实际时间 - 与order命令完全一致
                actual_start_hour = (7 + slot_index) % 24  # slot-0对应07:00
                actual_start = f"{actual_start_hour:02d}:00"
                actual_end_hour = (actual_start_hour + 1) % 24
                actual_end = f"{actual_end_hour:02d}:00"
                
                self.console.print(f"[blue]计算时间段: {actual_start}-{actual_end} (slot索引: {slot_index})[/blue]")
                
                # 使用完整的下单流程
                self.console.print(f"[blue]开始下单流程...[/blue]")
                result = order_manager.place_order(
                    slot=target_slot,
                    preset=preset,
                    date=date_str,
                    actual_start=actual_start,
                    actual_end=actual_end,
                    max_retries=1  # 监控模式下只尝试一次
                )
                
                if result.success:
                    message = f"下单成功，订单ID: {result.order_id}" if result.order_id else result.message
                    self.console.print(f"[green]✅ {message}[/green]")
                    return True, message
                else:
                    self.console.print(f"[red]❌ 下单失败: {result.message}[/red]")
                    self._handle_rate_limit_error(result.message)
                    return False, result.message
                    
            except Exception as e:
                error_msg = f"重新查询时间段失败: {e}"
                self.console.print(f"[red]❌ {error_msg}[/red]")
                self._handle_rate_limit_error(error_msg)
                return False, error_msg
                
        except Exception as exc:  # pylint: disable=broad-except
            error_msg = f"下单异常: {str(exc)}"
            self.console.print(f"[red]❌ {error_msg}[/red]")
            self._handle_rate_limit_error(error_msg)
            return False, error_msg
