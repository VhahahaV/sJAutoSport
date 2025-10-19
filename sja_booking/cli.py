from __future__ import annotations

import argparse
import asyncio
import dataclasses
from datetime import time as dt_time, datetime, timedelta
from typing import List, Optional

from rich.console import Console
from rich.table import Table

from .api import SportsAPI
from .discovery import discover_endpoints
from .models import BookingTarget, MonitorPlan, OrderIntent, PresetOption
from .monitor import SlotMonitor
from .scheduler import schedule_daily
from . import service


PRESETS: List[PresetOption] = []


def parse_date_input(date_input: str) -> str:
    """解析日期输入，支持数字offset或标准日期格式"""
    if date_input.isdigit():
        # 数字输入，作为offset处理
        offset = int(date_input)
        target_date = datetime.now() + timedelta(days=offset)
        return target_date.strftime("%Y-%m-%d")
    else:
        # 标准日期格式，直接返回
        return date_input


def parse_time_input(time_input: str) -> str:
    """解析时间输入，支持数字或HH:MM格式"""
    if time_input.isdigit():
        # 数字输入，转换为HH:MM格式
        hour = int(time_input)
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
        else:
            raise ValueError(f"Invalid hour: {hour}. Must be 0-23")
    else:
        # 标准时间格式，直接返回
        return time_input


def clone_target(base: BookingTarget) -> BookingTarget:
    return dataclasses.replace(base, fixed_dates=list(base.fixed_dates))


def _apply_preset(tgt: BookingTarget, preset_index: int) -> None:
    for option in PRESETS:
        if option.index == preset_index:
            tgt.venue_id = option.venue_id
            tgt.venue_keyword = option.venue_name
            tgt.field_type_id = option.field_type_id
            tgt.field_type_keyword = option.field_type_name
            if option.field_type_code:
                tgt.field_type_code = option.field_type_code
            return
    raise ValueError(f"Unknown preset index: {preset_index}")


def apply_target_overrides(target: BookingTarget, args) -> BookingTarget:
    tgt = clone_target(target)
    if getattr(args, "preset", None) is not None:
        _apply_preset(tgt, args.preset)
    if args.venue_id:
        tgt.venue_id = args.venue_id
    if args.venue_keyword:
        tgt.venue_keyword = args.venue_keyword
    if args.field_type_id:
        tgt.field_type_id = args.field_type_id
    if args.field_type_keyword:
        tgt.field_type_keyword = args.field_type_keyword
    if getattr(args, "field_type_code", None):
        tgt.field_type_code = args.field_type_code
    if args.date:
        # 解析日期输入，支持数字offset
        parsed_dates = [parse_date_input(d) for d in args.date]
        tgt.fixed_dates = parsed_dates
        tgt.use_all_dates = False
    if getattr(args, "date_token", None):
        tgt.date_token = args.date_token
    if args.date_offset is not None:
        tgt.date_offset = args.date_offset
    if args.start_hour is not None:
        tgt.start_hour = args.start_hour
    if args.duration_hours is not None:
        tgt.duration_hours = args.duration_hours
    if not args.date and args.date_offset is None:
        tgt.use_all_dates = True
        tgt.date_offset = None
    return tgt


def cmd_debug_login(api: SportsAPI, console: Console) -> None:
    try:
        payload = api.check_login()
    except Exception as exc:  # pylint: disable=broad-except
        console.print(f"[red]Login check failed: {exc}[/red]")
        return
    user_info = payload
    if isinstance(payload, dict):
        for key in ("data", "user", "userInfo", "result", "payload"):
            candidate = payload.get(key)
            if isinstance(candidate, dict) and candidate:
                user_info = candidate
                break
    table = Table(title="Account Info", show_lines=False)
    table.add_column("Field")
    table.add_column("Value")
    shown = False
    if isinstance(user_info, dict):
        for key in ("realName", "name", "userName", "username", "code", "deptName", "mobile", "email"):
            if key in user_info and user_info[key] not in (None, ""):
                table.add_row(key, str(user_info[key]))
                shown = True
    if isinstance(payload, dict) and "code" in payload:
        table.add_row("raw.code", str(payload["code"]))
        shown = True
    if shown:
        console.print(table)
    else:
        console.print("[yellow]No printable user fields found. Raw payload follows:[/yellow]")
        console.print(payload)


