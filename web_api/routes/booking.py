from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config as CFG
from sja_booking import service
from sja_booking.czq_debug import end as czq_debug_end, start as czq_debug_start
from sja_booking.models import BookingTarget, DateAvailability, PresetOption, Slot
from sja_booking.service import SlotAvailability, SlotListResult

router = APIRouter(prefix="/booking", tags=["booking"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_preset(option: PresetOption) -> Dict[str, Any]:
    return {
        "index": option.index,
        "venue_id": option.venue_id,
        "venue_name": option.venue_name,
        "field_type_id": option.field_type_id,
        "field_type_name": option.field_type_name,
        "field_type_code": option.field_type_code,
    }


def _serialize_slot(slot: Slot) -> Dict[str, Any]:
    return {
        "slot_id": slot.slot_id,
        "start": slot.start,
        "end": slot.end,
        "price": slot.price,
        "available": slot.available,
        "remain": slot.remain,
        "capacity": slot.capacity,
        "field_name": slot.field_name,
        "area_name": slot.area_name,
        "sub_site_id": slot.sub_site_id,
        "sign": slot.sign,
    }


def _serialize_slot_availability(entry: SlotAvailability) -> Dict[str, Any]:
    return {
        "date": entry.date,
        "slot": _serialize_slot(entry.slot),
    }


def _serialize_resolved_target(resolved: service.ResolvedTarget) -> Dict[str, Any]:
    return {
        "label": resolved.label,
        "venue_id": resolved.venue_id,
        "venue_name": resolved.venue_name,
        "field_type_id": resolved.field_type_id,
        "field_type_name": resolved.field_type_name,
        "preset": _serialize_preset(resolved.preset) if resolved.preset else None,
    }


def _serialize_date_availability(entry: DateAvailability) -> Dict[str, Any]:
    return {
        "date": entry.date,
        "token": entry.token,
        "open": entry.open,
        "is_all": entry.is_all,
        "selectable": entry.selectable,
    }


def _aggregate_slot_entries(entries: List[SlotAvailability]) -> List[Dict[str, Any]]:
    buckets: Dict[tuple, Dict[str, Any]] = {}
    for availability in entries:
        slot = availability.slot
        start = str(slot.start)
        end = str(slot.end)
        key = (availability.date, start, end)
        bucket = buckets.setdefault(
            key,
            {
                "date": availability.date,
                "start": start,
                "end": end,
                "site_count": 0,
                "available_count": 0,
                "total_remain": 0,
                "min_price": None,
                "max_price": None,
            },
        )

        bucket["site_count"] += 1
        if slot.available:
            bucket["available_count"] += 1

        remain_val = slot.remain
        if remain_val is None:
            bucket["total_remain"] = None
        elif bucket["total_remain"] is not None:
            try:
                bucket["total_remain"] += int(remain_val)
            except (TypeError, ValueError):
                bucket["total_remain"] = None

        price_val = slot.price
        if isinstance(price_val, (int, float)):
            if bucket["min_price"] is None or price_val < bucket["min_price"]:
                bucket["min_price"] = float(price_val)
            if bucket["max_price"] is None or price_val > bucket["max_price"]:
                bucket["max_price"] = float(price_val)

    aggregated = list(buckets.values())
    aggregated.sort(key=lambda item: (item["start"], item["end"]))
    return aggregated


def _aggregate_by_date(entries: List[SlotAvailability]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[SlotAvailability]] = defaultdict(list)
    for availability in entries:
        grouped[availability.date].append(availability)

    days: List[Dict[str, Any]] = []
    for date in sorted(grouped.keys()):
        days.append({"date": date, "entries": _aggregate_slot_entries(grouped[date])})
    return days


def _serialize_slot_result(result: SlotListResult) -> Dict[str, Any]:
    return {
        "resolved": _serialize_resolved_target(result.resolved),
        "slots": [_serialize_slot_availability(entry) for entry in result.slots],
        "aggregated_days": _aggregate_by_date(result.slots),
    }


async def _stream_slot_result(body: "SlotQuery", base_target: BookingTarget) -> StreamingResponse:
    result = await service.list_slots(
        preset=body.preset,
        venue_id=body.venue_id,
        field_type_id=body.field_type_id,
        date=body.date,
        start_hour=body.start_hour,
        show_full=body.show_full,
        base_target=base_target,
        all_dates=body.all_days,
    )
    serialized = _serialize_slot_result(result)
    aggregated_days = serialized.get("aggregated_days", [])

    async def iterator():
        yield json.dumps({"type": "resolved", "resolved": serialized["resolved"]}, ensure_ascii=False) + "\n"
        for day_payload in aggregated_days:
            yield json.dumps({"type": "day", **day_payload}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "complete"}, ensure_ascii=False) + "\n"

    return StreamingResponse(iterator(), media_type="application/jsonl")


def _build_target(overrides: Optional["TargetOverride"]) -> BookingTarget:
    base = dataclasses.replace(getattr(CFG, "TARGET", BookingTarget()))
    if not overrides:
        return base

    for field, value in overrides.dict(exclude_unset=True).items():
        setattr(base, field, value)
    return base


def _list_available_users() -> List[Dict[str, Any]]:
    status = service.login_status()
    cookies_map = status.get("users", []) or []
    active_user = status.get("active_user")
    configured_users = getattr(CFG.AUTH, "users", []) or []

    merged: Dict[str, Dict[str, Any]] = {}

    if isinstance(cookies_map, list):
        for index, entry in enumerate(cookies_map):
            username = entry.get("username")
            nickname = entry.get("nickname")
            key = username or nickname or entry.get("key") or f"status_{index}"
            merged[key] = {
                "key": key,
                "nickname": nickname,
                "username": username,
                "expires_at": entry.get("expires_at"),
                "is_active": entry.get("is_active") or (username and username == active_user),
            }

    for index, user in enumerate(configured_users):
        key = user.username or user.nickname or f"config_{index}"
        current = merged.get(key, {}).copy()
        nickname = user.nickname or current.get("nickname")
        username = user.username or current.get("username")
        is_active = current.get("is_active") or (username and username == active_user)
        expires_at = current.get("expires_at")

        merged[key] = {
            "key": key,
            "nickname": nickname,
            "username": username,
            "expires_at": expires_at,
            "is_active": is_active,
            "password_masked": user.password,
        }

    return list(merged.values())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TargetOverride(BaseModel):
    venue_id: Optional[str] = None
    venue_keyword: Optional[str] = None
    field_type_id: Optional[str] = None
    field_type_keyword: Optional[str] = None
    field_type_code: Optional[str] = None
    date_token: Optional[str] = None
    use_all_dates: Optional[bool] = None
    date_offset: Optional[int] = None
    fixed_dates: Optional[List[str]] = None
    start_hour: Optional[int] = None
    duration_hours: Optional[int] = None
    target_users: Optional[List[str]] = None
    exclude_users: Optional[List[str]] = None


class SlotQuery(BaseModel):
    preset: Optional[int] = None
    venue_id: Optional[str] = None
    field_type_id: Optional[str] = None
    date: Optional[str] = None
    start_hour: Optional[int] = None
    show_full: bool = False
    target: Optional[TargetOverride] = None
    all_days: bool = False
    incremental: bool = False


class ImmediateAvailabilityRequest(BaseModel):
    preset: Optional[int] = None
    venue_id: Optional[str] = None
    field_type_id: Optional[str] = None
    target: Optional[TargetOverride] = None
    date: Optional[str] = Field(None, description="指定日期（可选）")
    include_slots: bool = False


class ImmediateSlotsRequest(ImmediateAvailabilityRequest):
    date: str = Field(..., description="YYYY-MM-DD 日期字符串")
    show_full: bool = True
    include_slots: bool = False


class OrderRequest(BaseModel):
    preset: int
    date: str
    start_time: str = Field(..., description="HH or HH:MM")
    end_time: Optional[str] = Field(None, description="HH or HH:MM (optional)")
    user: Optional[str] = Field(None, description="Nickname or username to use for booking")
    target: Optional[TargetOverride] = None
    target_users: Optional[List[str]] = Field(
        None, description="Optional list of users to book for when未指定单个用户"
    )
    require_all_users_success: bool = Field(
        False, description="是否要求所有用户都预订成功（用于批量下单）"
    )


class MonitorRequest(BaseModel):
    monitor_id: str = Field(..., description="Unique monitor identifier")
    preset: Optional[int] = None
    venue_id: Optional[str] = None
    field_type_id: Optional[str] = None
    date: Optional[str] = None
    start_hour: Optional[int] = None
    interval_seconds: int = Field(240, ge=30)
    auto_book: bool = False
    long_running: bool = Field(False, description="成功预订后是否持续运行")
    require_all_users_success: bool = Field(False, description="是否要求所有用户都成功")
    max_time_gap_hours: Optional[int] = Field(1, ge=0, le=4, description="要求所有用户成功时允许的最大时间差（小时）")
    operating_start_hour: Optional[int] = Field(None, ge=0, le=24, description="每日运行开始时间（小时）")
    operating_end_hour: Optional[int] = Field(None, ge=0, le=24, description="每日运行结束时间（小时）")
    target: Optional[TargetOverride] = None
    preferred_hours: Optional[List[int]] = None
    preferred_days: Optional[List[int]] = None


class MonitorUsers(BaseModel):
    target_users: Optional[List[str]] = None
    exclude_users: Optional[List[str]] = None


class MonitorCreateRequest(MonitorRequest, MonitorUsers):
    pass


class MonitorDeleteResponse(BaseModel):
    success: bool
    message: str


class ScheduleRequest(BaseModel):
    job_id: str
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    second: int = Field(0, ge=0, le=59)
    preset: Optional[int] = None
    venue_id: Optional[str] = None
    field_type_id: Optional[str] = None
    date: Optional[str] = None
    start_hour: Optional[int] = None
    start_hours: Optional[List[int]] = None
    require_all_users_success: bool = Field(False, description="是否要求所有用户都成功")
    max_time_gap_hours: Optional[int] = Field(1, ge=0, le=4, description="要求所有用户成功时允许的最大时间差（小时）")
    target: Optional[TargetOverride] = None
    target_users: Optional[List[str]] = None
    exclude_users: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Routes - reference data
# ---------------------------------------------------------------------------


@router.get("/presets")
async def list_presets() -> Dict[str, Any]:
    presets = getattr(CFG, "PRESET_TARGETS", []) or []
    return {"presets": [_serialize_preset(option) for option in presets]}


@router.get("/users")
async def list_users() -> Dict[str, Any]:
    return {"users": _list_available_users()}


# ---------------------------------------------------------------------------
# Routes - data discovery
# ---------------------------------------------------------------------------


@router.get("/venues")
async def search_venues(
    keyword: str = Query(..., description="Venue keyword"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    venues = await service.list_venues(keyword=keyword, page=page, size=size)
    payload = []
    for venue in venues:
        payload.append(
            {
                "id": venue.id,
                "name": venue.name,
                "address": venue.address,
                "phone": venue.phone,
            }
        )
    return {"venues": payload}


@router.get("/venues/{venue_id}/field-types")
async def list_field_types(venue_id: str) -> Dict[str, Any]:
    field_types = await service.list_field_types(venue_id)
    payload = []
    for field in field_types:
        payload.append(
            {
                "id": field.id,
                "name": field.name,
                "category": field.category,
            }
        )
    return {"field_types": payload}


@router.post("/slots")
async def query_slots(body: SlotQuery) -> Dict[str, Any]:
    base_target = _build_target(body.target)
    if body.incremental:
        return await _stream_slot_result(body, base_target)

    result = await service.list_slots(
        preset=body.preset,
        venue_id=body.venue_id,
        field_type_id=body.field_type_id,
        date=body.date,
        start_hour=body.start_hour,
        show_full=body.show_full,
        base_target=base_target,
        all_dates=body.all_days,
    )
    return _serialize_slot_result(result)


@router.post("/immediate/availability")
async def immediate_availability(body: ImmediateAvailabilityRequest) -> Dict[str, Any]:
    base_target = _build_target(body.target)
    span = czq_debug_start(
        f"immediate_availability preset={body.preset} venue={body.venue_id} field={body.field_type_id} include_slots={body.include_slots}"
    )
    availability = await service.list_date_availability(
        preset=body.preset,
        venue_id=body.venue_id,
        field_type_id=body.field_type_id,
        base_target=base_target,
    )
    date_payload = [_serialize_date_availability(entry) for entry in availability.dates]
    valid_dates = {entry.date for entry in availability.dates}
    requested_date = body.date if (body.date and body.date in valid_dates) else None
    selected_date = requested_date or availability.default_date
    if selected_date and selected_date not in valid_dates:
        selected_date = availability.dates[0].date if availability.dates else None

    entries_payload: List[Dict[str, Any]] = []
    slots_payload: List[Dict[str, Any]] = []

    if body.include_slots and selected_date:
        detail_span = czq_debug_start(
            f"immediate_availability.detail preset={body.preset} date={selected_date}"
        )
        slots_result = await service.list_slots(
            preset=body.preset,
            venue_id=body.venue_id,
            field_type_id=body.field_type_id,
            date=selected_date,
            show_full=True,
            base_target=base_target,
        )
        serialized = _serialize_slot_result(slots_result)
        aggregated_days = serialized.get("aggregated_days", []) or []
        day_payload = next((day for day in aggregated_days if day.get("date") == selected_date), None)
        entries_payload = []
        if day_payload:
            entries_payload = [entry for entry in day_payload.get("entries", []) if (entry.get("available_count") or 0) > 0]
        slots_payload = [
            entry
            for entry in serialized["slots"]
            if entry.get("date") == selected_date and entry.get("slot", {}).get("available")
        ]
        if not entries_payload:
            fallback_entries: List[Dict[str, Any]] = []
            for slot_entry in slots_payload:
                slot_info = slot_entry.get("slot") or {}
                start = slot_info.get("start")
                end = slot_info.get("end")
                if not start or not end:
                    continue
                fallback_entries.append(
                    {
                        "date": selected_date,
                        "start": start,
                        "end": end,
                        "site_count": 1,
                        "available_count": 1,
                        "total_remain": slot_info.get("remain"),
                        "min_price": slot_info.get("price"),
                        "max_price": slot_info.get("price"),
                    }
                )
            entries_payload = fallback_entries
        entries_payload.sort(key=lambda item: (item.get("start") or "", item.get("end") or ""))
        czq_debug_end(
            "immediate_availability.detail",
            detail_span,
            extra=f"preset={body.preset} date={selected_date} entries={len(entries_payload)} slots={len(slots_payload)}",
        )

    response_payload: Dict[str, Any] = {
        "resolved": _serialize_resolved_target(availability.resolved),
        "dates": date_payload,
        "default_date": availability.default_date,
        "selected_date": selected_date,
    }
    if body.include_slots:
        response_payload["entries"] = entries_payload
        response_payload["slots"] = slots_payload
    czq_debug_end(
        "immediate_availability",
        span,
        extra=f"preset={body.preset} dates={len(date_payload)} selected={selected_date} include_slots={body.include_slots}",
    )
    return response_payload


@router.post("/immediate/slots")
async def immediate_slots(body: ImmediateSlotsRequest) -> Dict[str, Any]:
    base_target = _build_target(body.target)
    span = czq_debug_start(
        f"immediate_slots preset={body.preset} date={body.date} venue={body.venue_id} field={body.field_type_id}"
    )
    result = await service.list_slots(
        preset=body.preset,
        venue_id=body.venue_id,
        field_type_id=body.field_type_id,
        date=body.date,
        show_full=body.show_full,
        base_target=base_target,
    )
    serialized = _serialize_slot_result(result)
    aggregated_days = serialized.get("aggregated_days", []) or []
    day_payload = next((day for day in aggregated_days if day.get("date") == body.date), None)
    filtered_entries = []
    if day_payload:
        filtered_entries = [entry for entry in day_payload.get("entries", []) if (entry.get("available_count") or 0) > 0]
    filtered_slots = [
        entry
        for entry in serialized["slots"]
        if entry.get("date") == body.date and entry.get("slot", {}).get("available")
    ]
    if not filtered_entries:
        fallback_entries: List[Dict[str, Any]] = []
        for slot_entry in filtered_slots:
            slot_payload = slot_entry.get("slot") or {}
            start = slot_payload.get("start")
            end = slot_payload.get("end")
            if not start or not end:
                continue
            fallback_entries.append(
                {
                    "date": body.date,
                    "start": start,
                    "end": end,
                    "site_count": 1,
                    "available_count": 1,
                    "total_remain": slot_payload.get("remain"),
                    "min_price": slot_payload.get("price"),
                    "max_price": slot_payload.get("price"),
                }
            )
        filtered_entries = fallback_entries
    filtered_entries.sort(key=lambda item: (item.get("start") or "", item.get("end") or ""))
    czq_debug_end(
        "immediate_slots",
        span,
        extra=f"preset={body.preset} date={body.date} entries={len(filtered_entries)} slots={len(filtered_slots)}",
    )
    return {
        "resolved": serialized["resolved"],
        "date": body.date,
        "entries": filtered_entries,
        "slots": filtered_slots,
    }


# ---------------------------------------------------------------------------
# Routes - booking actions
# ---------------------------------------------------------------------------


@router.post("/order")
async def create_order(request: OrderRequest) -> Dict[str, Any]:
    base_target = _build_target(request.target)
    # 构建目标用户列表：优先单选用户，其次显式列表，默认尝试所有已配置且可用的账号
    def _normalize_users(users: Iterable[Optional[str]]) -> List[str]:
        normalized: List[str] = []
        seen: Set[str] = set()
        for entry in users:
            if not entry:
                continue
            key = str(entry).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized

    selected_users: List[str] = []
    if request.user:
        selected_users = _normalize_users([request.user])
    elif request.target_users:
        selected_users = _normalize_users(request.target_users)
    else:
        fallback_users = []
        for user in getattr(CFG.AUTH, "users", []) or []:
            if not (user.cookie or user.token):
                continue
            identifier = user.nickname or user.username
            fallback_users.append(identifier)
        selected_users = _normalize_users(fallback_users)

    if not selected_users:
        # 回退到当前激活用户
        selected_users = _normalize_users([request.user])
        if not selected_users:
            selected_users = []

    results: List[Dict[str, Any]] = []
    success_count = 0
    first_order_id: Optional[str] = None

    # 当没有显式指定用户且配置中存在多个可用用户时，尝试为所有用户下单
    require_all = bool(request.require_all_users_success)
    if not request.user and len(selected_users) > 1 and not request.require_all_users_success:
        require_all = True

    if not selected_users:
        raise HTTPException(status_code=400, detail="未找到可用于下单的用户，请先登录或配置账户")

    for identifier in selected_users:
        result = await service.order_once(
            preset=request.preset,
            date=request.date,
            start_time=request.start_time,
            end_time=request.end_time,
            base_target=base_target,
            user=identifier,
            notification_context="立即预订（批量）",
        )
        resolved_order_id = service.resolve_order_identifier(result) or result.order_id
        if result.success:
            success_count += 1
            if not first_order_id and resolved_order_id:
                first_order_id = resolved_order_id
        results.append(
            {
                "user": identifier,
                "success": result.success,
                "message": result.message,
                "order_id": resolved_order_id,
            }
        )

    if require_all:
        overall_success = success_count == len(selected_users)
    else:
        overall_success = success_count > 0

    summary_parts = [
        f"{entry['user']}: {'成功' if entry['success'] else '失败'}"
        for entry in results
    ]
    summary_text = "；".join(summary_parts)
    message = summary_text or "下单完成"

    return {
        "success": overall_success,
        "message": message,
        "order_id": first_order_id,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Routes - monitor management
# ---------------------------------------------------------------------------


@router.get("/monitors")
async def list_monitors() -> Dict[str, Any]:
    status = await service.monitor_status()
    return status


@router.post("/monitors")
async def create_monitor(request: MonitorCreateRequest) -> Dict[str, Any]:
    base_target = _build_target(request.target)
    response = await service.start_monitor(
        monitor_id=request.monitor_id,
        preset=request.preset,
        venue_id=request.venue_id,
        field_type_id=request.field_type_id,
        date=request.date,
        start_hour=request.start_hour,
        interval_seconds=request.interval_seconds,
        auto_book=request.auto_book,
        long_running=request.long_running,
        require_all_users_success=request.require_all_users_success,
        max_time_gap_hours=request.max_time_gap_hours,
        operating_start_hour=request.operating_start_hour,
        operating_end_hour=request.operating_end_hour,
        base_target=base_target,
        target_users=request.target_users,
        exclude_users=request.exclude_users,
        preferred_hours=request.preferred_hours,
        preferred_days=request.preferred_days,
    )
    if not response.get("success"):
        raise HTTPException(status_code=400, detail=response.get("message", "创建监控任务失败"))
    return response


@router.delete("/monitors/{monitor_id}", response_model=MonitorDeleteResponse)
async def delete_monitor(monitor_id: str) -> MonitorDeleteResponse:
    response = await service.stop_monitor(monitor_id)
    if not response.get("success"):
        raise HTTPException(status_code=404, detail=response.get("message", "监控任务不存在"))
    return MonitorDeleteResponse(success=True, message=response["message"])


@router.post("/monitors/{monitor_id}/pause")
async def pause_monitor(monitor_id: str) -> Dict[str, Any]:
    response = await service.pause_monitor(monitor_id)
    if not response.get("success"):
        raise HTTPException(status_code=400, detail=response.get("message", "暂停监控任务失败"))
    return response


@router.post("/monitors/{monitor_id}/resume")
async def resume_monitor(monitor_id: str) -> Dict[str, Any]:
    response = await service.resume_monitor(monitor_id)
    if not response.get("success"):
        raise HTTPException(status_code=400, detail=response.get("message", "恢复监控任务失败"))
    return response




# ---------------------------------------------------------------------------
# Routes - schedule management
# ---------------------------------------------------------------------------


@router.get("/schedules")
async def list_schedules() -> Dict[str, Any]:
    return await service.list_scheduled_jobs()


@router.post("/schedules")
async def create_schedule(request: ScheduleRequest) -> Dict[str, Any]:
    base_target = _build_target(request.target)
    clean_target_users = [user.strip() for user in (request.target_users or []) if user and user.strip()]
    clean_exclude_users = [user.strip() for user in (request.exclude_users or []) if user and user.strip()]
    dedup_targets = list(dict.fromkeys(clean_target_users)) if clean_target_users else []
    dedup_excludes = list(dict.fromkeys(clean_exclude_users)) if clean_exclude_users else []
    if dedup_targets:
        base_target.target_users = dedup_targets
    if dedup_excludes:
        base_target.exclude_users = dedup_excludes

    clean_start_hours: List[int] = []
    if request.start_hours:
        for entry in request.start_hours:
            try:
                clean_start_hours.append(int(entry))
            except (TypeError, ValueError):
                continue
    elif request.start_hour is not None:
        clean_start_hours = [int(request.start_hour)]
    if clean_start_hours:
        base_target.start_hour = clean_start_hours[0]

    response = await service.schedule_daily_job(
        job_id=request.job_id,
        hour=request.hour,
        minute=request.minute,
        second=request.second,
        preset=request.preset,
        venue_id=request.venue_id,
        field_type_id=request.field_type_id,
        date=request.date,
        start_hours=clean_start_hours or None,
        require_all_users_success=request.require_all_users_success,
        max_time_gap_hours=request.max_time_gap_hours,
        base_target=base_target,
        target_users=dedup_targets or None,
        exclude_users=dedup_excludes or None,
    )
    if not response.get("success"):
        raise HTTPException(status_code=400, detail=response.get("message", "创建定时任务失败"))
    return response


@router.delete("/schedules/{job_id}")
async def delete_schedule(job_id: str) -> Dict[str, Any]:
    response = await service.cancel_scheduled_job(job_id)
    if not response.get("success"):
        raise HTTPException(status_code=404, detail=response.get("message", "定时任务不存在"))
    return response
