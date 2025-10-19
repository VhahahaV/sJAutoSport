"""
管理插件
支持任务管理、系统状态查看
"""

import asyncio
from datetime import datetime
from typing import Optional

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

# 导入服务层
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking.service import (
    monitor_status, 
    list_scheduled_jobs, 
    cancel_scheduled_job,
    stop_monitor,
    get_verification_code,
    submit_verification_code
)

# 命令处理器
system_status_cmd = on_command("系统状态", aliases={"status", "系统"}, priority=5)
cleanup_cmd = on_command("清理", aliases={"cleanup", "清理任务"}, priority=5)
verification_cmd = on_command("验证码", aliases={"verify", "验证"}, priority=5)
help_cmd = on_command("管理帮助", aliases={"admin_help", "管理"}, priority=5)


@system_status_cmd.handle()
async def handle_system_status(bot: Bot, event: MessageEvent):
    """处理系统状态命令"""
    try:
        logger.info("收到系统状态命令")
        
        # 获取监控状态
        monitor_result = await monitor_status()
        active_monitors = monitor_result.get("monitors", []) if monitor_result["success"] else []
        
        # 获取定时任务状态
        jobs_result = await list_scheduled_jobs()
        scheduled_jobs = jobs_result.get("jobs", []) if jobs_result["success"] else []
        
        # 构建状态报告
        response = f"🖥️ 系统状态报告\n"
        response += f"🕐 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # 监控状态
        response += f"📊 监控任务: {len(active_monitors)}个活跃\n"
        if active_monitors:
            for monitor in active_monitors:
                status_icon = "🟢" if monitor["status"] == "running" else "🔴"
                response += f"  {status_icon} {monitor['id']} - {monitor['status']}\n"
        
        # 定时任务状态
        response += f"\n⏰ 定时任务: {len(scheduled_jobs)}个计划中\n"
        if scheduled_jobs:
            for job in scheduled_jobs:
                status_icon = "🟢" if job["status"] == "scheduled" else "🔴"
                response += f"  {status_icon} {job['id']} - {job['status']}\n"
                response += f"    ⏰ 执行时间: {job['hour']:02d}:{job['minute']:02d}\n"
                response += f"    🔄 运行次数: {job.get('run_count', 0)}\n"
                response += f"    ✅ 成功次数: {job.get('success_count', 0)}\n"
        
        # 系统资源信息
        response += f"\n💾 系统资源:\n"
        response += f"  🐍 Python版本: {sys.version.split()[0]}\n"
        response += f"  📁 工作目录: {Path.cwd()}\n"
        response += f"  🕐 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        await system_status_cmd.finish(response)
        
    except Exception as e:
        logger.error(f"获取系统状态出错: {e}")
        await system_status_cmd.finish(f"❌ 获取系统状态出错: {str(e)}")


