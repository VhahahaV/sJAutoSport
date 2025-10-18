from __future__ import annotations

import json
import base64
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

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

SLOT_START_KEYS = {
    "startTime",
    "beginTime",
    "startHour",
    "timeStart",
    "timeBegin",
    "start",
    "begin",
}

SLOT_END_KEYS = {
    "endTime",
    "finishTime",
    "endHour",
    "timeEnd",
    "timeFinish",
    "end",
}


def _maybe_parse_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text and text[0] in "{[" and text[-1] in "]}" and len(text) >= 2:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return value
            return _maybe_parse_json(parsed)
    if isinstance(value, dict):
        return {k: _maybe_parse_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_maybe_parse_json(v) for v in value]
    return value


def _extract_first_list(payload: Any) -> Optional[List[Any]]:
    if isinstance(payload, str):
        coerced = _maybe_parse_json(payload)
        if coerced is not payload:
            return _extract_first_list(coerced)
        return None
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


def _collect_slot_dicts(payload: Any) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            coerced = _maybe_parse_json(node)
            if coerced is not node:
                _walk(coerced)
            return
        if isinstance(node, dict):
            node_keys = set(node.keys())
            if node_keys & SLOT_START_KEYS and node_keys & SLOT_END_KEYS:
                collected.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for child in node:
                _walk(child)

    _walk(payload)
    return collected


def _decode_sign(sign: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"raw": sign}
    if not sign:
        return result
    padded = sign + "=" * (-len(sign) % 4)
    try:
        data = base64.b64decode(padded)
    except Exception as exc:  # pylint: disable=broad-except
        result["error"] = str(exc)
        return result
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", "ignore")
    result["text"] = text
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            obj = json.loads(stripped)
            result["json"] = obj
        except json.JSONDecodeError:
            pass
    if "json" in result:
        payload_json = result["json"]
        if isinstance(payload_json, dict):
            for key in ("startTime", "start", "beginTime"):
                if key in payload_json:
                    result["start"] = str(payload_json[key])
                    break
            for key in ("endTime", "end", "finishTime"):
                if key in payload_json:
                    result["end"] = str(payload_json[key])
                    break
            for key in ("date", "reserveDate"):
                if key in payload_json:
                    result["date"] = str(payload_json[key])
                    break
    if "start" not in result or "end" not in result:
        times = re.findall(r"(?:[01]\\d|2[0-3]):[0-5]\\d", result.get("text") or "")
        if times:
            result.setdefault("start", times[0])
            if len(times) > 1:
                result.setdefault("end", times[1])
    return result


