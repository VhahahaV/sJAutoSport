"""
自动抢票插件
每天中午12点准时开始抢七天后的场地
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg, RegexGroup

# 导入服务层
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking.service import (
    start_auto_booking, stop_auto_booking, get_auto_booking_status,
    update_auto_booking_targets, get_auto_booking_results, execute_manual_booking
)

# 命令处理器
auto_booking_start_cmd = on_command("启动抢票", aliases={"start_auto", "开始抢票"}, priority=5)
auto_booking_stop_cmd = on_command("停止抢票", aliases={"stop_auto", "停止自动抢票"}, priority=5)
auto_booking_status_cmd = on_command("抢票状态", aliases={"auto_status", "抢票情况"}, priority=5)
auto_booking_config_cmd = on_command("抢票配置", aliases={"auto_config", "配置抢票"}, priority=5)
auto_booking_results_cmd = on_command("抢票记录", aliases={"auto_results", "抢票历史"}, priority=5)
auto_booking_test_cmd = on_command("测试抢票", aliases={"test_auto", "抢票测试"}, priority=5)


@auto_booking_start_cmd.handle()
async def handle_start_auto_booking(bot: Bot, event: MessageEvent):
    """处理启动自动抢票命令"""
    try:
        logger.info("收到启动自动抢票命令")
        
        result = await start_auto_booking()
        
        if result["success"]:
            response = f"✅ 自动抢票系统已启动！\n"
            response += f"🕐 抢票时间: 每天中午12:00:00\n"
            response += f"📅 目标日期: 7天后的场地\n"
            response += f"🎯 系统状态: 运行中\n"
            response += f"💡 使用 '抢票状态' 查看详细信息"
            await auto_booking_start_cmd.finish(response)
        else:
            await auto_booking_start_cmd.finish(f"❌ 启动失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"启动自动抢票出错: {e}")
        await auto_booking_start_cmd.finish(f"❌ 启动自动抢票出错: {str(e)}")


@auto_booking_stop_cmd.handle()
async def handle_stop_auto_booking(bot: Bot, event: MessageEvent):
    """处理停止自动抢票命令"""
    try:
        logger.info("收到停止自动抢票命令")
        
        result = await stop_auto_booking()
        
        if result["success"]:
            await auto_booking_stop_cmd.finish("✅ 自动抢票系统已停止")
        else:
            await auto_booking_stop_cmd.finish(f"❌ 停止失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"停止自动抢票出错: {e}")
        await auto_booking_stop_cmd.finish(f"❌ 停止自动抢票出错: {str(e)}")


@auto_booking_status_cmd.handle()
async def handle_auto_booking_status(bot: Bot, event: MessageEvent):
    """处理抢票状态命令"""
    try:
        logger.info("收到抢票状态命令")
        
        result = await get_auto_booking_status()
        
        if result.get("success", True):  # 默认成功
            status = result
            response = f"🎯 自动抢票系统状态\n\n"
            response += f"🔄 运行状态: {'运行中' if status.get('is_running', False) else '已停止'}\n"
            response += f"📊 目标数量: {status.get('targets_count', 0)}个\n"
            response += f"✅ 启用目标: {status.get('enabled_targets', 0)}个\n"
            response += f"🕐 下次抢票: 明天12:00:00\n"
            response += f"📅 目标日期: {(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')}\n\n"
            
            # 显示最近结果
            last_results = status.get('last_results', [])
            if last_results:
                response += f"📋 最近结果:\n"
                for i, result in enumerate(last_results[-3:], 1):
                    status_icon = "✅" if result.get("success", False) else "❌"
                    response += f"  {i}. {status_icon} {result.get('target', {}).get('description', '未知')}\n"
                    if result.get("success"):
                        response += f"     🎫 订单: {result.get('order_id', 'N/A')}\n"
                    else:
                        response += f"     📝 原因: {result.get('message', 'N/A')}\n"
            else:
                response += f"📋 最近结果: 暂无\n"
            
            response += f"\n💡 使用 '抢票记录' 查看历史记录"
            await auto_booking_status_cmd.finish(response)
        else:
            await auto_booking_status_cmd.finish(f"❌ 获取状态失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"获取抢票状态出错: {e}")
        await auto_booking_status_cmd.finish(f"❌ 获取抢票状态出错: {str(e)}")


@auto_booking_config_cmd.handle()
async def handle_auto_booking_config(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理抢票配置命令"""
    try:
        args_str = str(args).strip()
        logger.info(f"收到抢票配置命令: {args_str}")
        
        if not args_str:
            # 显示当前配置
            result = await get_auto_booking_status()
            if result.get("success", True):
                response = f"🎯 当前抢票配置\n\n"
                response += f"📊 目标数量: {result.get('targets_count', 0)}个\n"
                response += f"✅ 启用目标: {result.get('enabled_targets', 0)}个\n\n"
                response += f"💡 配置说明:\n"
                response += f"• 系统每天12:00:00准时开始抢票\n"
                response += f"• 目标为7天后的场地\n"
                response += f"• 按优先级顺序尝试预订\n"
                response += f"• 每个目标最多尝试3次\n\n"
                response += f"🔧 默认配置:\n"
                response += f"1. 南洋北苑健身房 (优先级1, 18-21点)\n"
                response += f"2. 气膜体育中心羽毛球 (优先级2, 18-20点)\n"
                response += f"3. 霍英东体育中心羽毛球 (优先级3, 18-20点)\n\n"
                response += f"💡 使用 '测试抢票' 进行测试"
                await auto_booking_config_cmd.finish(response)
            else:
                await auto_booking_config_cmd.finish(f"❌ 获取配置失败: {result.get('message', '未知错误')}")
        else:
            # 解析配置参数
            config = parse_config_args(args_str)
            if config:
                result = await update_auto_booking_targets([config])
                if result["success"]:
                    await auto_booking_config_cmd.finish(f"✅ 抢票配置已更新")
                else:
                    await auto_booking_config_cmd.finish(f"❌ 更新配置失败: {result.get('message', '未知错误')}")
            else:
                await auto_booking_config_cmd.finish("❌ 配置参数格式错误")
            
    except Exception as e:
        logger.error(f"处理抢票配置出错: {e}")
        await auto_booking_config_cmd.finish(f"❌ 处理抢票配置出错: {str(e)}")


