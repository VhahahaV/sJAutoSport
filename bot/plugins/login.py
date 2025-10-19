"""
登录协同插件
提供通过 QQ 与机器人交互完成登陆、验证码回传等功能
"""

import base64
from typing import Optional

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking import service  # pylint: disable=wrong-import-position

# 命令处理器
login_cmd = on_command("登录", aliases={"login"}, priority=3)
verify_cmd = on_command("验证码", aliases={"verify"}, priority=3)
cancel_login_cmd = on_command("取消登录", aliases={"cancel_login"}, priority=3)
login_status_cmd = on_command("登录状态", aliases={"login_status"}, priority=3)

# 用户与会话映射
_user_sessions: dict[str, str] = {}


def _check_permission(bot: Bot, event: MessageEvent) -> bool:
    """仅允许超级用户或配置允许的用户执行关键命令。"""
    superusers = getattr(bot.config, "superusers", set())
    if superusers:
        return event.get_user_id() in superusers
    return True


def _image_segment(image_bytes: bytes) -> MessageSegment:
    payload = base64.b64encode(image_bytes).decode("ascii")
    return MessageSegment.image(f"base64://{payload}")


@login_cmd.handle()
async def handle_login(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """启动登录流程，必要时返回验证码。"""
    if not _check_permission(bot, event):
        await login_cmd.finish("❌ 仅限管理员使用此命令")

    args_str = str(args).strip()
    username: Optional[str] = None
    password: Optional[str] = None
    if args_str:
        for param in args_str.split():
            if param.startswith("user="):
                username = param.split("=", 1)[1]
            if param.startswith("pass="):
                password = param.split("=", 1)[1]

    result = await service.start_login_session(
        user_id=event.get_user_id(),
        username=username,
        password=password,
    )
    if not result.get("success"):
        await login_cmd.finish(f"❌ 登录初始化失败：{result.get('message', '未知错误')}")

    if result.get("captcha_required"):
        session_id = result["session_id"]
        _user_sessions[event.get_user_id()] = session_id
        image = result.get("captcha_image", b"")
        response = Message()
        response.append("🔐 登录已初始化，请回复“验证码 123456”完成验证。\n")
        if image:
            response += _image_segment(image)
        await login_cmd.finish(response)

    await login_cmd.finish(f"✅ {result.get('message', '登录成功')}，Cookie 有效期至 {result.get('expires_at', '未知')}")


@verify_cmd.handle()
async def handle_verify(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """提交验证码，继续登录。"""
    if not _check_permission(bot, event):
        await verify_cmd.finish("❌ 仅限管理员使用此命令")

    session_id = _user_sessions.get(event.get_user_id())
    if not session_id:
        await verify_cmd.finish("⚠️ 当前没有待提交的验证码，请先发送“登录”命令。")

    code = str(args).strip()
    if not code:
        await verify_cmd.finish("❌ 请在命令后填写验证码，例如：验证码 123456")

    result = await service.submit_login_session_code(session_id, code)
    if result.get("success"):
        _user_sessions.pop(event.get_user_id(), None)
        await verify_cmd.finish(f"✅ 登录成功，Cookie 有效期至 {result.get('expires_at', '未知')}")

    if result.get("retry"):
        image = result.get("captcha_image", b"")
        response = Message()
        response.append(result.get("message", "验证码错误，请重新输入。") + "\n")
        if image:
            response += _image_segment(image)
        await verify_cmd.finish(response)

    _user_sessions.pop(event.get_user_id(), None)
    await verify_cmd.finish(f"❌ 登录失败：{result.get('message', '未知错误')}")


@cancel_login_cmd.handle()
async def handle_cancel_login(bot: Bot, event: MessageEvent):
    """取消当前登录流程。"""
    if not _check_permission(bot, event):
        await cancel_login_cmd.finish("❌ 仅限管理员使用此命令")

    session_id = _user_sessions.pop(event.get_user_id(), None)
    if not session_id:
        await cancel_login_cmd.finish("ℹ️ 当前没有待取消的登录流程。")

    result = await service.cancel_login_session(session_id)
    message = "✅ 已取消登录流程" if result.get("success") else f"⚠️ {result.get('message', '取消失败')}"
    await cancel_login_cmd.finish(message)


@login_status_cmd.handle()
async def handle_login_status(bot: Bot, event: MessageEvent):
    """查看当前 Cookie 状态。"""
    if not _check_permission(bot, event):
        await login_status_cmd.finish("❌ 仅限管理员使用此命令")

    result = service.login_status()
    if not result.get("success"):
        await login_status_cmd.finish("ℹ️ 尚未保存任何登录凭据。")

    cookie = result.get("cookie", "")
    snippet = cookie[:80] + ("..." if len(cookie) > 80 else "")
    expires_at = result.get("expires_at", "未知")
    message = f"✅ 已保存 Cookie。\n🕒 有效期至：{expires_at}\n🍪 片段：{snippet}"
    await login_status_cmd.finish(message)