def cmd_list_venues(api: SportsAPI, console: Console, keyword: Optional[str], page: int, size: int) -> None:
    venues = api.list_venues(keyword=keyword, page=page, size=size)
    title = f"Venue List (keyword: {keyword or 'ALL'})"
    table = Table(title=title, show_lines=False)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Address")
    table.add_column("Phone")
    for venue in venues:
        table.add_row(venue.id, venue.name, venue.address or "-", venue.phone or "-")
    console.print(table)


def cmd_list_presets(console: Console) -> None:
    if not PRESETS:
        console.print("[yellow]No presets defined in config.PRESET_TARGETS[/yellow]")
        return
    table = Table(title="Preset Venue / Sport Mapping", show_lines=False)
    table.add_column("#")
    table.add_column("Venue")
    table.add_column("Sport")
    table.add_column("Venue ID")
    table.add_column("Field Type ID")
    for option in sorted(PRESETS, key=lambda item: item.index):
        table.add_row(
            str(option.index),
            option.venue_name,
            option.field_type_name,
            option.venue_id,
            option.field_type_id,
        )
    console.print(table)


def cmd_list_venues_sports(console: Console) -> None:
    """显示场馆和运动类型的序号映射表"""
    if not PRESETS:
        console.print("[yellow]No presets defined in config.PRESET_TARGETS[/yellow]")
        return
    
    table = Table(title="场馆和运动类型映射表 - 使用 --preset 序号选择", show_lines=False)
    table.add_column("序号", style="cyan", justify="center")
    table.add_column("场馆名称", style="green")
    table.add_column("运动类型", style="yellow")
    table.add_column("使用示例", style="dim")
    
    for option in sorted(PRESETS, key=lambda item: item.index):
        example = f"python main.py slots --preset {option.index}"
        table.add_row(
            str(option.index),
            option.venue_name,
            option.field_type_name,
            example,
        )
    
    console.print(table)
    console.print("\n[bold cyan]使用方法：[/bold cyan]")
    console.print("1. 查看上表找到你想要的场馆和运动类型对应的序号")
    console.print("2. 使用 --preset 序号 来选择，例如：")
    console.print("   [green]python main.py slots --preset 13[/green]  # 选择南洋北苑健身房")
    console.print("   [green]python main.py monitor --preset 5[/green]  # 监控霍英东体育馆羽毛球")
    console.print("   [green]python main.py book-now --preset 1[/green]  # 立即预约学生中心篮球")


def cmd_catalog(api: SportsAPI, console: Console, max_pages: int, page_size: int) -> None:
    index = 1
    table = Table(title="Venue / Sport Catalog", show_lines=False)
    table.add_column("#")
    table.add_column("Venue")
    table.add_column("Sport")
    table.add_column("Venue ID")
    table.add_column("Field Type ID")
    for page in range(1, max_pages + 1):
        venues = api.list_venues(page=page, size=page_size)
        if not venues:
            break
        for venue in venues:
            detail = api.get_venue_detail(venue.id)
            field_types = api.list_field_types(detail)
            if not field_types:
                table.add_row(str(index), venue.name, "-", venue.id, "-")
                index += 1
                continue
            for field_type in field_types:
                table.add_row(
                    str(index),
                    venue.name,
                    field_type.name,
                    venue.id,
                    field_type.id,
                )
                index += 1
        if len(venues) < page_size:
            break
    if index == 1:
        console.print("[yellow]No venue data returned by list_venues[/yellow]")
    else:
        console.print(table)


