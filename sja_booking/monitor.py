from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from .api import SportsAPI
from .models import BookingTarget, MonitorPlan, OrderIntent, Slot


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

    # -------------------- public API --------------------

    def resolve_context(self) -> None:
        if not self._venue_id:
            if not self.target.venue_keyword:
                raise ValueError("缺少 venue_id 或 venue_keyword")
            venue = self.api.find_venue(self.target.venue_keyword)
            if not venue:
                raise RuntimeError(f"未找到场馆：{self.target.venue_keyword}")
            self._venue_id = venue.id
            self._venue_name = venue.name
        else:
            venue = self.api.get_venue_detail(self._venue_id)
            self._venue_name = venue.get("venueName") or venue.get("name")

        if not self._field_type_id:
            match: Optional[FieldType] = None
            if self.target.field_type_keyword:
                match = self.api.get_field_type(self._venue_id, self.target.field_type_keyword)
            if not match:
                detail = self.api.get_venue_detail(self._venue_id)
                types = self.api.list_field_types(detail)
                match = types[0] if types else None
            if not match:
                raise RuntimeError("未能获取项目列表，请检查 field_type 配置或接口返回格式")
            self._field_type_id = match.id
            self._field_type_name = match.name
        else:
            detail = self.api.get_venue_detail(self._venue_id)
            field_types = self.api.list_field_types(detail)
            for ft in field_types:
                if ft.id == self._field_type_id:
                    self._field_type_name = ft.name
                    break

    def run_once(self, *, include_full: bool = False) -> List[Tuple[str, Slot]]:
        self.resolve_context()
        dates = self.api.resolve_target_dates(self.target)
        results: List[Tuple[str, Slot]] = []
        for date_str in dates:
            slots = self.api.query_slots(self._venue_id, self._field_type_id, date_str)
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
            f"[cyan]启动监测：场馆 {self._venue_name or self.target.venue_keyword}，项目 {self._field_type_name or self.target.field_type_keyword}[/cyan]"
        )
        while not should_stop.is_set():
            try:
                hit_slots = self.run_once()
            except Exception as exc:
                self.console.print(f"[red]监测失败：{exc}[/red]")
                time.sleep(self.plan.interval_seconds)
                continue
            if not hit_slots:
                self.console.print(
                    f"[yellow]{datetime.now():%H:%M:%S} 没有可预约时段[/yellow]"
                )
            else:
                for date_str, slot in hit_slots:
                    self.console.print(
                        f"[green]{datetime.now():%H:%M:%S} 找到空位：{date_str} {slot.start}-{slot.end}[/green]"
                    )
                    if on_available:
                        on_available(date_str, slot)
                    if self.plan.auto_book:
                        ok, msg = self._attempt_booking(date_str, slot)
                        if ok:
                            self.console.print(f"[bold green]下单成功：{msg}[/bold green]")
                            should_stop.set()
                            break
                        self.console.print(f"[red]下单失败：{msg}[/red]")
            if should_stop.is_set():
                break
            time.sleep(self.plan.interval_seconds)

    def render_table(self, slots: List[Tuple[str, Slot]], *, include_full: bool = False) -> Table:
        table = Table(title=f"{self._venue_name or self.target.venue_keyword} - {self._field_type_name or self.target.field_type_keyword}", show_lines=False)
        table.add_column("日期")
        table.add_column("开始")
        table.add_column("结束")
        table.add_column("状态")
        table.add_column("剩余")
        table.add_column("容量")
        table.add_column("价格")
        for date_str, slot in slots:
            if not include_full and not slot.available:
                continue
            table.add_row(
                date_str,
                slot.start,
                slot.end,
                "可预约" if slot.available else "已满",
                "-" if slot.remain is None else str(slot.remain),
                "-" if slot.capacity is None else str(slot.capacity),
                "-" if slot.price is None else f"{slot.price:.2f}",
            )
        return table

    def attempt_booking(self, date_str: str, slot: Slot) -> Tuple[bool, str]:
        return self._attempt_booking(date_str, slot)

    # -------------------- internal helpers --------------------

    def _attempt_booking(self, date_str: str, slot: Slot) -> Tuple[bool, str]:
        order_id = slot.raw.get("orderId") or slot.raw.get("id") or slot.slot_id
        intent = OrderIntent(
            venue_id=self._venue_id,
            field_type_id=self._field_type_id,
            slot_id=slot.slot_id,
            date=date_str,
            order_id=str(order_id) if order_id else None,
            payload=slot.raw,
        )
        if not intent.order_id:
            return False, "缺少 orderId，无法自动下单"
        try:
            resp = self.api.order_immediately(intent)
            message = json.dumps(resp, ensure_ascii=False)
            return True, message
        except Exception as exc:  # pylint: disable=broad-except
            return False, str(exc)
