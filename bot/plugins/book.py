"""
预订插件
支持立即预订和定时预订功能
"""

import re
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
from sja_booking.service import order_once, schedule_daily_job, list_scheduled_jobs, cancel_scheduled_job

# 命令处理器
book_now_cmd = on_command("预订", aliases={"book", "立即预订"}, priority=5)
book_schedule_cmd = on_command("定时预订", aliases={"schedule", "定时"}, priority=5)
book_preset_cmd = on_regex(r"预订\s+preset=(\d+)", priority=5)
list_jobs_cmd = on_command("任务列表", aliases={"jobs", "定时任务"}, priority=5)
cancel_job_cmd = on_command("取消任务", aliases={"cancel", "取消"}, priority=5)


@book_now_cmd.handle()
async def handle_book_now(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理立即预订命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        logger.info(f"收到立即预订命令: {args_str}")
        
        # 解析参数
        params = parse_booking_args(args_str)
        
        if not params.get("preset") and not params.get("venue_keyword"):
            await book_now_cmd.finish("❌ 请指定场馆，使用 preset=数字 或 venue=场馆名")
        
        # 调用服务层
        result = await order_once(
            preset=params.get("preset"),
            date=params.get("date", "0"),
            start_time=params.get("start_time", "18"),
            end_time=params.get("end_time"),
        )
        
        if result.success:
            response = f"✅ 预订成功！\n"
            response += f"📅 日期: {params.get('date', '今天')}\n"
            response += f"⏰ 时间: {params.get('start_time', '18:00')}\n"
            response += f"🏟️ 场馆: 预设{params.get('preset', 'N/A')}\n"
            response += f"📝 消息: {result.message}"
            if result.order_id:
                response += f"\n🆔 订单ID: {result.order_id}"
            await book_now_cmd.finish(response)
        else:
            await book_now_cmd.finish(f"❌ 预订失败: {result.message}")
            
    except Exception as e:
        logger.error(f"立即预订出错: {e}")
        await book_now_cmd.finish(f"❌ 预订出错: {str(e)}")


@book_preset_cmd.handle()
async def handle_book_preset(bot: Bot, event: MessageEvent, groups: tuple = RegexGroup()):
    """处理 preset 样式预订命令"""
    try:
        preset_id = int(groups[0])
        logger.info(f"收到预设预订命令: preset={preset_id}")
        
        # 调用服务层
        result = await order_once(
            preset=preset_id,
            date="0",  # 默认今天
            start_time="18",  # 默认18点
        )
        
        if result.success:
            response = f"✅ 预订成功！\n"
            response += f"🏟️ 预设场馆: {preset_id}\n"
            response += f"📅 日期: 今天\n"
            response += f"⏰ 时间: 18:00\n"
            response += f"📝 消息: {result.message}"
            if result.order_id:
                response += f"\n🆔 订单ID: {result.order_id}"
            await book_preset_cmd.finish(response)
        else:
            await book_preset_cmd.finish(f"❌ 预订失败: {result.message}")
            
    except Exception as e:
        logger.error(f"预设预订出错: {e}")
        await book_preset_cmd.finish(f"❌ 预订出错: {str(e)}")


@book_schedule_cmd.handle()
async def handle_book_schedule(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理定时预订命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        logger.info(f"收到定时预订命令: {args_str}")
        
        # 解析参数
        params = parse_schedule_args(args_str)
        
        if not params.get("preset") and not params.get("venue_keyword"):
            await book_schedule_cmd.finish("❌ 请指定场馆，使用 preset=数字 或 venue=场馆名")
        
        # 生成任务ID
        job_id = f"job_{int(datetime.now().timestamp())}"
        
        # 调用服务层
        result = await schedule_daily_job(
            job_id=job_id,
            hour=params.get("hour", 8),
            minute=params.get("minute", 0),
            preset=params.get("preset"),
            date=params.get("date", "0"),
            start_hour=params.get("start_hour", 18),
        )
        
        if result["success"]:
            job_info = result["job_info"]
            response = f"✅ 定时任务创建成功！\n"
            response += f"🆔 任务ID: {job_id}\n"
            response += f"⏰ 执行时间: {job_info['hour']:02d}:{job_info['minute']:02d}\n"
            response += f"🏟️ 场馆: 预设{params.get('preset', 'N/A')}\n"
            response += f"📅 预订日期: {params.get('date', '今天')}\n"
            response += f"🕐 预订时间: {params.get('start_hour', 18):02d}:00\n"
            response += f"📝 状态: {job_info['status']}"
            await book_schedule_cmd.finish(response)
        else:
            await book_schedule_cmd.finish(f"❌ 定时任务创建失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"定时预订出错: {e}")
        await book_schedule_cmd.finish(f"❌ 定时预订出错: {str(e)}")


@list_jobs_cmd.handle()
async def handle_list_jobs(bot: Bot, event: MessageEvent):
    """处理任务列表命令"""
    try:
        # 调用服务层
        result = await list_scheduled_jobs()
        
        if result["success"]:
            jobs = result["jobs"]
            if not jobs:
                await list_jobs_cmd.finish("📋 当前没有定时任务")
            
            response = f"📋 定时任务列表 (共{len(jobs)}个):\n\n"
            
            for job in jobs:
                response += f"🆔 {job['id']}\n"
                response += f"⏰ 执行时间: {job['hour']:02d}:{job['minute']:02d}\n"
                response += f"📅 预订日期: {job.get('date', '今天')}\n"
                response += f"🕐 预订时间: {job.get('start_hour', 18):02d}:00\n"
                response += f"📊 状态: {job['status']}\n"
                response += f"🔄 运行次数: {job.get('run_count', 0)}\n"
                response += f"✅ 成功次数: {job.get('success_count', 0)}\n"
                if job.get('last_run'):
                    response += f"🕐 最后运行: {job['last_run']}\n"
                if job.get('next_run'):
                    response += f"⏳ 下次运行: {job['next_run']}\n"
                response += "\n"
            
            await list_jobs_cmd.finish(response)
        else:
            await list_jobs_cmd.finish(f"❌ 获取任务列表失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"获取任务列表出错: {e}")
        await list_jobs_cmd.finish(f"❌ 获取任务列表出错: {str(e)}")


@cancel_job_cmd.handle()
async def handle_cancel_job(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理取消任务命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        if not args_str:
            await cancel_job_cmd.finish("❌ 请指定要取消的任务ID")
        
        job_id = args_str.strip()
        logger.info(f"收到取消任务命令: {job_id}")
        
        # 调用服务层
        result = await cancel_scheduled_job(job_id)
        
        if result["success"]:
            await cancel_job_cmd.finish(f"✅ 任务 {job_id} 已取消")
        else:
            await cancel_job_cmd.finish(f"❌ 取消任务失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        logger.error(f"取消任务出错: {e}")
        await cancel_job_cmd.finish(f"❌ 取消任务出错: {str(e)}")


def parse_booking_args(args_str: str) -> dict:
    """解析预订参数"""
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
        (r"end=(\d+)", "end_hour"),
    ]
    
    for pattern, param_name in patterns:
        match = re.search(pattern, args_str)
        if match:
            value = match.group(1)
            if param_name in ["preset", "date", "start_hour", "end_hour"]:
                params[param_name] = int(value)
            else:
                params[param_name] = value
    
    # 处理时间参数
    if "start_hour" in params:
        params["start_time"] = f"{params['start_hour']:02d}:00"
    if "end_hour" in params:
        params["end_time"] = f"{params['end_hour']:02d}:00"
    
    return params


def parse_schedule_args(args_str: str) -> dict:
    """解析定时预订参数"""
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
        (r"hour=(\d+)", "hour"),
        (r"minute=(\d+)", "minute"),
    ]
    
    for pattern, param_name in patterns:
        match = re.search(pattern, args_str)
        if match:
            value = match.group(1)
            if param_name in ["preset", "date", "start_hour", "hour", "minute"]:
                params[param_name] = int(value)
            else:
                params[param_name] = value
    
    return params