def cmd_list_slots(api: SportsAPI, console: Console, base_target: BookingTarget, args) -> None:
    tgt = apply_target_overrides(base_target, args)

    if hasattr(args, "start_hour") and args.start_hour is not None:
        start_time = f"{args.start_hour:02d}:00"
        duration = getattr(args, "duration_hours", tgt.duration_hours or 1) or 1
        end_hour = (args.start_hour + duration) % 24
        end_time = f"{end_hour:02d}:00"
        console.print(f"[cyan]查询时段: {start_time}-{end_time}[/cyan]")

    result = asyncio.run(
        service.list_slots(
            preset=getattr(args, "preset", None),
            venue_id=getattr(args, "venue_id", None),
            field_type_id=getattr(args, "field_type_id", None),
            date=None,
            start_hour=getattr(args, "start_hour", None),
            show_full=args.show_full,
            base_target=tgt,
        )
    )

    if not result.slots:
        console.print("[yellow]No slots matched the filters[/yellow]")
        return

    render_monitor = SlotMonitor(api, result.resolved.target, MonitorPlan(enabled=False), console=console)
    render_monitor._venue_name = result.resolved.venue_name  # type: ignore[attr-defined]
    render_monitor._field_type_name = result.resolved.field_type_name  # type: ignore[attr-defined]

    rows = [(entry.date, entry.slot) for entry in result.slots]
    table = render_monitor.render_table(rows, include_full=args.show_full)
    console.print(table)


def cmd_monitor(api: SportsAPI, console: Console, base_target: BookingTarget, plan: MonitorPlan, args) -> None:
    tgt = apply_target_overrides(base_target, args)
    monitor_plan = dataclasses.replace(plan)
    if args.interval:
        monitor_plan.interval_seconds = args.interval
    if args.auto_book is not None:
        monitor_plan.auto_book = args.auto_book
    monitor_plan.enabled = True
    monitor = SlotMonitor(api, tgt, monitor_plan, console=console)
    monitor.monitor_loop()


def cmd_book_now(api: SportsAPI, console: Console, base_target: BookingTarget, args) -> None:
    tgt = apply_target_overrides(base_target, args)

    result = asyncio.run(
        service.list_slots(
            preset=getattr(args, "preset", None),
            venue_id=getattr(args, "venue_id", None),
            field_type_id=getattr(args, "field_type_id", None),
            date=None,
            start_hour=None,
            show_full=True,
            base_target=tgt,
        )
    )

    if not result.slots:
        console.print("[yellow]No slots found[/yellow]")
        return

    preferred_hour = getattr(tgt, "start_hour", None)
    chosen_entry = None
    fallback_entry = None
    for entry in result.slots:
        slot = entry.slot
        if not slot.available:
            continue
        if fallback_entry is None:
            fallback_entry = entry
        if preferred_hour is None:
            chosen_entry = entry
            break
        try:
            slot_hour = int(str(slot.start).split(":")[0])
        except Exception:  # pylint: disable=broad-except
            continue
        if slot_hour == preferred_hour:
            chosen_entry = entry
            break
    target_entry = chosen_entry or fallback_entry
    if not target_entry:
        console.print("[yellow]No available slot satisfied the target filters[/yellow]")
        render_monitor = SlotMonitor(api, result.resolved.target, MonitorPlan(enabled=False), console=console)
        render_monitor._venue_name = result.resolved.venue_name  # type: ignore[attr-defined]
        render_monitor._field_type_name = result.resolved.field_type_name  # type: ignore[attr-defined]
        rows = [(entry.date, entry.slot) for entry in result.slots]
        table = render_monitor.render_table(rows, include_full=True)
        console.print(table)
        return

    slot = target_entry.slot
    order_identifier = slot.raw.get("orderId") if isinstance(slot.raw, dict) else None
    if not order_identifier:
        if isinstance(slot.raw, dict):
            order_identifier = slot.raw.get("id")
    if not order_identifier:
        order_identifier = slot.slot_id
    if not order_identifier:
        console.print("[red]Booking failed: missing order identifier in slot payload[/red]")
        return

    intent = OrderIntent(
        venue_id=result.resolved.venue_id,
        field_type_id=result.resolved.field_type_id,
        slot_id=slot.slot_id,
        date=target_entry.date,
        order_id=str(order_identifier),
        payload=slot.raw,
    )

    try:
        response = api.order_immediately(intent)
    except Exception as exc:  # pylint: disable=broad-except
        console.print(f"[red]Booking failed: {exc}[/red]")
        return

    success = True
    message = response
    if isinstance(response, dict):
        code = response.get("code")
        success = code in (None, 0, "0") and not response.get("error")
        message = response.get("msg") or response.get("message") or str(response)
    if success:
        console.print(f"[bold green]Booking succeeded: {message}[/bold green]")
    else:
        console.print(f"[red]Booking failed: {message}[/red]")
        if isinstance(response, dict):
            console.print(response)


