from __future__ import annotations

import argparse
import asyncio
import dataclasses
import getpass
import os
import re
from datetime import time as dt_time, datetime, timedelta
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from .api import SportsAPI
from .discovery import discover_endpoints
from .models import AuthConfig, BookingTarget, MonitorPlan, OrderIntent, PresetOption, UserAuth
from .monitor import SlotMonitor
from .scheduler import schedule_daily
from .auth import AuthManager, perform_login
from .ocr import solve_captcha_async
from .multi_user import MultiUserManager, UserBookingResult
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


def parse_start_hours_arg(raw: Optional[str]) -> List[int]:
    """解析逗号或空格分隔的开始时间列表"""
    if not raw:
        return []
    segments = re.split(r"[\s,]+", raw.strip())
    result: List[int] = []
    for segment in segments:
        if not segment:
            continue
        try:
            value = int(segment)
        except ValueError:
            continue
        if 0 <= value <= 23:
            result.append(value)
    # 去重保持顺序
    seen = set()
    unique: List[int] = []
    for value in result:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


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


def _print_user_info(console: Console, header: Optional[str], payload: Dict[str, Any]) -> None:
    if header:
        console.print(f"\n[bold blue]{header}[/bold blue]")

    # 首先检查原始响应的状态码
    response_code = payload.get("code") if isinstance(payload, dict) else None
    if response_code not in (None, 0, "0"):
        console.print("[red]❌ 登录失败[/red]")
        console.print("[yellow]系统提醒：查询用户信息失败，请重新登录[/yellow]")
        return

    # 然后提取用户信息
    user_info: Dict[str, Any] = payload
    for key in ("data", "user", "userInfo", "result", "payload"):
        candidate = user_info.get(key) if isinstance(user_info, dict) else None
        if isinstance(candidate, dict) and candidate:
            user_info = candidate
            break

    if not isinstance(user_info, dict):
        console.print("[red]❌ 登录失败[/red]")
        console.print("[yellow]系统提醒：查询用户信息失败，请重新登录[/yellow]")
        return

    # 检查是否包含用户详细信息
    has_user_details = any(key in user_info for key in ['userName', 'loginName', 'createTime', 'phonenumber'])
    
    if not has_user_details:
        # 如果只有基本状态信息，说明认证成功但无法获取详细信息
        console.print("[green]✅ 登录成功[/green]")
        console.print("[yellow]⚠️  注意：认证有效但无法获取用户详细信息[/yellow]")
        console.print("[blue]💡 这通常表示Cookie有效，可以正常使用其他功能（如下单）[/blue]")
        return

    console.print("[green]✅ 登录成功[/green]")

    create_time = user_info.get("createTime", "未知")
    login_name = user_info.get("loginName", "未知")
    user_name = user_info.get("userName", "未知")
    phone = user_info.get("phonenumber", "未知")
    sex = user_info.get("sex", "未知")
    code_value = user_info.get("code", "未知")
    class_no = user_info.get("classNo", "未知")
    admin = user_info.get("admin", False)

    sex_display = "男" if sex == "0" else "女" if sex == "1" else "未知"

    dept_name = "未知"
    if isinstance(user_info.get("dept"), dict):
        dept_name = user_info["dept"].get("deptName", "未知")

    roles: List[str] = []
    if isinstance(user_info.get("roles"), list):
        for role in user_info["roles"]:
            if isinstance(role, dict) and "roleName" in role:
                roles.append(str(role["roleName"]))

    table = Table(title="🎉 用户信息", show_header=True, header_style="bold magenta")
    table.add_column("项目", style="cyan", width=15)
    table.add_column("信息", style="green")

    table.add_row("创建时间", str(create_time))
    table.add_row("登录名", str(login_name))
    table.add_row("姓名", str(user_name))
    table.add_row("手机号", str(phone))
    table.add_row("性别", sex_display)
    table.add_row("部门", str(dept_name))
    table.add_row("学号", str(code_value))
    table.add_row("班级", str(class_no))
    table.add_row("管理员", "是" if admin else "否")

    if roles:
        table.add_row("角色", "\n".join(roles))
    else:
        table.add_row("角色", "无")

    console.print(table)


def cmd_show_user_info(api: SportsAPI, console: Console, *, header: Optional[str] = None) -> None:
    try:
        payload = api.check_login()
    except Exception as exc:  # pylint: disable=broad-except
        console.print(f"[red]Login check failed: {exc}")
        return

    if isinstance(payload, dict):
        _print_user_info(console, header, payload)
    else:
        console.print("[yellow]Unexpected response format[/yellow]")
        console.print(payload)


