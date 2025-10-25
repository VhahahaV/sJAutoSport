"""
登录协同插件
提供通过 QQ 与机器人交互完成登陆、验证码回传等功能
"""

import base64
from datetime import datetime
from typing import Dict, Optional

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking import service  # pylint: disable=wrong-import-position
from bot import services as bot_services

from typing import Dict

# 命令处理器
login_cmd = on_command("登录", aliases={"login"}, priority=3)
verify_cmd = on_command("验证码", aliases={"verify"}, priority=3)
cancel_login_cmd = on_command("取消登录", aliases={"cancel_login"}, priority=3)
login_status_cmd = on_command("登录状态", aliases={"login_status"}, priority=3)
user_list_cmd = on_command("用户列表", aliases={"users", "user_list"}, priority=3)
user_switch_cmd = on_command("切换用户", aliases={"switch_user"}, priority=3)
user_delete_cmd = on_command("删除用户", aliases={"delete_user"}, priority=3)
userinfo_cmd = on_command("用户信息", aliases={"userinfo", "debug-login"}, priority=3)
presets_cmd = on_command("预设", aliases={"presets", "场馆列表", "venues"}, priority=3)
help_cmd = on_command("帮助", aliases={"help", "指令", "commands"}, priority=3)

# 用户与会话映射
_user_sessions: Dict[str, Dict[str, str]] = {}


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
    
    # 处理用户选择命令
    if args_str.startswith("select "):
        user_id = event.get_user_id()
        
        try:
            user_index = int(args_str.split(" ", 1)[1]) - 1
            
            # 直接获取用户列表，不依赖会话状态
            from sja_booking.auth import AuthManager
            import config as CFG
            
            auth_manager = AuthManager()
            cookie_map, active_username = auth_manager.load_all_cookies()
            config_users = getattr(CFG.AUTH, "users", []) or []
            
            # 优先使用已保存cookie的用户，然后使用config.py中的用户
            user_list = []
            
            # 添加已保存cookie的用户
            for key, record in cookie_map.items():
                user_list.append({
                    "type": "cookie",
                    "key": key,
                    "username": record.get("username"),
                    "password": record.get("password"),
                    "nickname": record.get("nickname"),
                })
            
            # 添加config.py中的用户（如果还没有cookie）
            for user in config_users:
                if not any(u.get("username") == user.username for u in user_list):
                    user_list.append({
                        "type": "config",
                        "key": user.nickname,
                        "username": user.username,
                        "password": user.password,
                        "nickname": user.nickname,
                    })
            
            if not user_list:
                await login_cmd.finish("❌ 没有可用的用户，请先使用 !login user=用户名 pass=密码 创建用户")
            
            if 0 <= user_index < len(user_list):
                user_info = user_list[user_index]
                username = user_info.get("username")
                password = user_info.get("password")
                nickname = user_info.get("nickname")
                
                if not username:
                    await login_cmd.finish("❌ 该用户没有用户名")
                
                if not password:
                    await login_cmd.finish("❌ 该用户没有保存密码，请使用 !login user=用户名 pass=密码 直接登录")
                
                # 使用保存的凭据登录
                result = await service.start_login_session(
                    user_id=user_id,
                    username=username,
                    password=password,
                    nickname=nickname,
                )
                
                if not result.get("success"):
                    await login_cmd.finish(f"❌ 登录失败：{result.get('message', '未知错误')}")
                
                if result.get("captcha_required"):
                    session_id = result["session_id"]
                    _user_sessions[user_id] = {
                        "session_id": session_id,
                        "username": username,
                        "nickname": nickname or "",
                    }
                    image = result.get("captcha_image", b"")
                    response = Message()
                    response.append("🔐 登录已初始化，请回复\"验证码 123456\"完成验证。\n")
                    if image:
                        response += _image_segment(image)
                    await login_cmd.finish(response)
                
                if result.get("username"):
                    bot_services.set_active_user(result.get("username"))
                
                summary = result.get("nickname") or result.get("username") or "用户"
                await login_cmd.finish(
                    f"✅ {summary} 登录成功，Cookie 有效期至 {result.get('expires_at', '未知')}"
                )
            else:
                await login_cmd.finish(f"❌ 无效的用户序号，请使用 1-{len(user_list)} 之间的数字")
        except (ValueError, IndexError):
            await login_cmd.finish("❌ 请提供有效的用户序号，例如：!login select 1")
    
    elif args_str.startswith("delete "):
        user_id = event.get_user_id()
        
        try:
            user_index = int(args_str.split(" ", 1)[1]) - 1
            
            # 直接获取用户列表，不依赖会话状态
            from sja_booking.auth import AuthManager
            auth_manager = AuthManager()
            cookie_map, active_username = auth_manager.load_all_cookies()
            
            if not cookie_map:
                await login_cmd.finish("❌ 没有保存的用户")
            
            user_list = list(cookie_map.items())
            if 0 <= user_index < len(user_list):
                key, record = user_list[user_index]
                username = record.get("username")
                nickname = record.get("nickname")
                
                # 删除用户
                if bot_services.remove_user(username or nickname or key):
                    await login_cmd.finish(f"✅ 已删除用户 {nickname or username or key}")
                else:
                    await login_cmd.finish(f"❌ 删除用户失败")
            else:
                await login_cmd.finish(f"❌ 无效的用户序号，请使用 1-{len(user_list)} 之间的数字")
        except (ValueError, IndexError):
            await login_cmd.finish("❌ 请提供有效的用户序号，例如：!login delete 1")
    
    elif args_str == "list":
        # 显示用户列表
        try:
            from sja_booking.auth import AuthManager
            auth_manager = AuthManager()
            cookie_map, active_username = auth_manager.load_all_cookies()
            
            if not cookie_map:
                await login_cmd.finish("❌ 没有保存的用户")
            
            response_parts = ["📋 已保存的用户列表："]
            for idx, (key, record) in enumerate(cookie_map.items(), start=1):
                label = record.get("nickname") or record.get("username") or "默认用户"
                if key == "__default__":
                    label = f"{label} (默认)"
                if active_username and key == active_username:
                    label = f"{label} [当前活跃]"
                
                expires_at = record.get("expires_at")
                if isinstance(expires_at, datetime):
                    now = datetime.now(expires_at.tzinfo)
                    if expires_at < now:
                        label = f"{label} (已过期 {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
                    else:
                        label = f"{label} (expires {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
                
                response_parts.append(f"{idx}. {label}")
            
            response_parts.append("")
            response_parts.append("使用方法：")
            response_parts.append("• 选择用户：!login select 1")
            response_parts.append("• 删除用户：!login delete 1")
            response_parts.append("• 创建用户：!login new user=用户名 pass=密码 nick=昵称")
            
            await login_cmd.finish("\n".join(response_parts))
        except Exception as e:
            await login_cmd.finish(f"❌ 获取用户列表失败: {str(e)}")
    
    elif args_str == "cancel":
        _user_sessions.pop(event.get_user_id(), None)
        await login_cmd.finish("✅ 已取消登录操作")
    
    # 如果直接提供了用户名和密码，直接登录
    elif args_str and ("user=" in args_str or "pass=" in args_str):
        username: Optional[str] = None
        password: Optional[str] = None
        nickname: Optional[str] = None
        
        for param in args_str.split():
            if param.startswith("user="):
                username = param.split("=", 1)[1]
            if param.startswith("pass="):
                password = param.split("=", 1)[1]
            if param.startswith("nick="):
                nickname = param.split("=", 1)[1]

        result = await service.start_login_session(
            user_id=event.get_user_id(),
            username=username,
            password=password,
            nickname=nickname,
        )
        if not result.get("success"):
            await login_cmd.finish(f"❌ 登录初始化失败：{result.get('message', '未知错误')}")

        if result.get("captcha_required"):
            session_id = result["session_id"]
            _user_sessions[event.get_user_id()] = {
                "session_id": session_id,
                "username": username or result.get("username", ""),
                "nickname": nickname or result.get("nickname", ""),
            }
            image = result.get("captcha_image", b"")
            response = Message()
            response.append("🔐 登录已初始化，请回复\"验证码 123456\"完成验证。\n")
            if image:
                response += _image_segment(image)
            await login_cmd.finish(response)

        if result.get("username"):
            bot_services.set_active_user(result.get("username"))

        summary = result.get("nickname") or result.get("username") or "用户"
        await login_cmd.finish(
            f"✅ {summary} 登录成功，Cookie 有效期至 {result.get('expires_at', '未知')}"
        )
    
    # 否则显示用户选择菜单
    try:
        from sja_booking.auth import AuthManager
        from sja_booking.models import AuthConfig, UserAuth
        import config as CFG
        
        auth_manager = AuthManager()
        cookie_map, active_username = auth_manager.load_all_cookies()
        
        # 检查config.py中的用户配置
        config_users = getattr(CFG.AUTH, "users", []) or []
        
        if not cookie_map and not config_users:
            # 既没有保存的cookie，也没有config.py中的用户配置
            await login_cmd.finish("❌ 没有配置任何用户，请使用以下格式直接登录：\n!login user=用户名 pass=密码 nick=昵称")
        
        if not cookie_map:
            # 没有保存的cookie，但有config.py中的用户配置，显示这些用户
            response_parts = ["📋 已配置的用户列表（需要登录）："]
            for idx, user in enumerate(config_users, start=1):
                nickname = user.nickname or "未命名"
                username = user.username or "未设置"
                response_parts.append(f"{idx}. {nickname} ({username})")
            
            response_parts.append("")
            response_parts.append("请选择操作：")
            response_parts.append("1. 选择已有用户登录")
            response_parts.append("2. 创建新用户")
            response_parts.append("3. 取消")
            response_parts.append("")
            response_parts.append("使用方法：")
            response_parts.append("• 选择用户：!login select 1")
            response_parts.append("• 创建用户：!login new user=用户名 pass=密码 nick=昵称")
            response_parts.append("• 取消：!login cancel")
            
            await login_cmd.finish("\n".join(response_parts))
        
        # 显示用户列表
        response_parts = ["📋 已保存的用户列表："]
        user_list = []
        
        for idx, (key, record) in enumerate(cookie_map.items(), start=1):
            label = record.get("nickname") or record.get("username") or "默认用户"
            if key == "__default__":
                label = f"{label} (默认)"
            if active_username and key == active_username:
                label = f"{label} [当前活跃]"
            
            expires_at = record.get("expires_at")
            if isinstance(expires_at, datetime):
                label = f"{label} (expires {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
            
            response_parts.append(f"{idx}. {label}")
            user_list.append((key, record))
        
        response_parts.append("")
        response_parts.append("请选择操作：")
        response_parts.append("1. 选择已有用户登录")
        response_parts.append("2. 创建新用户")
        response_parts.append("3. 删除用户")
        response_parts.append("4. 取消")
        response_parts.append("")
        response_parts.append("使用方法：")
        response_parts.append("• 选择用户：!login select 1")
        response_parts.append("• 创建用户：!login new user=用户名 pass=密码 nick=昵称")
        response_parts.append("• 删除用户：!login delete 1")
        response_parts.append("• 取消：!login cancel")
        
        # 保存用户列表到会话中
        _user_sessions[event.get_user_id()] = {
            "user_list": user_list,
            "mode": "selection"
        }
        
        await login_cmd.finish("\n".join(response_parts))
        
    except Exception as e:
        await login_cmd.finish(f"❌ 获取用户列表失败: {str(e)}")