def cmd_order(api: SportsAPI, console: Console, args) -> None:
    import config as CFG  # pylint: disable=import-outside-toplevel

    base_target = getattr(CFG, "TARGET", BookingTarget())
    try:
        result = asyncio.run(
            service.order_once(
                preset=args.preset,
                date=args.date,
                start_time=args.start_time,
                end_time=getattr(args, "end_time", None),
                base_target=base_target,
            )
        )
    except ValueError as exc:
        console.print(f"[red]Input error: {exc}[/red]")
        return
    except Exception as exc:  # pylint: disable=broad-except
        console.print(f"[red]Order failed: {exc}[/red]")
        return

    if result.success:
        console.print("[bold green]Order succeeded[/bold green]")
        console.print(f"Message: {result.message}")
        if result.order_id:
            console.print(f"Order ID: {result.order_id}")
    else:
        console.print(f"[red]Order failed: {result.message}")
        if result.raw_response:
            console.print(f"[yellow]Raw response:[/yellow] {result.raw_response}")


def cmd_schedule(api_factory, console: Console, base_target: BookingTarget, plan: MonitorPlan, args) -> None:
    run_time = dt_time(hour=args.hour, minute=args.minute, second=args.second)

    def job() -> None:
        api = api_factory()
        try:
            cmd_book_now(api, console, base_target, args)
        finally:
            api.close()

    def warmup() -> None:
        api = api_factory()
        try:
            api.ping()
        except Exception:  # pylint: disable=broad-except
            pass
        finally:
            api.close()

    schedule_daily(job, run_time=run_time, warmup=warmup)


