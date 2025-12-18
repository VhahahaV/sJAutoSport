"""
监控插件
支持启动/停止监控、查看状态
"""

import re
from datetime import datetime
from typing import Optional

from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg, RegexGroup

# 导入服务层
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking.service import start_monitor, stop_monitor, monitor_status
from bot import services as bot_services

# 命令处理器
start_monitor_cmd = on_command("开始监控", aliases={"monitor", "监控"}, priority=5)
stop_monitor_cmd = on_command("停止监控", aliases={"stop", "停止"}, priority=5)
monitor_status_cmd = on_command("监控状态", aliases={"status", "状态"}, priority=5)
monitor_preset_cmd = on_regex(r"监控\s+preset=(\d+)", priority=5)


@start_monitor_cmd.handle()
async def handle_start_monitor(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理开始监控命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        logger.info(f"收到开始监控命令: {args_str}")
        
        # 解析参数
        params = parse_monitor_args(args_str)
        
        if not params.get("preset") and not params.get("venue_keyword"):
            await start_monitor_cmd.finish("❌ 请指定场馆，使用 preset=数字 或 venue=场馆名")
        
        # 生成监控ID
        monitor_id = f"monitor_{int(datetime.now().timestamp())}"
        
        # 调用服务层
        target_users = params.get("target_users")
        exclude_users = params.get("exclude_users")

        base_target = bot_services.build_target(None, target_users, exclude_users)

        result = await start_monitor(
            monitor_id=monitor_id,
            preset=params.get("preset"),
            venue_id=params.get("venue_id"),
            field_type_id=params.get("field_type_id"),
            date=params.get("date"),
            start_hour=params.get("start_hour"),
            interval_seconds=params.get("interval_seconds", 240),
            auto_book=params.get("auto_book", False),
            long_running=params.get("long_running", False),
            base_target=base_target,
            target_users=target_users,
            exclude_users=exclude_users,
        )
        
        if result["success"]:
            monitor_info = result["monitor_info"]
            response = f"✅ 监控已启动！\n"
            response += f"🆔 监控ID: {monitor_id}\n"
            response += f"🏟️ 场馆: 预设{params.get('preset', 'N/A')}\n"
            response += f"📅 目标日期: {params.get('date', '所有可用日期')}\n"
            response += f"🕐 目标时间: {params.get('start_hour', '任意时间')}\n"
            response += f"⏱️ 检查间隔: {params.get('interval_seconds', 240)}秒\n"
            response += f"🤖 自动预订: {'是' if params.get('auto_book', False) else '否'}\n"
            response += f"♾️ 长期任务: {'是' if params.get('long_running', False) else '否'}\n"
            if target_users:
                response += f"👥 指定用户: {', '.join(target_users)}\n"
            if exclude_users:
                response += f"🚫 排除用户: {', '.join(exclude_users)}\n"
            response += f"📊 状态: {monitor_info['status']}\n"
            response += f"🕐 启动时间: {monitor_info['start_time']}"
            await start_monitor_cmd.finish(response)
        else:
            await start_monitor_cmd.finish(f"❌ 启动监控失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"开始监控出错: {e}")
        await start_monitor_cmd.finish(f"❌ 开始监控出错: {str(e)}")


@monitor_preset_cmd.handle()
async def handle_monitor_preset(bot: Bot, event: MessageEvent, groups: tuple = RegexGroup()):
    """处理 preset 样式监控命令"""
    try:
        preset_id = int(groups[0])
        logger.info(f"收到预设监控命令: preset={preset_id}")
        
        # 生成监控ID
        monitor_id = f"monitor_{int(datetime.now().timestamp())}"
        
        # 调用服务层
        result = await start_monitor(
            monitor_id=monitor_id,
            preset=preset_id,
            interval_seconds=240,
            auto_book=False,
            base_target=bot_services.build_target(None, None, None),
        )
        
        if result["success"]:
            monitor_info = result["monitor_info"]
            response = f"✅ 监控已启动！\n"
            response += f"🆔 监控ID: {monitor_id}\n"
            response += f"🏟️ 预设场馆: {preset_id}\n"
            response += f"⏱️ 检查间隔: 240秒\n"
            response += f"🤖 自动预订: 否\n"
            response += f"📊 状态: {monitor_info['status']}\n"
            response += f"🕐 启动时间: {monitor_info['start_time']}"
            await monitor_preset_cmd.finish(response)
        else:
            await monitor_preset_cmd.finish(f"❌ 启动监控失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"预设监控出错: {e}")
        await monitor_preset_cmd.finish(f"❌ 预设监控出错: {str(e)}")


@stop_monitor_cmd.handle()
async def handle_stop_monitor(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理停止监控命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        if not args_str:
            await stop_monitor_cmd.finish("❌ 请指定要停止的监控ID，或使用 'all' 停止所有监控")
        
        if args_str.lower() == "all":
            # 停止所有监控
            result = await monitor_status()
            if result["success"]:
                monitors = result["monitors"]
                stopped_count = 0
                for monitor in monitors:
                    stop_result = await stop_monitor(monitor["id"])
                    if stop_result["success"]:
                        stopped_count += 1
                
                await stop_monitor_cmd.finish(f"✅ 已停止 {stopped_count} 个监控任务")
            else:
                await stop_monitor_cmd.finish("❌ 获取监控列表失败")
        else:
            # 停止指定监控
            monitor_id = args_str.strip()
            logger.info(f"收到停止监控命令: {monitor_id}")
            
            result = await stop_monitor(monitor_id)
            
            if result["success"]:
                await stop_monitor_cmd.finish(f"✅ 监控 {monitor_id} 已停止")
            else:
                await stop_monitor_cmd.finish(f"❌ 停止监控失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"停止监控出错: {e}")
        await stop_monitor_cmd.finish(f"❌ 停止监控出错: {str(e)}")


@monitor_status_cmd.handle()
async def handle_monitor_status(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理监控状态命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        logger.info(f"收到监控状态命令: {args_str}")
        
        if args_str:
            # 查询指定监控状态
            monitor_id = args_str.strip()
            result = await monitor_status(monitor_id)
            
            if result["success"]:
                monitor_info = result["monitor_info"]
                response = format_monitor_status(monitor_info)
                await monitor_status_cmd.finish(response)
            else:
                await monitor_status_cmd.finish(f"❌ 获取监控状态失败: {result.get('message', '未知错误')}")
        else:
            # 查询所有监控状态
            result = await monitor_status()
            
            if result["success"]:
                monitors = result["monitors"]
                if not monitors:
                    await monitor_status_cmd.finish("📊 当前没有活跃的监控任务")
                
                response = f"📊 监控状态总览 (共{len(monitors)}个):\n\n"
                
                for monitor in monitors:
                    response += format_monitor_status(monitor, brief=True)
                    response += "\n"
                
                await monitor_status_cmd.finish(response)
            else:
                await monitor_status_cmd.finish(f"❌ 获取监控状态失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"获取监控状态出错: {e}")
        await monitor_status_cmd.finish(f"❌ 获取监控状态出错: {str(e)}")


def parse_monitor_args(args_str: str) -> dict:
    """解析监控参数"""
    params = {}
    
    if not args_str:
        return params
    
    # 解析各种参数格式
    patterns = [
        (r"preset=(\d+)", "preset"),
        (r"venue=([^\s]+)", "venue_keyword"),
        (r"sport=([^\s]+)", "field_type_keyword"),
        (r"date=(\d+)", "date"),
        (r"time=(\d+)", "start_hour"),
        (r"start=(\d+)", "start_hour"),
        (r"interval=(\d+)", "interval_seconds"),
        (r"auto", "auto_book"),
        (r"long(?:_?term)?=(true|false|1|0)", "long_running"),
        (r"\blong(?:_?term)?\b", "long_running"),
        (r"长期", "long_running"),
        (r"users=([^\s]+)", "target_users"),
        (r"exclude=([^\s]+)", "exclude_users"),
    ]

    int_fields = {"preset", "date", "start_hour", "interval_seconds"}
    list_fields = {"target_users", "exclude_users"}
    bool_fields = {"auto_book", "long_running"}
    
    for pattern, param_name in patterns:
        match = re.search(pattern, args_str, flags=re.IGNORECASE)
        if match:
            groups = match.groups()
            value = groups[0] if groups else None

            if param_name in bool_fields:
                if value is None:
                    params[param_name] = True
                else:
                    normalized = str(value).strip().lower()
                    params[param_name] = normalized in {"1", "true", "yes", "on"}
                continue

            if value is None:
                continue

            if param_name in int_fields:
                try:
                    params[param_name] = int(value)
                except ValueError:
                    continue
            elif param_name in list_fields:
                params[param_name] = [item.strip() for item in value.split(',') if item.strip()]
            else:
                params[param_name] = value

    return params


def format_monitor_status(monitor_info: dict, brief: bool = False) -> str:
    """格式化监控状态"""
    base_target = monitor_info.get("base_target")
    if base_target and isinstance(base_target, dict):
        target_users = base_target.get("target_users", [])
        exclude_users = base_target.get("exclude_users", [])
    else:
        target_users = getattr(base_target, "target_users", []) if base_target else []
        exclude_users = getattr(base_target, "exclude_users", []) if base_target else []

    if brief:
        response = f"🆔 {monitor_info['id']}\n"
        response += f"📊 状态: {monitor_info['status']}\n"
        response += f"🏟️ 场馆: 预设{monitor_info.get('preset', 'N/A')}\n"
        response += f"⏱️ 间隔: {monitor_info.get('interval_seconds', 240)}秒\n"
        response += f"🤖 自动预订: {'是' if monitor_info.get('auto_book', False) else '否'}\n"
        response += f"♾️ 长期任务: {'是' if monitor_info.get('long_running') else '否'}\n"
        if target_users:
            response += f"👥 用户: {', '.join(target_users)}\n"
        if exclude_users:
            response += f"🚫 排除: {', '.join(exclude_users)}\n"
        response += f"🕐 启动时间: {monitor_info.get('start_time', 'N/A')}\n"
        response += f"🔍 最后检查: {monitor_info.get('last_check', 'N/A')}\n"
        response += f"📋 找到时间段: {len(monitor_info.get('found_slots', []))}个\n"
        response += f"🔄 预订尝试: {monitor_info.get('booking_attempts', 0)}次\n"
        response += f"✅ 成功预订: {monitor_info.get('successful_bookings', 0)}次"
        return response

    response = f"📊 监控详细信息\n\n"
    response += f"🆔 监控ID: {monitor_info['id']}\n"
    response += f"📊 状态: {monitor_info['status']}\n"
    response += f"🏟️ 场馆: 预设{monitor_info.get('preset', 'N/A')}\n"
    response += f"📅 目标日期: {monitor_info.get('date', '所有可用日期')}\n"
    response += f"🕐 目标时间: {monitor_info.get('start_hour', '任意时间')}\n"
    response += f"⏱️ 检查间隔: {monitor_info.get('interval_seconds', 240)}秒\n"
    response += f"🤖 自动预订: {'是' if monitor_info.get('auto_book', False) else '否'}\n"
    response += f"♾️ 长期任务: {'是' if monitor_info.get('long_running') else '否'}\n"
    if target_users:
        response += f"👥 指定用户: {', '.join(target_users)}\n"
    if exclude_users:
        response += f"🚫 排除用户: {', '.join(exclude_users)}\n"
    response += f"🕐 启动时间: {monitor_info.get('start_time', 'N/A')}\n"
    response += f"🔍 最后检查: {monitor_info.get('last_check', 'N/A')}\n"
    response += f"📋 找到时间段: {len(monitor_info.get('found_slots', []))}个\n"
    response += f"🔄 预订尝试: {monitor_info.get('booking_attempts', 0)}次\n"
    response += f"✅ 成功预订: {monitor_info.get('successful_bookings', 0)}次\n"
    if monitor_info.get("last_cycle_completed_at"):
        response += f"🔁 上次完成: {monitor_info['last_cycle_completed_at']}\n"

    if monitor_info.get('last_error'):
        response += f"❌ 最后错误: {monitor_info['last_error']}\n"

    if monitor_info.get('last_booking_error'):
        response += f"❌ 最后预订错误: {monitor_info['last_booking_error']}\n"

    return response
