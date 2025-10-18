from __future__ import annotations

import imp
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .models import (
    AuthConfig,
    BookingTarget,
    EndpointSet,
    FieldType,
    OrderIntent,
    Slot,
    Venue,
)


LIST_KEYS: Iterable[str] = (
    "data",
    "list",
    "rows",
    "records",
    "items",
    "content",
    "results",
    "result",
)


def _extract_first_list(payload: Any) -> Optional[List[Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        # prefer explicit list fields
        for key in LIST_KEYS:
            if key in payload:
                lst = _extract_first_list(payload[key])
                if lst is not None:
                    return lst
        # fallback: first list value
        for value in payload.values():
            if isinstance(value, list):
                return value
    return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.lower() in {"1", "true", "y", "yes", "available", "idle"}
    return False


class SportsAPI:
    def __init__(
        self,
        base_url: str,
        endpoints: EndpointSet,
        auth: AuthConfig,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoints = endpoints
        self.auth = auth
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        if auth.token:
            headers["Authorization"] = auth.token
        cookies: Dict[str, str] = {}
        if auth.cookie:
            for kv in auth.cookie.split(";"):
                if "=" in kv:
                    k, v = kv.strip().split("=", 1)
                    cookies[k] = v
        self._client = httpx.Client(base_url=self.base_url, headers=headers, cookies=cookies, timeout=timeout, http2=True)

    # -------------------- generic helpers --------------------

    def close(self) -> None:
        self._client.close()

    def _req(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        expected: Iterable[int] = (200,),
    ) -> httpx.Response:
        if path.startswith("http"):
            url = path
        else:
            url = path if path.startswith("/") else f"/{path}"
        resp = self._client.request(
            method,
            url,
            params=params,
            json=json_body,
            data=data,
            headers=headers,
        )
        if resp.status_code not in expected:
            detail = resp.text[:400]
            raise RuntimeError(f"{method} {url} -> {resp.status_code}: {detail}")
        return resp

    def check_login(self) -> Dict[str, Any]:
        resp = self._req("GET", self.endpoints.current_user)
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("profile interface returned non-dict payload")
        return data

    def ping(self) -> None:
        try:
            self._req("GET", self.endpoints.ping or "/")
        except RuntimeError:
            pass

    # -------------------- venue & slot operations --------------------

    def list_venues(self, keyword: Optional[str] = None, page: int = 1, size: int = 50, flag: int = 0) -> List[Venue]:
        payload = {"pageSize": size, "pageNum": page, "flag": flag}
        if keyword:
            payload["venueName"] = keyword
        resp = self._req("POST", self.endpoints.list_venues, data=payload)
        items = _extract_first_list(resp.json()) or []
        venues: List[Venue] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            vid = str(item.get("id") or item.get("venueId") or item.get("uuid") or item.get("bizId") or "")
            name = item.get("venueName") or item.get("name") or item.get("title") or ""
            if not vid or not name:
                continue
            venues.append(
                Venue(
                    id=vid,
                    name=name,
                    address=item.get("address") or item.get("addr"),
                    phone=item.get("phone") or item.get("tel"),
                    raw=item,
                )
            )
        return venues

    def get_venue_detail(self, venue_id: str) -> Dict[str, Any]:
        resp = self._req("POST", self.endpoints.venue_detail, data={"id": venue_id})
        data = resp.json()
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict):
                return inner
            return data
        raise RuntimeError("venue detail returned unexpected payload")

    def list_field_types(self, venue_detail: Dict[str, Any]) -> List[FieldType]:
        candidates = []
        for key in ("fieldTypeList", "fieldTypes", "bizFieldTypeList", "data", "motionTypes"):
            value = venue_detail.get(key)
            if isinstance(value, list):
                candidates = value
                break
        field_types: List[FieldType] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            fid = str(item.get("id") or item.get("fieldTypeId") or item.get("code") or item.get("motionId") or "")
            name = item.get("fieldTypeName") or item.get("name") or item.get("title") or item.get("motionName") or ""
            if fid and name:
                field_types.append(FieldType(id=fid, name=name, raw=item))
        return field_types

    def query_slots(self, venue_id: str, field_type_id: str, date_str: str, *, date_token: Optional[str] = None) -> List[Slot]:
        body: Dict[str, Any] = {
            "venueId": venue_id,
            "fieldType": field_type_id,
            "date": date_str,
        }
        if date_token:
            body["dateId"] = date_token
        resp = self._req(
            "POST",
            self.endpoints.field_situation,
            json_body=body,
            headers={"Content-Type": "application/json;charset=UTF-8"},
        )
        items = _extract_first_list(resp.json()) or []
        slots: List[Slot] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            slot_id = str(item.get("id") or item.get("detailId") or item.get("timeId") or item.get("siteId") or "")
            start = item.get("startTime") or item.get("beginTime") or item.get("startHour") or item.get("timeStart")
            end = item.get("endTime") or item.get("finishTime") or item.get("endHour") or item.get("timeEnd")
            remain = item.get("remain") or item.get("left") or item.get("availableNumber")
            capacity = item.get("capacity") or item.get("total") or item.get("maxNumber")
            available = item.get("isFull")
            if isinstance(available, str) and available.isdigit():
                available = available == "0"
            available_bool = _bool(item.get("available")) or _bool(item.get("status")) or _bool(remain) or not _bool(available)
            slots.append(
                Slot(
                    slot_id=slot_id or f"{venue_id}:{field_type_id}:{start}-{end}",
                    start=str(start),
                    end=str(end),
                    price=float(item.get("price") or item.get("amount") or 0) if item.get("price") or item.get("amount") else None,
                    available=available_bool,
                    remain=int(remain) if isinstance(remain, (int, float, str)) and str(remain).isdigit() else None,
                    capacity=int(capacity) if isinstance(capacity, (int, float, str)) and str(capacity).isdigit() else None,
                    raw=item,
                )
            )
        return slots

    def query_reserve_summary(self, venue_id: str, field_type_id: str, date_str: str) -> Dict[str, Any]:
        body = {"id": venue_id, "feildType": field_type_id, "date": date_str}
        resp = self._req(
            "POST",
            self.endpoints.field_reserve,
            json_body=body,
            headers={"Content-Type": "application/json;charset=UTF-8"},
        )
        return resp.json()

    def order_immediately(self, intent: OrderIntent) -> Dict[str, Any]:
        if not intent.order_id:
            raise ValueError("order_immediately requires intent.order_id")
        resp = self._req(
            "POST",
            self.endpoints.order_submit,
            data={"orderId": intent.order_id},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return resp.json()

    # -------------------- utilities --------------------

    def resolve_target_dates(self, target: BookingTarget, today: Optional[datetime] = None) -> List[str]:
        base = today or datetime.now()
        if target.fixed_dates:
            return target.fixed_dates
        goal = base + timedelta(days=target.date_offset)
        return [goal.strftime("%Y-%m-%d")]

    def pick_slot(self, slots: List[Slot], start_hour: int, duration_hours: int = 1) -> Optional[Slot]:
        for slot in slots:
            try:
                sh = int(str(slot.start).split(":")[0])
            except Exception:
                continue
            if sh == start_hour and slot.available:
                return slot
        return None

    def summary_table_rows(
        self,
        slots: List[Slot],
        *,
        include_full: bool = False,
    ) -> List[List[str]]:
        rows: List[List[str]] = []
        for slot in slots:
            if not include_full and not slot.available:
                continue
            status = "可预约" if slot.available else "已满"
            remain = "-" if slot.remain is None else str(slot.remain)
            capacity = "-" if slot.capacity is None else str(slot.capacity)
            price = "-" if slot.price is None else f"{slot.price:.2f}"
            rows.append([slot.start, slot.end, status, remain, capacity, price])
        return rows

    def find_venue(self, keyword: str, *, max_pages: int = 3, page_size: int = 50) -> Optional[Venue]:
        for page in range(1, max_pages + 1):
            venues = self.list_venues(keyword=keyword, page=page, size=page_size)
            for venue in venues:
                if keyword in venue.name:
                    return venue
        return None

    def get_field_type(self, venue_id: str, keyword: Optional[str] = None) -> Optional[FieldType]:
        detail = self.get_venue_detail(venue_id)
        field_types = self.list_field_types(detail)
        if keyword:
            for ft in field_types:
                if keyword in ft.name:
                    return ft
        return field_types[0] if field_types else None