def run_cli(args) -> None:
    import config as CFG  # pylint: disable=import-outside-toplevel

    console = Console()

    def api_factory() -> SportsAPI:
        return SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH, preset_targets=CFG.PRESET_TARGETS)

    global PRESETS  # pylint: disable=global-statement
    PRESETS = list(getattr(CFG, "PRESET_TARGETS", []))

    if args.command == "presets":
        cmd_list_presets(console)
        return
    
    if args.command == "list":
        cmd_list_venues_sports(console)
        return

    api = api_factory()
    try:
        if args.command == "debug-login":
            cmd_debug_login(api, console)
        elif args.command == "discover":
            base_url = getattr(args, "base", None) or CFG.BASE_URL
            discover_endpoints(base_url, console=console)
        elif args.command == "catalog":
            cmd_catalog(
                api,
                console,
                max_pages=getattr(args, "pages", 3),
                page_size=getattr(args, "size", 50),
            )
        elif args.command == "venues":
            cmd_list_venues(api, console, keyword=args.keyword, page=args.page, size=args.size)
        elif args.command == "slots":
            cmd_list_slots(api, console, CFG.TARGET, args)
        elif args.command == "monitor":
            cmd_monitor(api, console, CFG.TARGET, CFG.MONITOR_PLAN, args)
        elif args.command == "book-now":
            cmd_book_now(api, console, CFG.TARGET, args)
        elif args.command == "schedule":
            cmd_schedule(api_factory, console, CFG.TARGET, CFG.MONITOR_PLAN, args)
        elif args.command == "order":
            cmd_order(api, console, args)
        else:
            console.print("[yellow]Unknown command[/yellow]")
    finally:
        api.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SJTU Sports Automation CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("debug-login", help="Check login status and show account information")
    p_discover = sub.add_parser("discover", help="Scan pages and JS files for candidate API endpoints")
    p_discover.add_argument("--base", type=str, help="Override BASE_URL when scanning")

    sub.add_parser("presets", help="List preset venue/sport mappings defined in config")
    sub.add_parser("list", help="List all available venues and sports with index numbers")

    p_catalog = sub.add_parser("catalog", help="Enumerate venues and field types with generated indices")
    p_catalog.add_argument("--pages", type=int, default=3, help="Number of venue pages to scan")
    p_catalog.add_argument("--size", type=int, default=50, help="Venue page size")

    p_venues = sub.add_parser("venues", help="List venues from the official API")
    p_venues.add_argument("--keyword", type=str, help="Filter by keyword")
    p_venues.add_argument("--page", type=int, default=1, help="Page number")
    p_venues.add_argument("--size", type=int, default=20, help="Page size")

    def add_target_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--preset", type=int, help="Use preset index from config.PRESET_TARGETS (推荐使用此选项)")
        p.add_argument("--venue-id", type=str, help="Override venue ID (不推荐，请使用 --preset)")
        p.add_argument("--venue-keyword", type=str, help="Override venue keyword search")
        p.add_argument("--field-type-id", type=str, help="Override field type ID (不推荐，请使用 --preset)")
        p.add_argument("--field-type-keyword", type=str, help="Override field type keyword")
        p.add_argument("--field-type-code", type=str, help="Provide extra code/motionId if required")
        p.add_argument("--date", type=str, action="append", help="Date: 0-8 (offset) or YYYY-MM-DD format")
        p.add_argument("--date-token", type=str, help="Provide dateId/dateToken when known")
        p.add_argument("--date-offset", type=int, help="Target today + N days (ignored when --date used)")
        p.add_argument("--start-hour", type=int, help="Desired starting hour (0-23)")
        p.add_argument("--duration-hours", type=int, help="Booking duration in hours")

    p_slots = sub.add_parser("slots", help="Query slot availability and render a table")
    add_target_args(p_slots)
    p_slots.add_argument("--show-full", action="store_true", help="Include slots that are already full")

    p_monitor = sub.add_parser("monitor", help="Continuously monitor for availability")
    add_target_args(p_monitor)
    p_monitor.add_argument("--interval", type=int, help="Polling interval in seconds")
    p_monitor.add_argument("--auto-book", action="store_true", help="Attempt booking automatically when possible")

    p_book = sub.add_parser("book-now", help="Run a single booking attempt")
    add_target_args(p_book)

    p_sched = sub.add_parser("schedule", help="Schedule a booking attempt every day at a fixed time")
    add_target_args(p_sched)
    p_sched.add_argument("--hour", type=int, default=12)
    p_sched.add_argument("--minute", type=int, default=0)
    p_sched.add_argument("--second", type=int, default=0)

    p_order = sub.add_parser("order", help="Place an order for a specific time slot")
    p_order.add_argument("--preset", type=int, required=True, help="Preset index from config.PRESET_TARGETS")
    p_order.add_argument("--date", type=str, required=True, help="Date: 0-8 (offset) or YYYY-MM-DD format")
    p_order.add_argument("--start-time", "--st", type=str, default="21", help="Start time: 0-23 (hour) or HH:MM format")
    p_order.add_argument("--end-time", type=str, help="End time: 0-23 (hour) or HH:MM format (auto: start+1h if not provided)")

    return parser
