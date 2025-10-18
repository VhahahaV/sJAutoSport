from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any, Dict, List, Optional


@dataclass
class AuthConfig:
    cookie: Optional[str] = None
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class EndpointSet:
    current_user: str = "/system/user/currentUser"
    list_venues: str = "/manage/venue/listOrderCount"
    venue_detail: str = "/manage/venue/queryVenueById"
    field_situation: str = "/manage/fieldDetail/queryFieldSituation"
    field_reserve: str = "/manage/fieldDetail/queryFieldReserveSituationIsFull"
    order_submit: str = "/venue/personal/orderImmediatelyPC"
    order_confirm: str = "/venue/personal/ConfirmOrder"  # 新增下单确认端点
    appointment_overview: Optional[str] = "/appointment/disabled/getAppintmentAndSysUserbyUser"
    slot_summary: Optional[str] = "/manage/fieldDetail/queryFieldReserveSituationIsFull"
    ping: str = "/"


@dataclass
class SlotFilter:
    venue_keyword: Optional[str] = None
    venue_id: Optional[str] = None
    sport_keyword: Optional[str] = None
    sport_id: Optional[str] = None
    dates: List[str] = field(default_factory=list)
    start_time: Optional[time] = None
    end_time: Optional[time] = None


@dataclass
class BookingTarget:
    venue_id: Optional[str] = None
    venue_keyword: Optional[str] = None
    field_type_id: Optional[str] = None
    field_type_keyword: Optional[str] = None
    field_type_code: Optional[str] = None
    date_token: Optional[str] = None
    use_all_dates: bool = False
    date_offset: Optional[int] = 7
    fixed_dates: List[str] = field(default_factory=list)
    start_hour: int = 18
    duration_hours: int = 1


@dataclass
class PresetOption:
    index: int
    venue_id: str
    venue_name: str
    field_type_id: str
    field_type_name: str
    field_type_code: Optional[str] = None


@dataclass
class MonitorPlan:
    enabled: bool = False
    interval_seconds: int = 30
    auto_book: bool = False
    notify_stdout: bool = True


@dataclass
class Venue:
    id: str
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FieldType:
    id: str
    name: str
    category: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Slot:
    slot_id: str
    start: str
    end: str
    price: Optional[float] = None
    available: bool = False
    remain: Optional[int] = None
    capacity: Optional[int] = None
    field_name: Optional[str] = None
    area_name: Optional[str] = None
    sub_site_id: Optional[str] = None  # 对应PAYLOAD中的subSiteId
    sign: Optional[str] = None  # 对应PAYLOAD中的sign字段
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderIntent:
    venue_id: str
    field_type_id: str
    slot_id: str
    date: str
    order_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
