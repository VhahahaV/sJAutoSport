from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config as CFG
from sja_booking import service
from sja_booking.models import BookingTarget, PresetOption, Slot
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
    resolved = result.resolved
    return {
        "resolved": {
            "label": resolved.label,
            "venue_id": resolved.venue_id,
            "venue_name": resolved.venue_name,
            "field_type_id": resolved.field_type_id,
            "field_type_name": resolved.field_type_name,
            "preset": _serialize_preset(resolved.preset) if resolved.preset else None,
        },
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


class OrderRequest(BaseModel):
    preset: int
    date: str
    start_time: str = Field(..., description="HH or HH:MM")
    end_time: Optional[str] = Field(None, description="HH or HH:MM (optional)")
    user: Optional[str] = Field(None, description="Nickname or username to use for booking")
    target: Optional[TargetOverride] = None


class MonitorRequest(BaseModel):
    monitor_id: str = Field(..., description="Unique monitor identifier")
    preset: Optional[int] = None
    venue_id: Optional[str] = None
    field_type_id: Optional[str] = None
    date: Optional[str] = None
    start_hour: Optional[int] = None
    interval_seconds: int = Field(240, ge=30)
    auto_book: bool = False
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


# ---------------------------------------------------------------------------
# Routes - booking actions
# ---------------------------------------------------------------------------


@router.post("/order")
async def create_order(request: OrderRequest) -> Dict[str, Any]:
    base_target = _build_target(request.target)
    result = await service.order_once(
        preset=request.preset,
        date=request.date,
        start_time=request.start_time,
        end_time=request.end_time,
        base_target=base_target,
        user=request.user,
    )
    return {
        "success": result.success,
        "message": result.message,
        "order_id": result.order_id,
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
