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
                for date_str, slot in hit_slots:
                    self.console.print(
                        f"[green]{datetime.now():%H:%M:%S} found availability: {date_str} {slot.start}-{slot.end}[/green]"
                    )
                    if on_available:
                        on_available(date_str, slot)
                    if self.plan.auto_book:
                        ok, msg = self._attempt_booking(date_str, slot)
                        if ok:
                            self.console.print(f"[bold green]booking succeeded: {msg}[/bold green]")
                            should_stop.set()
                            break
                        self.console.print(f"[red]booking failed: {msg}[/red]")
            if should_stop.is_set():
                break
            time.sleep(self.plan.interval_seconds)

    def render_table(self, slots: List[Tuple[str, Slot]], *, include_full: bool = False) -> Table:
        table = Table(
            title=f"{self._venue_name or self.target.venue_keyword} - {self._field_type_name or self.target.field_type_keyword}",
            show_lines=False,
        )
        table.add_column("Venue")
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

        aggregates: Dict[Tuple[str, str, str, Optional[float]], int] = {}

        for date_str, slot in slots:
            remain = slot.remain if slot.remain is not None else 0
            if remain <= 0:
                continue
            time_label = _time_label(slot)
            price_val = slot.price
            key = (venue_label, date_str, time_label, price_val)
            aggregates[key] = aggregates.get(key, 0) + remain

        sorted_entries = sorted(
            aggregates.items(),
            key=lambda item: (
                item[0][1],
                _time_sort_key(item[0][2]),
                item[0][3] if item[0][3] is not None else float("inf"),
            ),
        )

        for (venue_cell, date_cell, time_cell, price_val), total_remain in sorted_entries:
            if total_remain <= 0:
                continue
            price_text = "-" if price_val is None else f"{price_val:.2f}"
            table.add_row(
                venue_cell,
                date_cell,
                time_cell,
                str(total_remain),
                price_text,
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
            return False, "missing orderId; cannot submit booking"
        try:
            resp = self.api.order_immediately(intent)
            message = json.dumps(resp, ensure_ascii=False)
            return True, message
        except Exception as exc:  # pylint: disable=broad-except
            return False, str(exc)