def cmd_list_users(api: SportsAPI, console: Console) -> None:
    """列出所有配置的用户"""
    from rich.table import Table
    
    users = api.auth.users
    if not users:
        console.print("[yellow]没有配置的用户[/yellow]")
        return
    
    console.print("[bold blue]已配置的用户列表:[/bold blue]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("昵称", style="cyan")
    table.add_column("用户名", style="green")
    table.add_column("密码已保存", style="yellow")
    table.add_column("状态", style="blue")
    
    # 检查当前活跃的 Cookie
    from .auth import AuthManager
    auth_manager = AuthManager()
    cookie_map, active_username = auth_manager.load_all_cookies()

    for user in users:
        if not user.username:
            continue
            
        password_saved = "是" if user.password else "否"
        record = cookie_map.get(user.username)

        if record:
            if active_username == user.username:
                status = "🟢 当前活跃"
            else:
                status = "🟠 已保存"
        else:
            status = "⚪ 未登录"
        
        table.add_row(
            user.nickname,
            user.username,
            password_saved,
            status
        )
    
    console.print(table)


def cmd_switch_user(api: SportsAPI, console: Console, nickname: str) -> None:
    """切换到指定用户"""
    multi_user_manager = MultiUserManager(api.auth, console)
    user = multi_user_manager.get_user_by_nickname(nickname)
    
    if not user:
        console.print(f"[red]用户 '{nickname}' 不存在[/red]")
        return
    
    if not (user.cookie or user.token):
        console.print(f"[red]用户 '{nickname}' 没有有效的认证信息[/red]")
        return
    
    api.switch_to_user(user)
    console.print(f"[green]已切换到用户: {nickname}[/green]")


def cmd_validate_users(api: SportsAPI, console: Console) -> None:
    """验证用户配置"""
    multi_user_manager = MultiUserManager(api.auth, console)
    is_valid, errors = multi_user_manager.validate_users()
    
    if is_valid:
        console.print("[green]✅ 所有用户配置有效[/green]")
    else:
        console.print("[red]❌ 用户配置存在问题:[/red]")
        for error in errors:
            console.print(f"[red]  - {error}[/red]")


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


def cmd_login(console: Console, cfg, args, auth_manager: AuthManager) -> None:
    from .user_manager import select_user, get_login_credentials, save_user_to_config
    
    # 如果通过命令行参数提供了用户名和密码，直接使用
    login_user: Optional["UserAuth"] = None  # type: ignore[name-defined]
    if args.username and args.password:
        username = args.username
        password = args.password
    else:
        # 使用用户管理流程
        selected_user, is_new_user = select_user(cfg.AUTH)
        if selected_user is None and not is_new_user:
            console.print("[yellow]取消登录[/yellow]")
            return
        
        try:
            username, password, login_user_candidate = get_login_credentials(selected_user)
            login_user = login_user_candidate
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

    async def run_login() -> None:
        if args.no_prompt:
            async def _empty_fallback(_: bytes) -> str:
                return ""
            fallback_local = _empty_fallback
        else:
            fallback_local = None
            
        result = await perform_login(
            cfg.BASE_URL,
            cfg.ENDPOINTS,
            cfg.AUTH,
            username,
            password,
            solver=None if args.no_ocr else solve_captcha_async,
            fallback=fallback_local,
            max_retries=5,  # 最多重试5次
            retry_delay=3,  # 每次重试间隔3秒
        )
        
        # 保存 Cookie 到持久化存储
        nickname_for_store: Optional[str] = None
        if login_user and login_user.nickname:
            nickname_for_store = login_user.nickname
        else:
            nickname_for_store = username.split("@")[0]

        auth_manager.save_cookie(
            result.cookie_header,
            result.expires_at,
            username=username,
            nickname=nickname_for_store,
        )

        # 更新内存中的用户配置与状态
        if login_user:
            login_user.cookie = result.cookie_header
            login_user.username = username
            if login_user.nickname != "临时用户":
                save_user_to_config(login_user, cfg.AUTH)
        else:
            try:
                for user in getattr(cfg.AUTH, "users", []) or []:
                    if user.username == username:
                        user.cookie = result.cookie_header
                        break
            except Exception:
                pass
        
        console.print(
            f"[green]登录成功，有效期至 {result.expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}[/green]"
        )

    asyncio.run(run_login())


def cmd_logout(console: Console, auth_manager: AuthManager) -> None:
    auth_manager.clear()
    console.print("[green]已清除本地持久化 Cookie[/green]")


def cmd_user_management(console: Console, cfg) -> None:
    """用户管理命令"""
    from .user_manager import show_user_management_menu
    show_user_management_menu(cfg.AUTH)


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
    if getattr(args, "start_hour", None) is not None:
        start_time = f"{args.start_hour:02d}:00"
        duration = getattr(args, "duration_hours", tgt.duration_hours or 1) or 1
        end_hour = (args.start_hour + duration) % 24
        end_time = f"{end_hour:02d}:00"
        console.print(f"[cyan]查询时段: {start_time}-{end_time}[/cyan]")

    preset_index = getattr(args, "preset", None)
    explicit_field = any([preset_index, getattr(args, "field_type_id", None), getattr(args, "field_type_keyword", None)])

    if not explicit_field:
        venue_identifier = tgt.venue_id
        if not venue_identifier and tgt.venue_keyword:
            venue = api.find_venue(tgt.venue_keyword)
            if venue:
                venue_identifier = venue.id
        if not venue_identifier:
            console.print("[red]缺少场馆 ID，请使用 --preset 或 --venue-id[/red]")
            return
        detail = api.get_venue_detail(venue_identifier)
        field_types = api.list_field_types(detail)
        if not field_types:
            console.print("[yellow]未在该场馆找到可预约项目[/yellow]")
            return
        printed_any = False
        for field_type in field_types:
            field_target = dataclasses.replace(tgt)
            field_target.field_type_id = field_type.id
            field_target.field_type_keyword = field_type.name
            result = asyncio.run(
                service.list_slots(
                    preset=None,
                    venue_id=venue_identifier,
                    field_type_id=field_type.id,
                    date=None,
                    start_hour=getattr(args, "start_hour", None),
                    show_full=args.show_full,
                    base_target=field_target,
                )
            )
            if not result.slots:
                console.print(f"[yellow]{field_type.name}: 暂无可用时段[/yellow]")
                continue
            printed_any = True
            render_monitor = SlotMonitor(api, result.resolved.target, MonitorPlan(enabled=False), console=console)
            render_monitor._venue_name = result.resolved.venue_name  # type: ignore[attr-defined]
            render_monitor._field_type_name = field_type.name  # type: ignore[attr-defined]
            rows = [(entry.date, entry.slot) for entry in result.slots]
            table = render_monitor.render_table(rows, include_full=args.show_full)
            table.title = f"{result.resolved.venue_name or venue_identifier} - {field_type.name}"
            console.print(table)
        if not printed_any:
            console.print("[yellow]未找到任何时间段[/yellow]")
        return

    result = asyncio.run(
        service.list_slots(
            preset=preset_index,
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
    
    # 处理多用户参数
    if hasattr(args, 'users') and args.users:
        tgt.target_users = [nickname.strip() for nickname in args.users.split(',')]
        console.print(f"[green]指定预订用户: {tgt.target_users}[/green]")
    
    if hasattr(args, 'exclude_users') and args.exclude_users:
        tgt.exclude_users = [nickname.strip() for nickname in args.exclude_users.split(',')]
        console.print(f"[green]排除用户: {tgt.exclude_users}[/green]")
    
    # 处理优先时间段设置
    if hasattr(args, 'pt') and args.pt:
        try:
            # 解析优先时间段，如 "15,16,17" -> [15, 16, 17]
            preferred_hours = [int(h.strip()) for h in args.pt.split(',')]
            monitor_plan.preferred_hours = preferred_hours
            console.print(f"[green]设置优先时间段: {preferred_hours}[/green]")
        except ValueError:
            console.print(f"[red]无效的优先时间段格式: {args.pt}，应为 '15,16,17' 格式[/red]")
            return
    elif monitor_plan.preferred_hours:
        # 显示配置文件中的优先时间段
        console.print(f"[green]使用配置的优先时间段: {monitor_plan.preferred_hours}[/green]")
    else:
        console.print(f"[yellow]没有设置优先时间段[/yellow]")
    
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
            # 处理 slot-X 格式的时间
            if str(slot.start).startswith("slot-"):
                slot_num = int(str(slot.start).split("-")[1])
                slot_hour = (7 + slot_num) % 24  # slot-0对应07:00
            else:
                # 处理 HH:MM 格式的时间
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
    
    # 处理多用户参数
    if hasattr(args, 'users') and args.users:
        base_target.target_users = [nickname.strip() for nickname in args.users.split(',')]
        console.print(f"[green]指定预订用户: {base_target.target_users}[/green]")
    
    if hasattr(args, 'exclude_users') and args.exclude_users:
        base_target.exclude_users = [nickname.strip() for nickname in args.exclude_users.split(',')]
        console.print(f"[green]排除用户: {base_target.exclude_users}[/green]")
    
    # 多用户预订
    multi_user_manager = MultiUserManager(api.auth, console)
    target_users = multi_user_manager.get_users_for_booking(base_target)
    
    if not target_users:
        console.print("[red]没有可用的用户进行预订[/red]")
        return
    
    if len(target_users) == 1:
        # 单用户预订（向后兼容）
        user = target_users[0]
        api.switch_to_user(user)
        console.print(f"[blue]使用用户: {user.nickname}[/blue]")
        
        try:
                result = asyncio.run(
                    service.order_once(
                        preset=args.preset,
                        date=args.date,
                        start_time=args.start_time,
                        end_time=getattr(args, "end_time", None),
                        base_target=base_target,
                        user=user.username or user.nickname,
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
    else:
        # 多用户预订
        console.print(f"[blue]为 {len(target_users)} 个用户进行预订: {[u.nickname for u in target_users]}[/blue]")
        
        results = []
        for user in target_users:
            console.print(f"\n[blue]--- 为用户 {user.nickname} 预订 ---[/blue]")
            api.switch_to_user(user)
            
            try:
                result = asyncio.run(
                    service.order_once(
                        preset=args.preset,
                        date=args.date,
                        start_time=args.start_time,
                        end_time=getattr(args, "end_time", None),
                        base_target=base_target,
                        user=user.username or user.nickname,
                    )
                )
                
                user_result = UserBookingResult(
                    nickname=user.nickname,
                    success=result.success,
                    message=result.message,
                    order_id=result.order_id,
                    error=result.message if not result.success else None
                )
                results.append(user_result)
                
            except Exception as exc:
                user_result = UserBookingResult(
                    nickname=user.nickname,
                    success=False,
                    message="预订失败",
                    error=str(exc)
                )
                results.append(user_result)
                console.print(f"[red]用户 {user.nickname} 预订失败: {exc}[/red]")
        
        # 打印汇总结果
        multi_user_manager.print_user_status(results)


def cmd_schedule(api_factory, console: Console, base_target: BookingTarget, plan: MonitorPlan, args) -> None:
    schedule_defaults = None
    try:
        import config as CFG  # pylint: disable=import-outside-toplevel
        schedule_defaults = getattr(CFG, "SCHEDULE_PLAN", None)
    except Exception:  # pylint: disable=broad-except
        schedule_defaults = None

    run_time = dt_time(hour=args.hour, minute=args.minute, second=args.second)

    def job() -> None:
        api = api_factory()
        try:
            print(f"[DEBUG] 开始执行预订任务...")
            print(f"[DEBUG] 目标配置: preset={getattr(args, 'preset', None)}, start_hour={getattr(args, 'start_hour', None)}")
            print(f"[DEBUG] 日期偏移: {getattr(args, 'date_offset', None)}")
            
            # 使用 order 模块的逻辑
            from .multi_user import MultiUserManager, UserBookingResult
            
            # 处理多用户参数
            if hasattr(args, 'users') and args.users:
                base_target.target_users = list(dict.fromkeys(nickname.strip() for nickname in args.users.split(',') if nickname.strip()))
                console.print(f"[green]指定预订用户: {base_target.target_users}[/green]")
            
            if hasattr(args, 'exclude_users') and args.exclude_users:
                base_target.exclude_users = list(dict.fromkeys(nickname.strip() for nickname in args.exclude_users.split(',') if nickname.strip()))
                console.print(f"[green]排除用户: {base_target.exclude_users}[/green]")
            
            # 多用户预订
            multi_user_manager = MultiUserManager(api.auth, console)
            target_users = multi_user_manager.get_users_for_booking(base_target)
            
            if not target_users:
                console.print("[red]没有可用的用户进行预订[/red]")
                return
            
            # 计算目标日期
            from datetime import datetime, timedelta
            date_offset = getattr(args, 'date_offset', None)
            if date_offset is None and schedule_defaults is not None:
                date_offset = schedule_defaults.date_offset
            if date_offset is None:
                date_offset = 1
            target_date = datetime.now() + timedelta(days=date_offset)
            date_str = target_date.strftime("%Y-%m-%d")
            
            # 计算开始时间
            start_hours = parse_start_hours_arg(getattr(args, 'start_hours', None))
            if not start_hours and getattr(args, 'start_hour', None) is not None:
                start_hours = [int(getattr(args, 'start_hour'))]
            if not start_hours and schedule_defaults is not None:
                if getattr(schedule_defaults, 'start_hours', None):
                    start_hours = list(getattr(schedule_defaults, 'start_hours'))
                elif getattr(schedule_defaults, 'start_hour', None) is not None:
                    start_hours = [int(getattr(schedule_defaults, 'start_hour'))]
            if not start_hours:
                start_hours = [base_target.start_hour or 18]

            base_target.start_hour = start_hours[0]
            start_time = f"{start_hours[0]:02d}"
            
            print(f"[DEBUG] 预订日期: {date_str}")
            print(f"[DEBUG] 预订时间: {', '.join(f'{h:02d}:00' for h in start_hours)}")
            print(f"[DEBUG] 目标用户: {[u.nickname for u in target_users]}")
            
            if len(target_users) == 1:
                # 单用户预订
                user = target_users[0]
                api.switch_to_user(user)
                console.print(f"[blue]使用用户: {user.nickname}[/blue]")
                
                try:
                        result = asyncio.run(
                        service.order_once(
                            preset=args.preset,
                            date=date_str,
                            start_time=start_time,
                            end_time=None,
                            base_target=base_target,
                            user=user.username or user.nickname,
                        )
                        )
                except ValueError as exc:
                    console.print(f"[red]Input error: {exc}[/red]")
                    return
                except Exception as exc:
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
            else:
                # 多用户预订
                console.print(f"[blue]为 {len(target_users)} 个用户进行预订: {[u.nickname for u in target_users]}[/blue]")
                
                results = []
                for user in target_users:
                    console.print(f"\n[blue]--- 为用户 {user.nickname} 预订 ---[/blue]")
                    api.switch_to_user(user)
                    
                    try:
                        result = asyncio.run(
                            service.order_once(
                                preset=args.preset,
                                date=date_str,
                                start_time=start_time,
                                end_time=None,
                                base_target=base_target,
                                user=user.nickname,
                            )
                        )
                        
                        user_result = UserBookingResult(
                            nickname=user.nickname,
                            success=result.success,
                            message=result.message,
                            order_id=result.order_id,
                            error=result.raw_response if not result.success else None,
                        )
                        results.append(user_result)
                        
                    except Exception as exc:
                        console.print(f"[red]用户 {user.nickname} 预订失败: {exc}[/red]")
                        user_result = UserBookingResult(
                            nickname=user.nickname,
                            success=False,
                            message=f"异常: {exc}",
                            order_id=None,
                            error=str(exc),
                        )
                        results.append(user_result)
                
                # 打印汇总结果
                multi_user_manager.print_user_status(results)
                
        except Exception as e:
            print(f"[DEBUG] 预订任务异常: {e}")
            import traceback
            traceback.print_exc()
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
    auth_manager = AuthManager()

    stored_cookies, active_username = auth_manager.load_all_cookies()
    if stored_cookies:
        # 如果配置中没有用户，基于持久化信息创建一个临时用户
        if not getattr(CFG.AUTH, "users", None):
            from .models import UserAuth

            key = (
                active_username
                if active_username and active_username in stored_cookies
                else next(iter(stored_cookies.keys()))
            )
            record = stored_cookies[key]
            nickname = record.get("nickname") or (
                (record.get("username") or "默认用户").split("@")[0]
                if record.get("username")
                else "默认用户"
            )
            CFG.AUTH.users = [
                UserAuth(
                    nickname=nickname,
                    cookie=record["cookie"],
                    username=record.get("username"),
                )
            ]
            console.log(
                f"Loaded persisted cookie for {nickname} (expires {record['expires_at'].astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
            )
        else:
            logged_users: set[str] = set()
            for user in CFG.AUTH.users:
                record = None
                if user.username and user.username in stored_cookies:
                    record = stored_cookies[user.username]
                    logged_users.add(user.username)
                elif "__default__" in stored_cookies and not user.username:
                    record = stored_cookies["__default__"]

                if record:
                    user.cookie = record["cookie"]
                    label = user.nickname or user.username or "默认用户"
                    console.log(
                        f"Loaded persisted cookie for {label} (expires {record['expires_at'].astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
                    )

            # 如果存在其他持久化用户但当前配置未跟踪，尝试记录日志提醒
            for username, record in stored_cookies.items():
                if username == "__default__":
                    continue
                if username not in logged_users and username != active_username:
                    label = record.get("nickname") or username
                    console.log(f"Persisted cookie available for {label} (expires {record['expires_at'].astimezone().strftime('%Y-%m-%d %H:%M:%S')})")

    def api_factory() -> SportsAPI:
        return SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH, preset_targets=CFG.PRESET_TARGETS)

    global PRESETS  # pylint: disable=global-statement
    PRESETS = list(getattr(CFG, "PRESET_TARGETS", []))

    if args.command == "login":
        cmd_login(console, CFG, args, auth_manager)
        return

    if args.command == "logout":
        cmd_logout(console, auth_manager)
        return

    if args.command == "user-management":
        cmd_user_management(console, CFG)
        return

    if args.command in ("userinfo", "debug-login"):
        cookie_map, active_username = auth_manager.load_all_cookies()
        if not cookie_map:
            console.print("[yellow]尚未保存任何登录凭据[/yellow]")
            return

        from .models import UserAuth, AuthConfig

        for idx, (key, record) in enumerate(cookie_map.items(), start=1):
            label = record.get("nickname") or record.get("username") or "默认用户"
            if key == "__default__":
                label = f"{label} (默认)"
            if active_username and key == active_username:
                label = f"{label} [当前活跃]"

            expires_at = record.get("expires_at")
            if isinstance(expires_at, datetime):
                label = f"{label} (expires {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')})"

            temp_user = UserAuth(
                nickname=record.get("nickname") or label,
                cookie=record.get("cookie"),
                username=record.get("username"),
            )
            temp_auth = AuthConfig(users=[temp_user])
            temp_api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, temp_auth, preset_targets=CFG.PRESET_TARGETS)
            try:
                cmd_show_user_info(temp_api, console, header=f"用户 {idx}: {label}")
            finally:
                temp_api.close()
        return

    if args.command == "presets":
        cmd_list_presets(console)
        return
    
    if args.command == "list":
        cmd_list_venues_sports(console)
        return

    api = api_factory()
    try:
        if args.command == "list-users":
            cmd_list_users(api, console)
        elif args.command == "switch-user":
            cmd_switch_user(api, console, args.nickname)
        elif args.command == "validate-users":
            cmd_validate_users(api, console)
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
        elif args.command == "jobs":
            cmd_list_jobs(console)
        elif args.command == "jobs-cleanup":
            cmd_cleanup_jobs(console)
        elif args.command == "jobs-delete-all":
            cmd_delete_all_jobs(console, args.type, args.force)
        elif args.command == "job-start":
            cmd_start_job(console, args.job_id)
        elif args.command == "job-stop":
            cmd_stop_job(console, args.job_id)
        elif args.command == "job-delete":
            cmd_delete_job(console, args.job_id)
        elif args.command == "job-logs":
            cmd_show_job_logs(console, args.job_id, args.lines)
        elif args.command == "create-monitor":
            cmd_create_monitor_job(console, CFG.TARGET, CFG.MONITOR_PLAN, args)
        elif args.command == "create-schedule":
            cmd_create_schedule_job(console, CFG.TARGET, args)
        elif args.command == "create-keep-alive":
            cmd_create_keep_alive_job(console, args)
        elif args.command == "keep-alive":
            cmd_keep_alive(console, args)
        else:
            console.print("[yellow]Unknown command[/yellow]")
    finally:
        api.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SJTU Sports Automation CLI")
    sub = parser.add_subparsers(dest="command")

    schedule_defaults = None
    try:
        import config as CFG  # pylint: disable=import-outside-toplevel
        schedule_defaults = getattr(CFG, "SCHEDULE_PLAN", None)
    except Exception:  # pylint: disable=broad-except
        schedule_defaults = None

    default_hour = getattr(schedule_defaults, "hour", 12)
    default_minute = getattr(schedule_defaults, "minute", 0)
    default_second = getattr(schedule_defaults, "second", 0)
    default_date_offset = getattr(schedule_defaults, "date_offset", None)
    default_start_hours = getattr(schedule_defaults, "start_hours", None)
    default_start_hour = getattr(schedule_defaults, "start_hour", None)
    default_duration_hours = getattr(schedule_defaults, "duration_hours", None)
    default_no_start = not getattr(schedule_defaults, "auto_start", True) if schedule_defaults else False

    sub.add_parser("userinfo", help="Show account information for stored users", aliases=["debug-login"])
    
    # 多用户相关命令
    sub.add_parser("list-users", help="List all configured users")
    p_switch_user = sub.add_parser("switch-user", help="Switch to a specific user")
    p_switch_user.add_argument("nickname", type=str, help="User nickname to switch to")
    sub.add_parser("validate-users", help="Validate user configuration")
    
    p_discover = sub.add_parser("discover", help="Scan pages and JS files for candidate API endpoints")
    p_discover.add_argument("--base", type=str, help="Override BASE_URL when scanning")

    p_login = sub.add_parser("login", help="Execute credential login and persist session cookie")
    p_login.add_argument("--username", type=str, help="Account (fallback: SJABOT_USER env or config AUTH.username)")
    p_login.add_argument("--password", type=str, help="Password (fallback: SJABOT_PASS env)")
    p_login.add_argument("--no-ocr", action="store_true", help="Disable OCR and rely on manual input")
    p_login.add_argument("--no-prompt", action="store_true", help="Skip CLI prompt fallback (for external collaboration)")

    sub.add_parser("logout", help="Remove persisted cookies and re-authenticate next time")
    
    sub.add_parser("user-management", help="Manage saved users (add, delete, view)")

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
    p_monitor.add_argument("--pt", "--preferred-times", type=str, help="Preferred hours for booking (e.g., '15,16,17')")
    p_monitor.add_argument("--users", type=str, help="Comma-separated list of user nicknames to book for (e.g., 'user1,user2')")
    p_monitor.add_argument("--exclude-users", type=str, help="Comma-separated list of user nicknames to exclude")

    p_book = sub.add_parser("book-now", help="Run a single booking attempt")
    add_target_args(p_book)

    p_sched = sub.add_parser("schedule", help="Schedule a booking attempt every day at a fixed time")
    add_target_args(p_sched)
    p_sched.add_argument("--hour", type=int, default=default_hour)
    p_sched.add_argument("--minute", type=int, default=default_minute)
    p_sched.add_argument("--second", type=int, default=default_second)
    p_sched.add_argument(
        "--start-hours",
        type=str,
        help="以逗号分隔的开始小时列表，例如 '18,19'",
    )
    if default_date_offset is not None:
        p_sched.set_defaults(date_offset=default_date_offset)
    if default_start_hour is not None:
        p_sched.set_defaults(start_hour=default_start_hour)
    if default_start_hours:
        p_sched.set_defaults(start_hours=",".join(str(h) for h in default_start_hours))
    if default_duration_hours is not None:
        p_sched.set_defaults(duration_hours=default_duration_hours)

    p_order = sub.add_parser("order", help="Place an order for a specific time slot")
    p_order.add_argument("--preset", type=int, required=True, help="Preset index from config.PRESET_TARGETS")
    p_order.add_argument("--date", type=str, required=True, help="Date: 0-8 (offset) or YYYY-MM-DD format")
    p_order.add_argument("--start-time", "--st", type=str, default="21", help="Start time: 0-23 (hour) or HH:MM format")
    p_order.add_argument("--end-time", type=str, help="End time: 0-23 (hour) or HH:MM format (auto: start+1h if not provided)")
    p_order.add_argument("--users", type=str, help="Comma-separated list of user nicknames to book for (e.g., 'user1,user2')")
    p_order.add_argument("--exclude-users", type=str, help="Comma-separated list of user nicknames to exclude")

    # 任务管理命令
    sub.add_parser("jobs", help="List all background jobs")
    sub.add_parser("jobs-cleanup", help="Clean up dead jobs")
    
    p_job_start = sub.add_parser("job-start", help="Start a background job")
    p_job_start.add_argument("job_id", type=str, help="Job ID to start")
    
    p_job_stop = sub.add_parser("job-stop", help="Stop a background job")
    p_job_stop.add_argument("job_id", type=str, help="Job ID to stop")
    
    p_job_delete = sub.add_parser("job-delete", help="Delete a background job")
    p_job_delete.add_argument("job_id", type=str, help="Job ID to delete")
    
    p_jobs_delete_all = sub.add_parser("jobs-delete-all", help="Delete all background jobs")
    p_jobs_delete_all.add_argument("--type", type=str, choices=["monitor", "schedule", "auto_booking", "keep_alive"], help="Delete only jobs of specific type")
    p_jobs_delete_all.add_argument("--force", action="store_true", help="Force delete without confirmation")
    
    p_job_logs = sub.add_parser("job-logs", help="Show job logs")
    p_job_logs.add_argument("job_id", type=str, help="Job ID to show logs for")
    p_job_logs.add_argument("--lines", type=int, default=500, help="Number of log lines to show")
    
    # 创建任务命令
    p_create_monitor = sub.add_parser("create-monitor", help="Create a monitor job")
    add_target_args(p_create_monitor)
    p_create_monitor.add_argument("--name", type=str, required=True, help="Job name")
    p_create_monitor.add_argument("--interval", type=int, help="Polling interval in seconds")
    p_create_monitor.add_argument("--auto-book", action="store_true", help="Attempt booking automatically when possible")
    p_create_monitor.add_argument("--pt", "--preferred-times", type=str, help="Preferred hours for booking (e.g., '15,16,17')")
    p_create_monitor.add_argument("--preferred-days", type=str, help="Preferred days for monitoring (e.g., '0,1,2,3,4,5,6,7,8')")
    p_create_monitor.add_argument("--users", type=str, help="Comma-separated list of user nicknames to book for")
    p_create_monitor.add_argument("--exclude-users", type=str, help="Comma-separated list of user nicknames to exclude")
    p_create_monitor.add_argument("--no-start", action="store_true", help="Create job but don't start it")
    
    p_create_schedule = sub.add_parser("create-schedule", help="Create a schedule job")
    add_target_args(p_create_schedule)
    p_create_schedule.add_argument("--name", type=str, required=True, help="Job name")
    p_create_schedule.add_argument("--hour", type=int, default=default_hour, help="Schedule hour")
    p_create_schedule.add_argument("--minute", type=int, default=default_minute, help="Schedule minute")
    p_create_schedule.add_argument("--second", type=int, default=default_second, help="Schedule second")
    p_create_schedule.add_argument(
        "--start-hours",
        type=str,
        help="Comma separated start hours list (e.g., '18,19')",
    )
    p_create_schedule.add_argument("--users", type=str, help="Comma-separated list of user nicknames to book for")
    p_create_schedule.add_argument("--exclude-users", type=str, help="Comma-separated list of user nicknames to exclude")
    p_create_schedule.add_argument("--no-start", action="store_true", help="Create job but don't start it")
    if default_date_offset is not None:
        p_create_schedule.set_defaults(date_offset=default_date_offset)
    if default_start_hour is not None:
        p_create_schedule.set_defaults(start_hour=default_start_hour)
    if default_start_hours:
        p_create_schedule.set_defaults(start_hours=",".join(str(h) for h in default_start_hours))
    if default_duration_hours is not None:
        p_create_schedule.set_defaults(duration_hours=default_duration_hours)
    p_create_schedule.set_defaults(no_start=default_no_start)
    
    # Keep-Alive命令
    p_create_keep_alive = sub.add_parser("create-keep-alive", help="Create a keep-alive job")
    p_create_keep_alive.add_argument("--name", type=str, required=True, help="Job name")
    p_create_keep_alive.add_argument("--interval", type=int, default=15, help="Keep-alive interval in minutes")
    p_create_keep_alive.add_argument("--no-start", action="store_true", help="Create job but don't start it")
    
    p_keep_alive = sub.add_parser("keep-alive", help="Manual keep-alive operations")
    p_keep_alive.add_argument("action", choices=["refresh", "status"], help="Keep-alive action")
    p_keep_alive.add_argument("--user", type=str, help="Specific user to refresh (optional)")

    return parser


# =============================================================================
# 任务管理命令
# =============================================================================

def cmd_list_jobs(console: Console) -> None:
    """列出所有任务"""
    from .job_manager import get_job_manager
    
    job_manager = get_job_manager()
    job_manager.show_jobs_table()


def cmd_cleanup_jobs(console: Console) -> None:
    """清理已死亡的任务"""
    from .job_manager import get_job_manager
    
    job_manager = get_job_manager()
    cleaned = job_manager.cleanup_dead_jobs()
    
    if cleaned == 0:
        console.print("[green]✅ 没有需要清理的任务[/green]")
    else:
        console.print(f"[green]✅ 已清理 {cleaned} 个已死亡的任务[/green]")


def cmd_delete_all_jobs(console: Console, job_type: Optional[str] = None, force: bool = False) -> None:
    """删除所有任务"""
    from .job_manager import get_job_manager, JobType
    
    job_manager = get_job_manager()
    
    # 转换任务类型
    job_type_enum = None
    if job_type:
        try:
            job_type_enum = JobType(job_type)
        except ValueError:
            console.print(f"[red]❌ 无效的任务类型: {job_type}[/red]")
            return
    
    deleted_count = job_manager.delete_all_jobs(job_type_enum, force)
    
    if deleted_count == 0:
        console.print("[yellow]⚠️  没有任务被删除[/yellow]")
    else:
        console.print(f"[green]✅ 成功删除 {deleted_count} 个任务[/green]")


def cmd_start_job(console: Console, job_id: str) -> None:
    """启动任务"""
    from .job_manager import get_job_manager
    
    job_manager = get_job_manager()
    success = job_manager.start_job(job_id)
    
    if success:
        console.print(f"[green]✅ 任务 {job_id} 已启动[/green]")
    else:
        console.print(f"[red]❌ 启动任务 {job_id} 失败[/red]")


def cmd_stop_job(console: Console, job_id: str) -> None:
    """停止任务"""
    from .job_manager import get_job_manager
    
    job_manager = get_job_manager()
    success = job_manager.stop_job(job_id)
    
    if success:
        console.print(f"[green]✅ 任务 {job_id} 已停止[/green]")
    else:
        console.print(f"[red]❌ 停止任务 {job_id} 失败[/red]")


def cmd_delete_job(console: Console, job_id: str) -> None:
    """删除任务"""
    from .job_manager import get_job_manager
    
    job_manager = get_job_manager()
    success = job_manager.delete_job(job_id)
    
    if success:
        console.print(f"[green]✅ 任务 {job_id} 已删除[/green]")
    else:
        console.print(f"[red]❌ 删除任务 {job_id} 失败[/red]")


def cmd_show_job_logs(console: Console, job_id: str, lines: int) -> None:
    """显示任务日志"""
    from .job_manager import get_job_manager
    
    job_manager = get_job_manager()
    logs = job_manager.get_job_logs(job_id, lines)
    
    if not logs:
        console.print(f"[yellow]⚠️  任务 {job_id} 没有日志[/yellow]")
        return
    
    console.print(f"[blue]📋 任务 {job_id} 的最近 {lines} 行日志：[/blue]")
    console.print("-" * 60)
    for log in logs:
        console.print(log)
    console.print("-" * 60)


def cmd_create_monitor_job(console: Console, base_target: BookingTarget, plan: MonitorPlan, args) -> None:
    """创建监控任务"""
    from .job_manager import get_job_manager, JobType
    
    # 应用目标覆盖
    target = apply_target_overrides(base_target, args)
    
    # 创建监控计划
    monitor_plan = dataclasses.replace(plan)
    if args.interval:
        monitor_plan.interval_seconds = args.interval
    if args.auto_book is not None:
        monitor_plan.auto_book = args.auto_book
    
    # 处理多用户参数
    if hasattr(args, 'users') and args.users:
        target.target_users = list(dict.fromkeys(nickname.strip() for nickname in args.users.split(',') if nickname.strip()))
        console.print(f"[green]指定预订用户: {target.target_users}[/green]")

    if hasattr(args, 'exclude_users') and args.exclude_users:
        target.exclude_users = list(dict.fromkeys(nickname.strip() for nickname in args.exclude_users.split(',') if nickname.strip()))
        console.print(f"[green]排除用户: {target.exclude_users}[/green]")
    
    # 处理优先时间段设置
    if hasattr(args, 'pt') and args.pt:
        try:
            preferred_hours = [int(h.strip()) for h in args.pt.split(',')]
            monitor_plan.preferred_hours = preferred_hours
            console.print(f"[green]设置优先时间段: {preferred_hours}[/green]")
        except ValueError:
            console.print(f"[red]无效的优先时间段格式: {args.pt}，应为 '15,16,17' 格式[/red]")
            return
    
    # 处理优先天数设置
    if hasattr(args, 'preferred_days') and args.preferred_days:
        try:
            preferred_days = [int(d.strip()) for d in args.preferred_days.split(',')]
            monitor_plan.preferred_days = preferred_days
            console.print(f"[green]设置优先天数: {preferred_days}[/green]")
        except ValueError:
            console.print(f"[red]无效的优先天数格式: {args.preferred_days}，应为 '0,1,2,3,4,5,6,7,8' 格式[/red]")
            return
    
    # 如果没有指定优先天数，使用默认值（0-8）
    if not monitor_plan.preferred_days:
        monitor_plan.preferred_days = list(range(9))  # 0-8
        console.print(f"[green]使用默认优先天数: {monitor_plan.preferred_days}[/green]")
    
    # 设置目标的日期偏移为优先天数
    target.date_offset = monitor_plan.preferred_days
    target.use_all_dates = False  # 确保不使用 use_all_dates
    console.print(f"[green]设置监控日期范围: {target.date_offset}[/green]")
    
    # 创建任务配置
    config = {
        'target': dataclasses.asdict(target),
        'plan': dataclasses.asdict(monitor_plan)
    }
    
    # 创建任务
    job_manager = get_job_manager()
    job_id = job_manager.create_job(
        job_type=JobType.MONITOR,
        name=args.name,
        config=config,
        auto_start=not args.no_start
    )
    
    console.print(f"[green]✅ 监控任务已创建: {args.name} (ID: {job_id})[/green]")
    if not args.no_start:
        console.print(f"[green]🚀 任务已自动启动[/green]")


def cmd_create_schedule_job(console: Console, base_target: BookingTarget, args) -> None:
    """创建定时任务"""
    from .job_manager import get_job_manager, JobType
    
    try:
        import config as CFG  # pylint: disable=import-outside-toplevel
        schedule_defaults = getattr(CFG, "SCHEDULE_PLAN", None)
    except Exception:  # pylint: disable=broad-except
        schedule_defaults = None
    
    # 应用目标覆盖
    target = apply_target_overrides(base_target, args)
    
    # 处理多用户参数
    if hasattr(args, 'users') and args.users:
        target.target_users = [nickname.strip() for nickname in args.users.split(',')]
        console.print(f"[green]指定预订用户: {target.target_users}[/green]")
    
    if hasattr(args, 'exclude_users') and args.exclude_users:
        target.exclude_users = [nickname.strip() for nickname in args.exclude_users.split(',')]
        console.print(f"[green]排除用户: {target.exclude_users}[/green]")
    
    hour = getattr(args, 'hour', None)
    if hour is None:
        hour = getattr(schedule_defaults, "hour", 12)
    minute = getattr(args, 'minute', None)
    if minute is None:
        minute = getattr(schedule_defaults, "minute", 0)
    second = getattr(args, 'second', None)
    if second is None:
        second = getattr(schedule_defaults, "second", 0)

    date_offset = getattr(args, 'date_offset', None)
    if date_offset is None:
        date_offset = getattr(schedule_defaults, "date_offset", 1)

    start_hours = parse_start_hours_arg(getattr(args, 'start_hours', None))
    if not start_hours and getattr(args, 'start_hour', None) is not None:
        try:
            start_hours = [int(getattr(args, 'start_hour'))]
        except (TypeError, ValueError):
            start_hours = []
    if not start_hours and schedule_defaults and getattr(schedule_defaults, "start_hours", None):
        start_hours = list(getattr(schedule_defaults, "start_hours"))
    if not start_hours and getattr(schedule_defaults, "start_hour", None) is not None:
        start_hours = [int(getattr(schedule_defaults, "start_hour"))]
    if not start_hours:
        start_hours = [target.start_hour or 18]

    start_hour_primary = start_hours[0]
    target.start_hour = start_hour_primary

    duration_hours = getattr(args, 'duration_hours', None)
    if duration_hours is None:
        duration_hours = getattr(schedule_defaults, "duration_hours", target.duration_hours)
    if duration_hours is None:
        duration_hours = target.duration_hours or 1

    # 创建任务配置
    config = {
        'target': dataclasses.asdict(target),
        'schedule': {
            'hour': hour,
            'minute': minute,
            'second': second,
            'preset': getattr(args, 'preset', None),
            'date_offset': date_offset,
            'start_hour': start_hour_primary,
            'start_hours': start_hours,
            'duration_hours': duration_hours,
        }
    }
    
    # 创建任务
    job_manager = get_job_manager()
    job_id = job_manager.create_job(
        job_type=JobType.SCHEDULE,
        name=args.name,
        config=config,
        auto_start=not args.no_start
    )
    
    console.print(f"[green]✅ 定时任务已创建: {args.name} (ID: {job_id})[/green]")
    console.print(f"[blue]⏰ 计划时间: {hour:02d}:{minute:02d}:{second:02d}[/blue]")
    console.print(f"[blue]🕒 预订时段: {', '.join(f'{h:02d}:00' for h in start_hours)}[/blue]")
    if not args.no_start:
        console.print(f"[green]🚀 任务已自动启动[/green]")


def cmd_create_keep_alive_job(console: Console, args) -> None:
    """创建Keep-Alive任务"""
    from .job_manager import get_job_manager, JobType
    
    interval_minutes = max(1, args.interval)
    
    # 创建任务配置
    config = {
        'interval_seconds': interval_minutes * 60
    }
    
    # 创建任务
    job_manager = get_job_manager()
    job_id = job_manager.create_job(
        job_type=JobType.KEEP_ALIVE,
        name=args.name,
        config=config,
        auto_start=not args.no_start
    )
    
    console.print(f"[green]✅ Keep-Alive任务已创建: {args.name} (ID: {job_id})[/green]")
    console.print(f"[blue]⏰ 刷新间隔: {interval_minutes}分钟[/blue]")
    if not args.no_start:
        console.print(f"[green]🚀 任务已自动启动[/green]")


def cmd_keep_alive(console: Console, args) -> None:
    """Keep-Alive操作"""
    import asyncio
    from .keep_alive import KeepAliveResult, run_keep_alive_for_user, run_keep_alive_once
    
    if args.action == "refresh":
        if args.user:
            # 刷新特定用户
            console.print(f"[blue]🔄 刷新用户 {args.user} 的Cookie...[/blue]")
            result: KeepAliveResult = asyncio.run(run_keep_alive_for_user(args.user))
            display_name = result.nickname or result.username or args.user
            if result.success:
                console.print(f"[green]✅ {display_name}: {result.message}[/green]")
            else:
                console.print(f"[red]❌ {display_name}: {result.message}[/red]")
        else:
            # 刷新所有用户
            console.print("[blue]🔄 刷新所有用户的Cookie...[/blue]")
            results = asyncio.run(run_keep_alive_once())
            
            success_count = sum(1 for r in results if r.success)
            total_count = len(results)
            
            console.print(f"[green]✅ 刷新完成: {success_count}/{total_count} 成功[/green]")
            
            for result in results:
                display_name = result.nickname or result.username or "未命名用户"
                if result.success:
                    console.print(f"[green]  ✅ {display_name}: {result.message}[/green]")
                else:
                    console.print(f"[red]  ❌ {display_name}: {result.message}[/red]")
    
    elif args.action == "status":
        # 显示Keep-Alive状态
        from .job_manager import get_job_manager
        job_manager = get_job_manager()
        
        # 查找Keep-Alive任务
        keep_alive_jobs = [job for job in job_manager.jobs.values() if job.job_type.value == "keep_alive"]
        
        if not keep_alive_jobs:
            console.print("[yellow]⚠️  没有找到Keep-Alive任务[/yellow]")
            return
            
        console.print("[blue]📋 Keep-Alive任务状态:[/blue]")
        for job in keep_alive_jobs:
            status_color = "green" if job.status.value == "running" else "yellow"
            console.print(f"  [{status_color}]{job.name}[/{status_color}] (ID: {job.job_id}) - {job.status.value}")
