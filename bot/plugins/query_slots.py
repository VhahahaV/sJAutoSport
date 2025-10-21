"""
查询时间段插件
支持 preset=... 样式命令查询可用时间段
"""

import re
from typing import Optional

from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import CommandArg, RegexGroup, CommandStart, RawCommand

# 导入服务层
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking.service import list_slots, SlotListResult

# 命令处理器
# block=True 防止命中后继续触发其他 matcher
query_slots_cmd = on_command(
    "查询",
    aliases={"slots", "查询时间段"},
    priority=5,
    block=True,
)
# 仅匹配独立 preset=xxx 形式，避免与命令重复
query_preset_cmd = on_regex(
    r"^\s*preset\s*=(\d+)\s*$",
    priority=6,
    block=True,
)
query_help_cmd = on_command("帮助", aliases={"help", "命令"}, priority=5)


@query_slots_cmd.handle()
async def handle_query_slots(
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
    command_start: Optional[str] = CommandStart(),
    raw_command: Optional[str] = RawCommand(),
):
    """处理查询时间段命令"""
    try:
        # 解析参数
        args_str = str(args).strip()
        logger.info(
            "收到查询命令: prefix=%r raw=%r args='%s' to_me=%s",
            command_start,
            raw_command,
            args_str,
            event.is_tome(),
        )
        
        # 解析参数
        params = parse_query_args(args_str)
        
        # 调用服务层
        result = await list_slots(**params)
        payload = normalize_slots_result(result)

        if not payload.get("success", False):
            await query_slots_cmd.finish(f"查询失败: {payload.get('message', '未知错误')}")
            return

        # 格式化输出并返回
        response = format_slots_response(payload)
        await query_slots_cmd.finish(response)
        return

        # 兜底避免 NoneBot 继续执行后续 handler
        # pylint: disable=lost-exception
        raise Exception("Unreachable code")
            
    except FinishedException:
        raise
    except Exception as e:  # pylint: disable=broad-except
        logger.error("查询时间段出错: %s", e)
        await query_slots_cmd.finish(f"查询出错: {type(e).__name__}: {str(e)}")


@query_preset_cmd.handle()
async def handle_query_preset(
    bot: Bot,
    event: MessageEvent,
    groups: tuple = RegexGroup(),
    command_start: Optional[str] = CommandStart(),
    raw_command: Optional[str] = RawCommand(),
):
    """处理 preset=... 样式命令"""
    try:
        preset_id = int(groups[0])
        logger.info(
            "收到预设查询命令: preset=%s prefix=%r raw=%r to_me=%s",
            preset_id,
            command_start,
            raw_command,
            event.is_tome(),
        )
        
        # 调用服务层
        result = await list_slots(preset=preset_id)
        payload = normalize_slots_result(result)

        if not payload.get("success", False):
            await query_preset_cmd.finish(f"查询失败: {payload.get('message', '未知错误')}")
            return

        # 格式化输出并返回
        response = format_slots_response(payload)
        await query_preset_cmd.finish(response)
        return

        raise Exception("Unreachable code")
            
    except FinishedException:
        raise
    except Exception as e:  # pylint: disable=broad-except
        logger.error("查询预设出错: %s", e)
        await query_preset_cmd.finish(f"查询出错: {type(e).__name__}: {str(e)}")


