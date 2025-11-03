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
    """认证配置，支持多用户"""
    users: List[UserAuth] = field(default_factory=list)


@dataclass
class EndpointSet:
    current_user: str = "/system/user/currentUser"
    list_venues: str = "/manage/venue/listOrderCount"
    venue_detail: str = "/manage/venue/queryVenueById"
    field_situation: str = "/manage/fieldDetail/queryFieldSituation"
    field_reserve: str = "/manage/fieldDetail/queryFieldReserveSituationIsFull"
    order_submit: str = "/venue/personal/orderImmediatelyPC"
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
    # 多用户支持
    target_users: List[str] = field(default_factory=list)  # 指定预订的用户昵称列表，空表示所有用户
    exclude_users: List[str] = field(default_factory=list)  # 排除的用户昵称列表


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
    require_all_users_success: bool = False  # 是否要求所有用户都成功
    max_time_gap_hours: int = 1  # 当需要所有用户成功时，允许的最大时间差


@dataclass
class SchedulePlan:
    hour: int = 12
    minute: int = 0
    second: int = 0
    date_offset: int = 1
    start_hours: List[int] = field(default_factory=lambda: [18])
    duration_hours: int = 1
    auto_start: bool = True

    @property
    def start_hour(self) -> int:
        if self.start_hours:
            return self.start_hours[0]
        return 18


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