@verify_cmd.handle()
async def handle_verify(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """提交验证码，继续登录。"""
    if not _check_permission(bot, event):
        await verify_cmd.finish("❌ 仅限管理员使用此命令")

    session_meta = _user_sessions.get(event.get_user_id())
    if not session_meta:
        await verify_cmd.finish("⚠️ 当前没有待提交的验证码，请先发送“登录”命令。")

    session_id = session_meta.get("session_id")

    code = str(args).strip()
    if not code:
        await verify_cmd.finish("❌ 请在命令后填写验证码，例如：验证码 123456")

    result = await service.submit_login_session_code(session_id, code)
    if result.get("success"):
        meta = _user_sessions.pop(event.get_user_id(), {})
        nickname = result.get("nickname") or meta.get("nickname") or result.get("username")
        if result.get("username"):
            bot_services.set_active_user(result.get("username"))
        await verify_cmd.finish(
            f"✅ {nickname or '用户'} 登录成功，Cookie 有效期至 {result.get('expires_at', '未知')}"
        )

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

    session_meta = _user_sessions.pop(event.get_user_id(), None)
    session_id = session_meta.get("session_id") if session_meta else None
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

    summary_text = bot_services.summarize_users_text()
    await login_status_cmd.finish(summary_text)


@user_list_cmd.handle()
async def handle_user_list(bot: Bot, event: MessageEvent):
    if not _check_permission(bot, event):
        await user_list_cmd.finish("❌ 仅限管理员使用此命令")

    summary_text = bot_services.summarize_users_text()
    await user_list_cmd.finish(summary_text)


@user_switch_cmd.handle()
async def handle_user_switch(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not _check_permission(bot, event):
        await user_switch_cmd.finish("❌ 仅限管理员使用此命令")

    target = str(args).strip()
    if not target:
        await user_switch_cmd.finish("❌ 请提供要切换的用户昵称或用户名")

    if bot_services.set_active_user(target):
        await user_switch_cmd.finish(f"✅ 已将 {target} 设置为活跃用户")

    candidate = bot_services.resolve_user(target)
    if candidate and candidate.username and bot_services.set_active_user(candidate.username):
        await user_switch_cmd.finish(f"✅ 已将 {candidate.nickname} 设置为活跃用户")

    await user_switch_cmd.finish(f"❌ 未找到用户 {target}")


@user_delete_cmd.handle()
async def handle_user_delete(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not _check_permission(bot, event):
        await user_delete_cmd.finish("❌ 仅限管理员使用此命令")

    target = str(args).strip()
    if not target:
        await user_delete_cmd.finish("❌ 请提供要删除的用户昵称或用户名")

    if bot_services.remove_user(target):
        await user_delete_cmd.finish(f"✅ 已删除用户 {target}")

    candidate = bot_services.resolve_user(target)
    if candidate and bot_services.remove_user(candidate.nickname):
        await user_delete_cmd.finish(f"✅ 已删除用户 {candidate.nickname}")

    await user_delete_cmd.finish(f"❌ 未找到用户 {target}")


@userinfo_cmd.handle()
async def handle_userinfo(bot: Bot, event: MessageEvent):
    """显示详细的用户信息"""
    if not _check_permission(bot, event):
        await userinfo_cmd.finish("❌ 仅限管理员使用此命令")

    response_parts = []
    
    try:
        # 获取所有用户的详细信息
        from sja_booking.auth import AuthManager
        from sja_booking.models import AuthConfig, UserAuth
        from sja_booking.api import SportsAPI
        import config as CFG
        
        auth_manager = AuthManager()
        cookie_map, active_username = auth_manager.load_all_cookies()
        
        if not cookie_map:
            response_parts.append("❌ 尚未保存任何登录凭据")
        else:
            for idx, (key, record) in enumerate(cookie_map.items(), start=1):
                label = record.get("nickname") or record.get("username") or "默认用户"
                if key == "__default__":
                    label = f"{label} (默认)"
                if active_username and key == active_username:
                    label = f"{label} [当前活跃]"
                
                expires_at = record.get("expires_at")
                if isinstance(expires_at, datetime):
                    now = datetime.now(expires_at.tzinfo)
                    if expires_at < now:
                        label = f"{label} (已过期 {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
                    else:
                        label = f"{label} (expires {expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
                
                # 创建临时API实例来获取用户详细信息
                temp_user = UserAuth(
                    nickname=record.get("nickname") or label,
                    cookie=record.get("cookie"),
                    username=record.get("username"),
                )
                temp_auth = AuthConfig(users=[temp_user])
                temp_api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, temp_auth, preset_targets=CFG.PRESET_TARGETS)
                
                try:
                    user_data = temp_api.check_login()
                    if isinstance(user_data, dict) and user_data.get("code") == 0:
                        # 提取用户详细信息
                        data = user_data.get("data", {})
                        if data:
                            response_parts.append(f"👤 用户 {idx}: {label}")
                            response_parts.append(f"   ✅ 登录成功")
                            response_parts.append(f"   📝 姓名: {data.get('userName', '未知')}")
                            response_parts.append(f"   🆔 学号: {data.get('code', '未知')}")
                            response_parts.append(f"   📱 手机: {data.get('phonenumber', '未知')}")
                            response_parts.append(f"   🏫 部门: {data.get('dept', {}).get('deptName', '未知')}")
                            response_parts.append(f"   👥 角色: {', '.join([r.get('roleName', '') for r in data.get('roles', [])]) or '无'}")
                            response_parts.append("")
                        else:
                            response_parts.append(f"👤 用户 {idx}: {label}")
                            response_parts.append(f"   ⚠️ 认证有效但无法获取详细信息")
                            response_parts.append("")
                    else:
                        response_parts.append(f"👤 用户 {idx}: {label}")
                        response_parts.append(f"   ❌ 登录失败")
                        response_parts.append("")
                except Exception as e:
                    response_parts.append(f"👤 用户 {idx}: {label}")
                    response_parts.append(f"   ❌ 错误: {str(e)}")
                    response_parts.append("")
                finally:
                    try:
                        temp_api.close()
                    except:
                        pass
                        
    except Exception as e:
        response_parts.append(f"❌ 获取用户信息失败: {str(e)}")
    
    # 只调用一次 finish()
    if response_parts:
        await userinfo_cmd.finish("\n".join(response_parts))
    else:
        await userinfo_cmd.finish("❌ 无法获取用户信息")


@presets_cmd.handle()
async def handle_presets(bot: Bot, event: MessageEvent):
    """显示所有预设场馆和运动类型"""
    if not _check_permission(bot, event):
        await presets_cmd.finish("❌ 仅限管理员使用此命令")

    try:
        import config as CFG
        
        response_parts = ["🏟️ 预设场馆列表：", ""]
        
        # 按场馆分组显示
        venues = {}
        for preset in CFG.PRESET_TARGETS:
            venue_name = preset.venue_name
            if venue_name not in venues:
                venues[venue_name] = []
            venues[venue_name].append(preset)
        
        for venue_name, presets in venues.items():
            response_parts.append(f"🏢 {venue_name}")
            for preset in presets:
                response_parts.append(f"   {preset.index:2d}. {preset.field_type_name}")
            response_parts.append("")
        
        response_parts.append("💡 使用方法：")
        response_parts.append("• 查询时间段：!slots --preset 5")
        response_parts.append("• 开始监控：!monitor --preset 5")
        response_parts.append("• 立即预订：!book-now --preset 5")
        
        await presets_cmd.finish("\n".join(response_parts))
        
    except Exception as e:
        await presets_cmd.finish(f"❌ 获取预设列表失败: {str(e)}")


@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent):
    """显示完整的帮助信息"""
    if not _check_permission(bot, event):
        await help_cmd.finish("❌ 仅限管理员使用此命令")

    help_text = """
🤖 SJTU体育场馆预订机器人 - 完整指令手册

📋 用户管理指令：
• !userinfo - 查看所有用户详细信息
• !login_status - 查看当前登录状态
• !login list - 显示已保存的用户列表
• !login select 1 - 选择用户1登录
• !login new user=用户名 pass=密码 nick=昵称 - 创建新用户
• !login delete 1 - 删除用户1
• !verify 验证码 - 提交验证码完成登录
• !cancel_login - 取消当前登录操作

🏟️ 场馆查询指令：
• !slots - 查询默认场馆的可用时间段
• !slots --preset 5 - 查询预设5的可用时间段
• !slots --date-offset 1 - 查询明天的可用时间段
• !presets - 查看所有预设场馆列表

📅 监控指令：
• !monitor - 开始监控默认场馆
• !monitor --preset 5 - 监控预设5的场馆
• !stop - 停止监控
• !status - 查看监控状态

🎫 预订指令：
• !book - 立即预订默认场馆
• !book --preset 5 - 立即预订预设5
• !schedule - 设置定时预订
• !jobs - 查看定时任务列表
• !cancel - 取消定时任务

🚀 自动抢票指令：
• !start_auto - 启动自动抢票
• !stop_auto - 停止自动抢票
• !auto_status - 查看抢票状态
• !auto_config - 配置抢票参数
• !auto_results - 查看抢票记录
• !test_auto - 测试抢票功能

⚙️ 系统管理指令：
• !system - 查看系统状态
• !cleanup - 清理过期任务
• !admin_help - 查看管理帮助

📊 热门预设场馆：
• 预设5: 气膜体育中心 - 羽毛球
• 预设13: 南洋北苑 - 健身房  
• 预设18: 霍英东体育中心 - 羽毛球
• 预设1: 学生中心 - 交谊厅

💡 使用技巧：
1. 先使用 !userinfo 检查登录状态
2. 使用 !presets 查看所有可用场馆
3. 使用 !slots --preset X 查询特定场馆
4. 使用 !monitor --preset X 开始监控
5. 使用 !book --preset X 立即预订

❓ 需要帮助？发送 !help 查看此帮助信息
    """.strip()
    
    await help_cmd.finish(help_text)