class SportsAPI:
    def __init__(
        self,
        base_url: str,
        endpoints: EndpointSet,
        auth: AuthConfig,
        *,
        timeout: float = 10.0,
        preset_targets: Optional[List] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoints = endpoints
        self.auth = auth
        self.preset_targets = preset_targets or []
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.base_url}/pc/",
            "Origin": self.base_url,
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
        self.client = self._client  # 提供公共访问接口

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
            category = item.get("category") or item.get("motionCode") or item.get("bizType")
            if fid and name:
                field_types.append(FieldType(id=fid, name=name, category=category, raw=item))
        return field_types

    def list_available_dates(self, venue_id: str, field_type_id: str) -> List[Tuple[str, str]]:
        path = self.endpoints.slot_summary
        if not path or path == self.endpoints.field_situation:
            return []
        body = {"venueId": venue_id, "fieldType": field_type_id}
        try:
            resp = self._req(
                "POST",
                path,
                json_body=body,
                headers={"Content-Type": "application/json;charset=UTF-8"},
            )
        except Exception:
            return []
        payload = _maybe_parse_json(resp.json())
        dates: List[Tuple[str, str]] = []
        if isinstance(payload, dict):
            for key in ("data", "result", "list", "rows"):
                value = payload.get(key)
                if isinstance(value, list):
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        date_str = str(item.get("date") or item.get("dateStr") or "")
                        token = str(item.get("dateId") or item.get("id") or item.get("token") or "")
                        if date_str:
                            dates.append((date_str, token))
                    break
        return dates

    def query_slots(self, venue_id: str, field_type_id: str, date_str: str, *, date_token: Optional[str] = None, original_field_type: Optional[FieldType] = None) -> List[Slot]:
        body: Dict[str, Any] = {
            "venueId": venue_id,
            "fieldType": field_type_id,
            "date": date_str,
        }
        if date_token:
            body["dateId"] = date_token
        elif original_field_type and original_field_type.raw:
            extra_token = original_field_type.raw.get("dateId") or original_field_type.raw.get("dateToken")
            if extra_token:
                body["dateId"] = extra_token
        if original_field_type and original_field_type.category:
            body.setdefault("bizMotionType", original_field_type.category)
        if original_field_type and original_field_type.raw:
            for key in ("bizMotionType", "motionType", "motionTypeId", "motionId", "bizMotionId"):
                if key in body:
                    break
                value = original_field_type.raw.get(key)
                if value:
                    body[key] = value
        if date_token:
            body["dateId"] = date_token
        resp = self._req(
            "POST",
            self.endpoints.field_situation,
            json_body=body,
            headers={"Content-Type": "application/json;charset=UTF-8"},
        )
        payload = _maybe_parse_json(resp.json())
        if isinstance(payload, dict):
            code_value = payload.get("code")
            if code_value not in (None, 0, "0"):
                raise RuntimeError(f"query_slots failed: {code_value} {payload.get('msg') or payload.get('message')}")

        items = _extract_first_list(payload) or []

        fields_payload: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            data_node = payload.get("data")
            if isinstance(data_node, list):
                fields_payload = [obj for obj in data_node if isinstance(obj, dict)]

        slots: List[Slot] = []
        if fields_payload:
            sample_entry: Optional[Dict[str, Any]] = None
            for field_node in fields_payload:
                price_list = field_node.get("priceList")
                if isinstance(price_list, list) and price_list:
                    sample_candidate = price_list[0]
                    if isinstance(sample_candidate, dict):
                        sample_entry = sample_candidate
                        break
            for field_node in fields_payload:
                field_id = str(field_node.get("fieldId") or field_node.get("id") or "")
                field_name = field_node.get("fieldName") or field_node.get("name")
                area_name = field_node.get("fieldNameEn") or field_node.get("fieldAreaName") or field_node.get("areaName")
                price_list = field_node.get("priceList") or []
                if not isinstance(price_list, list):
                    continue
                for idx, entry in enumerate(price_list):
                    if not isinstance(entry, dict):
                        continue
                    sign_info = _decode_sign(entry.get("sign"))
                    start = (
                        entry.get("startTime")
                        or entry.get("beginTime")
                        or entry.get("startHour")
                        or sign_info.get("start")
                    )
                    end = (
                        entry.get("endTime")
                        or entry.get("finishTime")
                        or entry.get("endHour")
                        or sign_info.get("end")
                    )
                    slot_id = entry.get("sign") or entry.get("id") or f"{field_id}:{idx}"
                    price_raw = entry.get("price") or entry.get("amount")
                    try:
                        price_val = float(price_raw) if price_raw not in (None, "") else None
                    except (TypeError, ValueError):
                        price_val = None
                    count = entry.get("count") or entry.get("remain")
                    remain_val: Optional[int] = None
                    if isinstance(count, (int, float)):
                        remain_val = int(count)
                    elif isinstance(count, str) and count.strip().lstrip("-").isdigit():
                        remain_val = int(count)
                    status = str(entry.get("status") or "").strip()
                    available_bool = False
                    if remain_val is not None:
                        available_bool = remain_val > 0
                    if status:
                        available_bool = available_bool or status in {"0", "1"}
                    slots.append(
                        Slot(
                            slot_id=str(slot_id),
                            start=str(start) if start not in (None, "") else f"slot-{idx}",
                            end=str(end) if end not in (None, "") else "-",
                            price=price_val,
                            available=available_bool,
                            remain=remain_val,
                            capacity=None,
                            field_name=str(field_name) if field_name is not None else None,
                            area_name=str(area_name) if area_name is not None else None,
                            sub_site_id=field_id,  # fieldId 对应 subSiteId
                            sign=entry.get("sign"),  # 提取 sign 字段
                            raw={
                                "field_id": field_id,
                                "field_name": field_name,
                                "price_entry": entry,
                                "decoded_sign": sign_info,
                                "status": status,
                            },
                        )
                    )
        else:
            sample_item: Optional[Dict[str, Any]] = None
            for candidate in items:
                if isinstance(candidate, dict):
                    sample_item = candidate
                    break
            if sample_item:
                sample_keys = list(sample_item.keys())[:15]

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
                field_name = item.get("fieldName") or item.get("siteName") or item.get("name") or item.get("courtName")
                area_name = item.get("areaName") or item.get("fieldAreaName") or item.get("venueFieldName") or item.get("zoneName")
                slots.append(
                    Slot(
                        slot_id=slot_id or f"{venue_id}:{field_type_id}:{start}-{end}",
                        start=str(start),
                        end=str(end),
                        price=float(item.get("price") or item.get("amount") or 0) if item.get("price") or item.get("amount") else None,
                        available=available_bool,
                        remain=int(remain) if isinstance(remain, (int, float, str)) and str(remain).isdigit() else None,
                        capacity=int(capacity) if isinstance(capacity, (int, float, str)) and str(capacity).isdigit() else None,
                        field_name=str(field_name) if field_name is not None else None,
                        area_name=str(area_name) if area_name is not None else None,
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
        if getattr(target, "use_all_dates", False):
            return []
        if target.date_offset is None:
            return []
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
            status = "available" if slot.available else "full"
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





