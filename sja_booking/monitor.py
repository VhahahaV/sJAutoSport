from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


from .api import SportsAPI
from .models import BookingTarget, FieldType, MonitorPlan, Slot


class SlotMonitor:
    def __init__(
        self,
        api: SportsAPI,
        target: BookingTarget,
        plan: MonitorPlan,
        *,
        console: Optional[Any] = None,
    ) -> None:
        self.api = api
        self.target = target
        self.plan = plan
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
            except Exception as exc:
                raise RuntimeError(f"查询 {date_str} 的场次失败: {exc}") from exc
            for slot in slots:
                if not include_full and not slot.available:
                    continue
                results.append((date_str, slot))
        return results
