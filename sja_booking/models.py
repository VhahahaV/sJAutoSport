from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any, Dict, List, Optional, Union


@dataclass
class UserAuth:
    """单个用户的认证信息"""
    nickname: str
    cookie: Optional[str] = None
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

@dataclass
class AuthConfig:
    """当前单个账号的认证配置。"""
    user: Optional[UserAuth] = None


@dataclass
class EndpointSet:
    current_user: str = "/system/user/currentUser"
    list_venues: str = "/manage/venue/listOrderCount"
    venue_detail: str = "/manage/venue/queryVenueById"
    field_situation: str = "/manage/fieldDetail/queryFieldSituation"
    field_reserve: str = "/manage/fieldDetail/queryFieldReserveSituationIsFull"
    order_confirm: str = "/venue/personal/ConfirmOrder"
    refund_create_receipt: str = "/tRefundReceipt/tRefundReceipt/createUserReceipt"
    refund_accept: str = "/tRefundReceipt/tRefundReceipt/cannelRefundReceipt"
    refund_confirm: str = "/tRefundReceipt/tRefundReceipt/cannelDetail"
    appointment_overview: Optional[str] = "/appointment/disabled/getAppintmentAndSysUserbyUser"
    slot_summary: Optional[str] = "/manage/fieldDetail/queryFieldReserveSituationIsFull"
    ping: str = "/"
    login_prepare: Optional[str] = None
    login_submit: Optional[str] = None
    login_captcha: Optional[str] = None


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
    date_offset: Optional[Union[int, List[int]]] = 7
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
    preferred_hours: Optional[List[int]] = None  # 优先时间段，如 [15, 16, 17]
    preferred_days: Optional[List[int]] = None  # 优先天数，0-8，0表示今天，1表示明天，以此类推




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
class DateAvailability:
    """Single date-level availability indicator returned by reserve summary endpoint."""

    date: str
    token: Optional[str] = None
    open: bool = True
    is_all: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def selectable(self) -> bool:
        return self.open and not self.is_all


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