@auto_booking_results_cmd.handle()
async def handle_auto_booking_results(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理抢票记录命令"""
    try:
        args_str = str(args).strip()
        limit = 5
        if args_str.isdigit():
            limit = int(args_str)
        
        logger.info(f"收到抢票记录命令: limit={limit}")
        
        result = await get_auto_booking_results(limit)
        
        if result["success"]:
            results = result["results"]
            if not results:
                await auto_booking_results_cmd.finish("📋 暂无抢票记录")
                return
            
            response = f"📋 抢票历史记录 (最近{len(results)}条)\n\n"
            
            for i, record in enumerate(results, 1):
                response += f"📅 {record.get('target_date', 'N/A')}\n"
                response += f"🕐 执行时间: {record.get('execution_time', 'N/A')}\n"
                response += f"🎯 目标数量: {record.get('total_targets', 0)}个\n"
                response += f"✅ 成功预订: {record.get('successful_bookings', 0)}个\n"
                
                # 显示详细结果
                details = record.get('results', [])
                if details:
                    response += f"📊 详细结果:\n"
                    for detail in details:
                        status_icon = "✅" if detail.get("success", False) else "❌"
                        target = detail.get("target", {})
                        response += f"  {status_icon} {target.get('description', '未知')}\n"
                        if detail.get("success"):
                            response += f"    🎫 订单: {detail.get('order_id', 'N/A')}\n"
                            response += f"    ⏰ 时间段: {detail.get('slot', {}).get('start', 'N/A')}-{detail.get('slot', {}).get('end', 'N/A')}\n"
                        else:
                            response += f"    📝 原因: {detail.get('message', 'N/A')}\n"
                
                response += "\n"
            
            await auto_booking_results_cmd.finish(response)
        else:
            await auto_booking_results_cmd.finish(f"❌ 获取抢票记录失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"获取抢票记录出错: {e}")
        await auto_booking_results_cmd.finish(f"❌ 获取抢票记录出错: {str(e)}")


@auto_booking_test_cmd.handle()
async def handle_auto_booking_test(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理测试抢票命令"""
    try:
        args_str = str(args).strip()
        target_date = None
        
        if args_str:
            # 解析日期参数
            if args_str.isdigit():
                days = int(args_str)
                target_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            else:
                target_date = args_str
        
        logger.info(f"收到测试抢票命令: target_date={target_date}")
        
        response = f"🧪 开始测试抢票...\n"
        response += f"📅 目标日期: {target_date or '7天后'}\n"
        response += f"⏰ 开始时间: {datetime.now().strftime('%H:%M:%S')}\n\n"
        
        await auto_booking_test_cmd.send(response)
        
        # 执行测试抢票
        result = await execute_manual_booking(target_date)
        
        if result["success"]:
            response = f"✅ 测试抢票完成！\n\n"
            response += f"📊 执行结果:\n"
            
            results = result.get("results", [])
            for i, booking_result in enumerate(results, 1):
                target = booking_result.get("target", {})
                status_icon = "✅" if booking_result.get("success", False) else "❌"
                response += f"{i}. {status_icon} {target.get('description', '未知')}\n"
                
                if booking_result.get("success"):
                    response += f"   🎫 订单ID: {booking_result.get('order_id', 'N/A')}\n"
                    response += f"   ⏰ 时间段: {booking_result.get('slot', {}).get('start', 'N/A')}-{booking_result.get('slot', {}).get('end', 'N/A')}\n"
                    response += f"   🔄 尝试次数: {booking_result.get('attempt', 1)}\n"
                else:
                    response += f"   📝 失败原因: {booking_result.get('message', 'N/A')}\n"
                
                response += "\n"
            
            await auto_booking_test_cmd.finish(response)
        else:
            await auto_booking_test_cmd.finish(f"❌ 测试抢票失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"测试抢票出错: {e}")
        await auto_booking_test_cmd.finish(f"❌ 测试抢票出错: {str(e)}")


def parse_config_args(args_str: str) -> Optional[dict]:
    """解析配置参数"""
    # 简单的配置解析，实际使用中可以更复杂
    # 格式: preset=13 priority=1 enabled=true times=18,19,20
    try:
        config = {}
        parts = args_str.split()
        
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                if key == "preset":
                    config["preset"] = int(value)
                elif key == "priority":
                    config["priority"] = int(value)
                elif key == "enabled":
                    config["enabled"] = value.lower() == "true"
                elif key == "times":
                    config["time_slots"] = [int(t) for t in value.split(",")]
                elif key == "attempts":
                    config["max_attempts"] = int(value)
                elif key == "desc":
                    config["description"] = value
        
        return config if config else None
        
    except Exception:
        return None
