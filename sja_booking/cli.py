from __future__ import annotations

import argparse
import dataclasses
from datetime import time as dt_time
from typing import Optional

from rich.console import Console
from rich.table import Table

from .api import SportsAPI
from .discovery import discover_endpoints
from .models import BookingTarget, MonitorPlan
from .monitor import SlotMonitor
from .scheduler import schedule_daily


def clone_target(base: BookingTarget) -> BookingTarget:
    return dataclasses.replace(
        base,
        fixed_dates=list(base.fixed_dates),
    )


def apply_target_overrides(target: BookingTarget, args) -> BookingTarget:
    tgt = clone_target(target)
    if args.venue_id:
        tgt.venue_id = args.venue_id
    if args.venue_keyword:
        tgt.venue_keyword = args.venue_keyword
    if args.field_type_id:
        tgt.field_type_id = args.field_type_id
    if args.field_type_keyword:
        tgt.field_type_keyword = args.field_type_keyword
    if args.date:
        tgt.fixed_dates = args.date
    if args.date_offset is not None:
        tgt.date_offset = args.date_offset
    if args.start_hour is not None:
        tgt.start_hour = args.start_hour
    if args.duration_hours is not None:
        tgt.duration_hours = args.duration_hours
    return tgt


def cmd_debug_login(api: SportsAPI, console: Console) -> None:
    try:
        payload = api.check_login()
    except Exception as exc:
        console.print(f"[red]登录检查失败：{exc}[/red]")
        return
    user_info = payload
    if isinstance(payload, dict):
        for key in ("data", "user", "userInfo", "result", "payload"):
            candidate = payload.get(key)
            if isinstance(candidate, dict) and candidate:
                user_info = candidate
                break
    table = Table(title="登录信息", show_lines=False)
    table.add_column("字段")
    table.add_column("值")
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
        console.print("[yellow]未在响应中找到可显示的用户字段，原始返回如下：[/yellow]")
        console.print(payload)


def cmd_list_venues(api: SportsAPI, console: Console, keyword: Optional[str], page: int, size: int) -> None:
    venues = api.list_venues(keyword=keyword, page=page, size=size)
    table = Table(title=f"场馆列表（关键词：{keyword or '全部'}）", show_lines=False)
    table.add_column("ID")
    table.add_column("名称")
    table.add_column("地址")
    table.add_column("电话")
    for venue in venues:
        table.add_row(venue.id, venue.name, venue.address or "-", venue.phone or "-")
    console.print(table)


def cmd_list_slots(api: SportsAPI, console: Console, base_target: BookingTarget, args) -> None:
    tgt = apply_target_overrides(base_target, args)
    monitor = SlotMonitor(api, tgt, MonitorPlan(enabled=False), console=console)
    slots = monitor.run_once(include_full=args.show_full)
    if not slots:
        console.print("[yellow]未找到可用时段[/yellow]")
        return
    table = monitor.render_table(slots, include_full=args.show_full)
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
    monitor = SlotMonitor(api, tgt, MonitorPlan(enabled=False, auto_book=True), console=console)
    slots = monitor.run_once(include_full=True)
    if not slots:
        console.print("[yellow]未找到任何时段[/yellow]")
        return
    slot = None
    for date_str, candidate in slots:
        chosen = monitor.api.pick_slot([candidate], tgt.start_hour, tgt.duration_hours)
        if chosen and candidate.available:
            slot = (date_str, candidate)
            break
        if candidate.available:
            slot = (date_str, candidate)
            break
    if not slot:
        console.print("[yellow]没有符合条件的可预约时段[/yellow]")
        table = monitor.render_table(slots, include_full=True)
        console.print(table)
        return
    ok, msg = monitor.attempt_booking(*slot)
    if ok:
        console.print(f"[bold green]下单成功：{msg}[/bold green]")
    else:
        console.print(f"[red]下单失败：{msg}[/red]")


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
        return SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH)

    api = api_factory()
    try:
        if args.command == "debug-login":
            cmd_debug_login(api, console)
        elif args.command == "discover":
            base_url = getattr(args, "base", None) or CFG.BASE_URL
            discover_endpoints(base_url, console=console)
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
        else:
            console.print("[yellow]未知命令[/yellow]")
    finally:
        api.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SJTU Sports 自动化工具")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("debug-login", help="检查登录态并显示账号信息")
    p_discover = sub.add_parser("discover", help="扫描页面提取候选 API")
    p_discover.add_argument("--base", type=str, help="覆盖默认 BASE_URL")

    p_venues = sub.add_parser("venues", help="列出场馆列表")
    p_venues.add_argument("--keyword", type=str, help="场馆关键字")
    p_venues.add_argument("--page", type=int, default=1, help="页码")
    p_venues.add_argument("--size", type=int, default=20, help="每页数量")

    def add_target_args(p):
        p.add_argument("--venue-id", type=str, help="指定场馆 ID")
        p.add_argument("--venue-keyword", type=str, help="模糊匹配场馆名称")
        p.add_argument("--field-type-id", type=str, help="指定项目 ID")
        p.add_argument("--field-type-keyword", type=str, help="模糊匹配项目名称")
        p.add_argument("--date", type=str, action="append", help="指定日期 YYYY-MM-DD，可多次提供")
        p.add_argument("--date-offset", type=int, help="今天 + N 天进行尝试")
        p.add_argument("--start-hour", type=int, help="目标开始小时")
        p.add_argument("--duration-hours", type=int, help="预约时长（小时）")

    p_slots = sub.add_parser("slots", help="查询时段余量并输出表格")
    add_target_args(p_slots)
    p_slots.add_argument("--show-full", action="store_true", help="显示已满时段")

    p_monitor = sub.add_parser("monitor", help="持续监测余票并可自动下单")
    add_target_args(p_monitor)
    p_monitor.add_argument("--interval", type=int, help="轮询间隔（秒）")
    p_monitor.add_argument("--auto-book", action="store_true", help="发现余票后自动下单")

    p_book = sub.add_parser("book-now", help="立即尝试抢票")
    add_target_args(p_book)

    p_sched = sub.add_parser("schedule", help="每天固定时间自动抢票")
    add_target_args(p_sched)
    p_sched.add_argument("--hour", type=int, default=12)
    p_sched.add_argument("--minute", type=int, default=0)
    p_sched.add_argument("--second", type=int, default=0)

    return parser