@cleanup_cmd.handle()
async def handle_cleanup(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理清理命令"""
    try:
        # 解析参数
        args_str = str(args).strip().lower()
        logger.info(f"收到清理命令: {args_str}")
        
        cleaned_count = 0
        response = "🧹 清理任务执行结果:\n\n"
        
        if args_str in ["all", "全部", ""]:
            # 清理所有任务
            
            # 停止所有监控
            monitor_result = await monitor_status()
            if monitor_result["success"]:
                monitors = monitor_result["monitors"]
                for monitor in monitors:
                    stop_result = await stop_monitor(monitor["id"])
                    if stop_result["success"]:
                        cleaned_count += 1
                        response += f"✅ 停止监控: {monitor['id']}\n"
            
            # 取消所有定时任务
            jobs_result = await list_scheduled_jobs()
            if jobs_result["success"]:
                jobs = jobs_result["jobs"]
                for job in jobs:
                    cancel_result = await cancel_scheduled_job(job["id"])
                    if cancel_result["success"]:
                        cleaned_count += 1
                        response += f"✅ 取消定时任务: {job['id']}\n"
            
            response += f"\n🎉 清理完成，共处理 {cleaned_count} 个任务"
            
        elif args_str in ["monitors", "监控"]:
            # 只清理监控任务
            monitor_result = await monitor_status()
            if monitor_result["success"]:
                monitors = monitor_result["monitors"]
                for monitor in monitors:
                    stop_result = await stop_monitor(monitor["id"])
                    if stop_result["success"]:
                        cleaned_count += 1
                        response += f"✅ 停止监控: {monitor['id']}\n"
            
            response += f"\n🎉 清理完成，共停止 {cleaned_count} 个监控任务"
            
        elif args_str in ["jobs", "任务"]:
            # 只清理定时任务
            jobs_result = await list_scheduled_jobs()
            if jobs_result["success"]:
                jobs = jobs_result["jobs"]
                for job in jobs:
                    cancel_result = await cancel_scheduled_job(job["id"])
                    if cancel_result["success"]:
                        cleaned_count += 1
                        response += f"✅ 取消定时任务: {job['id']}\n"
            
            response += f"\n🎉 清理完成，共取消 {cleaned_count} 个定时任务"
            
        else:
            response = "❌ 无效的清理参数\n"
            response += "支持: all(全部), monitors(监控), jobs(任务)"
        
        await cleanup_cmd.finish(response)
        
    except Exception as e:
        logger.error(f"清理任务出错: {e}")
        await cleanup_cmd.finish(f"❌ 清理任务出错: {str(e)}")


@verification_cmd.handle()
async def handle_verification(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理验证码命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        logger.info(f"收到验证码命令: {args_str}")
        
        if not args_str:
            # 获取验证码
            result = await get_verification_code()
            
            if result["success"]:
                response = f"🔐 验证码信息:\n"
                response += f"📝 消息: {result.get('message', 'N/A')}\n"
                response += f"💡 使用 '验证码 123456' 提交验证码"
                await verification_cmd.finish(response)
            else:
                await verification_cmd.finish(f"❌ 获取验证码失败: {result.get('message', '未知错误')}")
        else:
            # 提交验证码
            code = args_str.strip()
            result = await submit_verification_code(code)
            
            if result["success"]:
                response = f"✅ 验证码提交成功!\n"
                response += f"🔐 验证码: {code}\n"
                response += f"📝 消息: {result.get('message', 'N/A')}"
                await verification_cmd.finish(response)
            else:
                await verification_cmd.finish(f"❌ 验证码提交失败: {result.get('message', '未知错误')}")
        
    except Exception as e:
        logger.error(f"验证码处理出错: {e}")
        await verification_cmd.finish(f"❌ 验证码处理出错: {str(e)}")


@help_cmd.handle()
async def handle_admin_help(bot: Bot, event: MessageEvent):
    """处理管理帮助命令"""
    help_text = """
🛠️ 管理命令帮助

📊 系统管理：
• 系统状态 - 查看系统运行状态
• 清理 [类型] - 清理任务（all/监控/任务）
• 验证码 [代码] - 获取或提交验证码

📋 监控管理：
• 开始监控 [参数] - 启动监控任务
• 停止监控 [ID/all] - 停止监控任务
• 监控状态 [ID] - 查看监控状态

📅 任务管理：
• 定时预订 [参数] - 创建定时预订任务
• 任务列表 - 查看所有定时任务
• 取消任务 [ID] - 取消指定任务

🎯 预订管理：
• 预订 [参数] - 立即预订
• 预订 preset=数字 - 快速预订

📝 查询管理：
• 查询 [参数] - 查询可用时间段
• 查询 preset=数字 - 快速查询

💡 参数说明：
• preset=数字 - 使用预设场馆
• venue=场馆名 - 指定场馆
• sport=运动类型 - 指定运动
• date=数字 - 日期（0=今天）
• time=数字 - 时间（24小时制）
• interval=数字 - 监控间隔（秒）
• auto - 启用自动预订

🔧 示例：
• 系统状态
• 清理 all
• 开始监控 preset=13 auto
• 定时预订 preset=13 hour=8
• 预订 preset=13 time=18
    """
    await help_cmd.finish(help_text)


# 添加 sys 导入
import sys
