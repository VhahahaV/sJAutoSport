"""Single-account CLI schemas. No user selectors or booking timers."""
import asyncio
import base64
import dataclasses
import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from . import config, service
from .database import get_db_manager
from .keep_alive import run_keep_alive_once
from .models import BookingTarget
Hour = Annotated[int, Field(ge=0, le=23)]
Day = Annotated[int, Field(ge=0, le=365)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Empty(Input):
    pass


class KeepAliveConfig(Input):
    enabled: bool = True
    interval_minutes: Annotated[int, Field(ge=1)] = 15

class Login(Input):
    username: Identifier
    password: SecretStr
    nickname: str | None = None

class Session(Input):
    session_id: Identifier

class Verify(Session):
    code: Annotated[str, Field(min_length=1, max_length=32)]

class VenueQuery(Input):
    keyword: str | None = None
    page: Annotated[int, Field(ge=1)] = 1
    size: Annotated[int, Field(ge=1, le=100)] = 50
    flag: int = 0

class Venue(Input):
    venue_id: Identifier

class Target(Input):
    venue_id: str | None = None
    venue_keyword: str | None = None
    field_type_id: str | None = None
    field_type_keyword: str | None = None
    field_type_code: str | None = None
    date_token: str | None = None
    use_all_dates: bool = False
    date_offset: Day | list[Day] | None = 7
    fixed_dates: list[str] = Field(default_factory=list)
    start_hour: Hour = 18
    duration_hours: Annotated[int, Field(ge=1, le=24)] = 1

class Selection(Input):
    preset: Annotated[int, Field(ge=1)] | None = None
    venue_id: str | None = None
    field_type_id: str | None = None
    target: Target = Field(default_factory=Target)

class Slots(Selection):
    date: str | None = None
    start_hour: Hour | None = None
    show_full: bool = False
    all_dates: bool = False

    @field_validator("date")
    @classmethod
    def date_is_valid(cls, value):
        if value is not None:
            if value.isdigit() and 0 <= int(value) <= 365:
                return value
            datetime.strptime(value, "%Y-%m-%d")
        return value

class Order(Input):
    preset: Annotated[int, Field(ge=1)]
    date: str
    start_time: str
    end_time: str | None = None
    target: Target = Field(default_factory=Target)

    @field_validator("date")
    @classmethod
    def date_is_valid(cls, value):
        return Slots.date_is_valid(value)

    @field_validator("start_time", "end_time")
    @classmethod
    def time_is_valid(cls, value):
        if value is not None:
            value = service._parse_time_input(value)
            datetime.strptime(value, "%H:%M")
        return value

class CancelOrder(Input):
    order_id: Identifier

class Orders(Input):
    page_no: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 100

class Monitor(Slots):
    monitor_id: Identifier
    interval_seconds: Annotated[int, Field(ge=30)] = 240
    auto_book: bool = False
    long_running: bool = False
    operating_start_hour: Annotated[int, Field(ge=0, le=24)] = 0
    operating_end_hour: Annotated[int, Field(ge=0, le=24)] = 24
    preferred_hours: list[Hour] | None = None
    preferred_days: list[Day] | None = None

class MonitorID(Input):
    monitor_id: Identifier

class DashboardCard(Input):
    preset: Annotated[int, Field(ge=1)]
    days: Annotated[int, Field(ge=1, le=7)] = 3

class DashboardCardID(Input):
    card_id: Identifier

class Limit(Input):
    limit: Annotated[int, Field(ge=1, le=1000)] = 50

class Events(Limit):
    after: Annotated[int, Field(ge=0)] = 0

def public(value):
    """Do not return cookies, passwords, signed order payloads or raw responses."""
    if dataclasses.is_dataclass(value):
        fields = {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        for property_name in ("label", "selectable"):
            if hasattr(value, property_name):
                fields[property_name] = getattr(value, property_name)
        value = fields
    if isinstance(value, dict):
        private = {"cookie", "cookies", "password", "token", "authorization", "sign", "raw", "raw_response"}
        return {k: public(v) for k, v in value.items() if str(k).lower() not in private}
    if isinstance(value, (list, tuple)):
        return [public(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class Operations:
    def __init__(self):
        self.db = get_db_manager()
        self.captchas = {}


    def login_result(self, result, session_id=None):
        result = dict(result)
        qr = "qr_image" in result
        image = result.pop("qr_image" if qr else "captcha_image", None)
        prefix = "qr" if qr else "captcha"
        sid = result.get("session_id") or session_id
        old = self.captchas.pop(sid, None)
        if old:
            old.unlink(missing_ok=True)
        if image:
            directory = config.DATA_DIR / "captchas"
            directory.mkdir(mode=0o700, exist_ok=True)
            mime, extension = ("image/jpeg", "jpg") if image.startswith(b"\xff\xd8") else ("image/gif", "gif") if image.startswith(b"GIF8") else ("image/png", "png")
            path = directory / f"{uuid.uuid4().hex}.{extension}"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(image)
            self.captchas[sid] = path
            result.update({f"{prefix}_path": str(path), f"{prefix}_mime": mime,
                           f"{prefix}_base64": base64.b64encode(image).decode("ascii"), "session_id": sid})
        return result


    @staticmethod
    def selection(data):
        data = dict(data)
        data["base_target"] = BookingTarget(**data.pop("target"))
        return data

    async def dispatch(self, operation, payload):
        if operation not in CONTRACTS:
            raise ValueError(f"Unknown operation {operation}; run sja schema")
        model = CONTRACTS[operation][0].model_validate(payload)
        data = model.model_dump()
        service.initialize_database()
        if operation == "auth.start":
            for sid in list(self.captchas):
                self.login_result({}, sid)
            data["password"] = model.password.get_secret_value()
            return self.login_result(await service.start_login_session(**data))
        if operation == "auth.qr-start":
            for sid in list(self.captchas):
                self.login_result({}, sid)
            return self.login_result(await service.start_qr_login())
        if operation == "auth.qr-status":
            return self.login_result(service.qr_login_status(**data), data["session_id"])
        if operation == "auth.qr-cancel":
            return self.login_result(await service.cancel_qr_login(**data), data["session_id"])
        if operation == "auth.verify":
            return self.login_result(await service.submit_login_session_code(**data), data["session_id"])
        if operation == "auth.cancel":
            return self.login_result(await service.cancel_login_session(**data), data["session_id"])
        if operation == "auth.status":
            return await asyncio.to_thread(service.login_status)
        if operation == "auth.logout":
            for sid in list(service._qr_sessions):
                await service.cancel_qr_login(sid)
            for sid in list(service._login_sessions):
                await service.cancel_login_session(sid)
            for monitor_id in list(service._active_monitors):
                if service._active_monitors[monitor_id]["status"] == "running":
                    await service.pause_monitor(monitor_id)
            await service.configure_keep_alive(enabled=False)
            return service.clear_account()
        await service.require_authenticated()
        if operation == "account.info":
            return await service.fetch_user_info()
        if operation == "dashboard.list":
            return self.db.all("dashboard_card")
        if operation == "dashboard.add":
            if not service._get_preset(data["preset"]):
                raise ValueError("无效的场馆项目")
            card = {"id": str(uuid.uuid4()), **data}
            self.db.put("dashboard_card", card["id"], card)
            return card
        if operation in {"dashboard.delete", "dashboard.availability"}:
            card = self.db.get("dashboard_card", data["card_id"])
            if not card:
                raise ValueError("卡片不存在，请刷新总览")
            if operation == "dashboard.delete":
                self.db.delete("dashboard_card", card["id"])
                return {"success": True}
            return await service.dashboard_availability(card)
        if operation == "presets.list":
            return config.PRESET_TARGETS
        if operation == "venues.list":
            return await service.list_venues(**data)
        if operation == "venues.fields":
            return await service.list_field_types(**data)
        if operation == "dates.list":
            return await service.list_date_availability(**self.selection(data))
        if operation == "slots.list":
            return await service.list_slots(**self.selection(data))
        if operation == "orders.list":
            return await asyncio.to_thread(service.get_user_orders, **data)
        if operation == "orders.create":
            return await service.order_once(**self.selection(data))
        if operation == "orders.cancel":
            return await service.cancel_order(**data)
        if operation == "monitors.create":
            data.pop("show_full")
            data.pop("all_dates")
            return await service.start_monitor(**self.selection(data))
        if operation == "monitors.list":
            return await service.monitor_status()
        if operation == "monitors.pause":
            return await service.pause_monitor(**data)
        if operation == "monitors.resume":
            return await service.resume_monitor(**data)
        if operation == "monitors.delete":
            return await service.delete_monitor(**data)
        if operation == "keep-alive.run":
            return await run_keep_alive_once()
        if operation == "keep-alive.configure":
            return await service.configure_keep_alive(**data)
        if operation == "keep-alive.status":
            return service.keep_alive_status()
        if operation == "history.list":
            return list(reversed(self.db.all("booking")))[:data["limit"]]
        if operation == "events.list":
            with sqlite3.connect(self.db.db_path) as conn:
                rows = conn.execute("SELECT rowid,payload FROM records WHERE kind='event' AND rowid>? ORDER BY rowid LIMIT ?",
                                    (data["after"], data["limit"])).fetchall()
            return {"events": [{"cursor": row[0], **json.loads(row[1])} for row in rows],
                    "next_cursor": rows[-1][0] if rows else data["after"]}
        raise ValueError(operation)


CONTRACTS = {
    "dashboard.list": (Empty, "List saved venue availability cards"),
    "dashboard.add": (DashboardCard, "Add a venue/sport card for the next 1–7 days including today"),
    "dashboard.delete": (DashboardCardID, "Remove a saved dashboard card"),
    "dashboard.availability": (DashboardCardID, "Check date summaries and load available slots for one card"),
    "auth.start": (Login, "First step: sign in; receive captcha image for the user"),
    "auth.verify": (Verify, "Submit the user's captcha answer"),
    "auth.cancel": (Session, "Cancel unfinished login"),
    "auth.status": (Empty, "Verify the single saved account"),
    "auth.logout": (Empty, "Remove the saved login session"),
    "auth.qr-start": (Empty, "Generate a fresh jAccount QR image and subscribe for scan confirmation"),
    "auth.qr-status": (Session, "Poll QR status and refreshed image; success means the sports session is verified"),
    "auth.qr-cancel": (Session, "Cancel the QR login subscription and remove its image"),
    "account.info": (Empty, "Read the current account profile"),
    "presets.list": (Empty, "List venue/sport presets"),
    "venues.list": (VenueQuery, "Search venues"),
    "venues.fields": (Venue, "List sports in a venue"),
    "dates.list": (Selection, "List selectable dates"),
    "slots.list": (Slots, "Query slots; show_full includes unavailable slots"),
    "orders.list": (Orders, "Paginate the current account's orders"),
    "orders.create": (Order, "Create one real reservation"),
    "orders.cancel": (CancelOrder, "Cancel/refund a real reservation"),
    "monitors.create": (Monitor, "Watch slots; auto_book defaults to false"),
    "monitors.list": (Empty, "List live monitors and saved state"),
    "monitors.pause": (MonitorID, "Pause a live monitor"),
    "monitors.resume": (MonitorID, "Resume a paused monitor"),
    "monitors.delete": (MonitorID, "Stop and delete a monitor"),
    "keep-alive.run": (Empty, "Verify and refresh this session now"),
    "keep-alive.configure": (KeepAliveConfig, "Enable/disable periodic session maintenance"),
    "keep-alive.status": (Empty, "Read session maintenance settings and result"),
    "history.list": (Limit, "Read local reservation history"),
    "events.list": (Events, "Read notification events using an integer cursor"),
}