@query_help_cmd.handle()
async def handle_help(
    bot: Bot,
    event: MessageEvent,
    command_start: Optional[str] = CommandStart(),
    raw_command: Optional[str] = RawCommand(),
):
    """处理帮助命令"""
    logger.debug(
        "触发帮助命令: prefix=%r raw=%r to_me=%s",
        command_start,
        raw_command,
        event.is_tome(),
    )
    help_text = """
🏓 体育预订助手使用说明

📋 查询命令：
• 查询 [参数] - 查询可用时间段
• preset=数字 - 快速查询预设场馆
• 帮助 - 显示此帮助信息

🎯 查询参数：
• preset=数字 - 使用预设场馆（推荐）
• venue=场馆名 - 指定场馆名称
• sport=运动类型 - 指定运动类型
• date=日期 - 指定日期（0=今天，1=明天）
• time=时间 - 指定开始时间（如：18）

📝 使用示例：
• 查询 preset=13
• 查询 venue=学生中心 sport=羽毛球 date=1
• 查询 preset=5 time=21

🏟️ 常用预设：
• 1-4: 学生中心（交谊厅、台球、健身房、舞蹈）
• 5-6: 气膜体育中心（羽毛球、篮球）
• 13: 南洋北苑健身房
• 18-20: 霍英东体育中心（羽毛球、篮球、健身房）

💡 提示：使用 preset=数字 是最简单的方式！
    """
    await query_help_cmd.finish(help_text)


def parse_query_args(args_str: str) -> dict:
    """解析查询参数"""
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
    ]
    
    for pattern, param_name in patterns:
        match = re.search(pattern, args_str)
        if match:
            value = match.group(1)
            if param_name in ["preset", "date", "start_hour"]:
                params[param_name] = int(value)
            else:
                params[param_name] = value
    
    return params


def format_slots_response(result: dict) -> str:
    """格式化时间段查询结果"""
    if not result.get("slots"):
        return "❌ 没有找到可用的时间段"
    
    slots = result["slots"]
    venue_name = result.get("venue_name", "未知场馆")
    field_type_name = result.get("field_type_name", "未知运动")
    
    # 构建响应消息
    response = f"🏟️ {venue_name} - {field_type_name}\n"
    response += f"📅 找到 {len(slots)} 个可用时间段：\n\n"
    
    # 按日期分组显示
    slots_by_date = {}
    for slot in slots:
        date = slot.get("date", "未知日期")
        if date not in slots_by_date:
            slots_by_date[date] = []
        slots_by_date[date].append(slot)
    
    # 显示每个日期的时间段
    for date in sorted(slots_by_date.keys()):
        response += f"📅 {date}:\n"
        for slot in slots_by_date[date]:
            start_time = slot.get("start", "未知时间")
            end_time = slot.get("end", "未知时间")
            remain = slot.get("remain", 0)
            price = slot.get("price")
            
            # 格式化价格
            price_str = f"¥{price:.2f}" if price else "免费"
            
            # 格式化剩余数量
            remain_str = f"剩余{remain}个" if remain > 0 else "已满"
            
            response += f"  ⏰ {start_time}-{end_time} | {remain_str} | {price_str}\n"
        response += "\n"
    
        response += "💡 使用 'preset=数字' 快速查询其他场馆"
    
    return response


def normalize_slots_result(result) -> dict:
    """兼容服务层返回的 SlotListResult 或 dict 结构。"""
    if isinstance(result, dict):
        if "success" not in result:
            result = {**result, "success": True}
        return result

    if isinstance(result, SlotListResult):
        resolved = result.resolved
        preset = resolved.preset

        venue_name = (
            resolved.venue_name
            or (preset.venue_name if preset else None)
            or resolved.venue_id
        )
        field_type_name = (
            resolved.field_type_name
            or (preset.field_type_name if preset else None)
            or resolved.field_type_id
        )

        slots = []
        for item in result.slots:
            try:
                slots.append(
                    {
                        "date": item.date,
                        "start": item.start,
                        "end": item.end,
                        "price": item.price,
                        "remain": item.remain if item.remain is not None else (1 if item.available else 0),
                        "available": item.available,
                    }
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("格式化时间段失败: %s", exc)

        return {
            "success": True,
            "slots": slots,
            "venue_name": venue_name,
            "field_type_name": field_type_name,
        }

    logger.error("未识别的查询结果类型: %r", type(result))
    return {"success": False, "message": f"无法解析查询结果: {type(result).__name__}"}
