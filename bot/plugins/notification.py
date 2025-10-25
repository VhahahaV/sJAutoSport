"""
通知管理插件
用于管理订单成功通知的配置和测试
"""

from typing import List, Optional
from nonebot import CommandGroup
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

# 导入服务层
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking.notification import send_order_notification
import config as CFG

notification_cmd = CommandGroup("notification", priority=5)

test_notification_cmd = notification_cmd.command("测试通知")
set_notification_cmd = notification_cmd.command("设置通知")
notification_status_cmd = notification_cmd.command("通知状态")


@test_notification_cmd.handle()
async def handle_test_notification(bot: Bot, event: MessageEvent, args: str = CommandArg()):
    """测试通知功能"""
    try:
        # 发送测试通知
        success = await send_order_notification(
            order_id="TEST-12345",
            user_nickname="测试用户",
            venue_name="测试场馆",
            field_type_name="测试项目",
            date="2024-01-01",
            start_time="19:00",
            end_time="20:00",
            success=True,
            message="这是一个测试通知",
            target_groups=CFG.NOTIFICATION_TARGETS.get("groups"),
            target_users=CFG.NOTIFICATION_TARGETS.get("users")
        )
        
        if success:
            await test_notification_cmd.finish("✅ 测试通知发送成功！")
        else:
            await test_notification_cmd.finish("❌ 测试通知发送失败，请检查bot配置")
            
    except Exception as e:
        logger.error(f"测试通知失败: {e}")
        await test_notification_cmd.finish(f"❌ 测试通知失败: {e}")


@set_notification_cmd.handle()
async def handle_set_notification(bot: Bot, event: MessageEvent, args: str = CommandArg()):
    """设置通知目标"""
    try:
        args_str = str(args).strip()
        if not args_str:
            await set_notification_cmd.finish(
                "❌ 请指定通知目标\n"
                "用法: 设置通知 群组=123456789,987654321 用户=123456,789012\n"
                "或者: 设置通知 群组=123456789\n"
                "或者: 设置通知 用户=123456"
            )
        
        # 解析参数
        groups = []
        users = []
        
        parts = args_str.split()
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                if key == "群组" or key == "group":
                    groups = [g.strip() for g in value.split(",") if g.strip()]
                elif key == "用户" or key == "user":
                    users = [u.strip() for u in value.split(",") if u.strip()]
        
        if not groups and not users:
            await set_notification_cmd.finish("❌ 请指定至少一个通知目标")
        
        # 更新配置
        CFG.NOTIFICATION_TARGETS["groups"] = groups
        CFG.NOTIFICATION_TARGETS["users"] = users
        
        # 构建响应消息
        response = "✅ 通知目标设置成功！\n"
        if groups:
            response += f"📢 群组: {', '.join(groups)}\n"
        if users:
            response += f"👤 用户: {', '.join(users)}\n"
        
        await set_notification_cmd.finish(response)
        
    except Exception as e:
        logger.error(f"设置通知目标失败: {e}")
        await set_notification_cmd.finish(f"❌ 设置失败: {e}")


@notification_status_cmd.handle()
async def handle_notification_status(bot: Bot, event: MessageEvent):
    """查看通知状态"""
    try:
        response = "📋 通知配置状态\n\n"
        
        # Bot配置
        response += f"🤖 Bot地址: {CFG.BOT_HTTP_URL}\n"
        response += f"🔑 访问令牌: {'已设置' if CFG.BOT_ACCESS_TOKEN else '未设置'}\n"
        response += f"🔔 通知启用: {'是' if CFG.ENABLE_ORDER_NOTIFICATION else '否'}\n\n"
        
        # 通知目标
        groups = CFG.NOTIFICATION_TARGETS.get("groups", [])
        users = CFG.NOTIFICATION_TARGETS.get("users", [])
        
        response += "📢 通知目标:\n"
        if groups:
            response += f"  群组: {', '.join(groups)}\n"
        else:
            response += "  群组: 未设置\n"
            
        if users:
            response += f"  用户: {', '.join(users)}\n"
        else:
            response += "  用户: 未设置\n"
        
        if not groups and not users:
            response += "\n⚠️ 未设置任何通知目标，订单成功通知将不会发送"
        
        await notification_status_cmd.finish(response)
        
    except Exception as e:
        logger.error(f"查看通知状态失败: {e}")
        await notification_status_cmd.finish(f"❌ 查看状态失败: {e}")
