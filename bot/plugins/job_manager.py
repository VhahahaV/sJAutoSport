"""
任务管理插件
提供通过 QQ 与机器人交互管理后台任务的功能
"""

import sys
from pathlib import Path
from typing import Dict, Optional

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sja_booking.job_manager import get_job_manager, JobType, JobStatus


def _check_permission(bot: Bot, event: MessageEvent) -> bool:
    """仅允许超级用户或配置允许的用户执行关键命令。"""
    superusers = getattr(bot.config, "superusers", set())
    if superusers:
        return event.get_user_id() in superusers
    return True


# 命令处理器
jobs_cmd = on_command("任务列表", aliases={"jobs", "任务"}, priority=3)
job_start_cmd = on_command("启动任务", aliases={"job-start", "start-job"}, priority=3)
job_stop_cmd = on_command("停止任务", aliases={"job-stop", "stop-job"}, priority=3)
job_delete_cmd = on_command("删除任务", aliases={"job-delete", "delete-job"}, priority=3)
job_logs_cmd = on_command("任务日志", aliases={"job-logs", "logs"}, priority=3)
job_cleanup_cmd = on_command("清理任务", aliases={"jobs-cleanup", "cleanup"}, priority=3)
keep_alive_cmd = on_command("保持活跃", aliases={"keep-alive", "保持登录"}, priority=3)
create_monitor_cmd = on_command("创建监控", aliases={"create-monitor", "monitor-job"}, priority=3)
create_schedule_cmd = on_command("创建定时", aliases={"create-schedule", "schedule-job"}, priority=3)


@jobs_cmd.handle()
async def handle_jobs(bot: Bot, event: MessageEvent):
    """显示任务列表"""
    if not _check_permission(bot, event):
        await jobs_cmd.finish("❌ 仅限管理员使用此命令")

    try:
        job_manager = get_job_manager()
        jobs = job_manager.list_jobs()
        
        if not jobs:
            await jobs_cmd.finish("📋 当前没有任务")
        
        response_parts = ["📋 任务列表：", ""]
        
        for job in jobs:
            status_emoji = {
                JobStatus.PENDING: "⏳",
                JobStatus.RUNNING: "🟢",
                JobStatus.STOPPED: "🔴",
                JobStatus.FAILED: "❌",
                JobStatus.COMPLETED: "✅"
            }.get(job.status, "❓")
            
            pid_str = f" (PID: {job.pid})" if job.pid else ""
            created_str = job.created_at.strftime("%m-%d %H:%M")
            
            response_parts.append(f"{status_emoji} **{job.name}** ({job.job_id})")
            response_parts.append(f"   类型: {job.job_type.value}")
            response_parts.append(f"   状态: {job.status.value}{pid_str}")
            response_parts.append(f"   创建: {created_str}")
            
            if job.error_message:
                response_parts.append(f"   错误: {job.error_message}")
            
            response_parts.append("")
        
        await jobs_cmd.finish("\n".join(response_parts))
        
    except Exception as e:
        await jobs_cmd.finish(f"❌ 获取任务列表失败: {str(e)}")


@job_start_cmd.handle()
async def handle_job_start(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """启动任务"""
    if not _check_permission(bot, event):
        await job_start_cmd.finish("❌ 仅限管理员使用此命令")

    job_id = str(args).strip()
    if not job_id:
        await job_start_cmd.finish("❌ 请提供任务ID")

    try:
        job_manager = get_job_manager()
        success = job_manager.start_job(job_id)
        
        if success:
            await job_start_cmd.finish(f"✅ 任务 {job_id} 已启动")
        else:
            await job_start_cmd.finish(f"❌ 启动任务 {job_id} 失败")
            
    except Exception as e:
        await job_start_cmd.finish(f"❌ 启动任务失败: {str(e)}")


@job_stop_cmd.handle()
async def handle_job_stop(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """停止任务"""
    if not _check_permission(bot, event):
        await job_stop_cmd.finish("❌ 仅限管理员使用此命令")

    job_id = str(args).strip()
    if not job_id:
        await job_stop_cmd.finish("❌ 请提供任务ID")

    try:
        job_manager = get_job_manager()
        success = job_manager.stop_job(job_id)
        
        if success:
            await job_stop_cmd.finish(f"✅ 任务 {job_id} 已停止")
        else:
            await job_stop_cmd.finish(f"❌ 停止任务 {job_id} 失败")
            
    except Exception as e:
        await job_stop_cmd.finish(f"❌ 停止任务失败: {str(e)}")


@job_delete_cmd.handle()
async def handle_job_delete(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """删除任务"""
    if not _check_permission(bot, event):
        await job_delete_cmd.finish("❌ 仅限管理员使用此命令")

    job_id = str(args).strip()
    if not job_id:
        await job_delete_cmd.finish("❌ 请提供任务ID")

    try:
        job_manager = get_job_manager()
        success = job_manager.delete_job(job_id)
        
        if success:
            await job_delete_cmd.finish(f"✅ 任务 {job_id} 已删除")
        else:
            await job_delete_cmd.finish(f"❌ 删除任务 {job_id} 失败")
            
    except Exception as e:
        await job_delete_cmd.finish(f"❌ 删除任务失败: {str(e)}")


@job_logs_cmd.handle()
async def handle_job_logs(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """显示任务日志"""
    if not _check_permission(bot, event):
        await job_logs_cmd.finish("❌ 仅限管理员使用此命令")

    args_str = str(args).strip()
    if not args_str:
        await job_logs_cmd.finish("❌ 请提供任务ID")

    try:
        # 解析参数：job_id [lines]
        parts = args_str.split()
        job_id = parts[0]
        lines = int(parts[1]) if len(parts) > 1 else 20
        
        job_manager = get_job_manager()
        logs = job_manager.get_job_logs(job_id, lines)
        
        if not logs:
            await job_logs_cmd.finish(f"⚠️ 任务 {job_id} 没有日志")
        
        response_parts = [f"📋 任务 {job_id} 的最近 {lines} 行日志：", ""]
        response_parts.extend(logs[-lines:])  # 只显示最后几行
        
        # 如果日志太长，截断
        full_log = "\n".join(response_parts)
        if len(full_log) > 2000:  # QQ消息长度限制
            response_parts = response_parts[:2] + logs[-10:]  # 只显示最后10行
            response_parts.append("... (日志过长，只显示最后10行)")
        
        await job_logs_cmd.finish("\n".join(response_parts))
        
    except Exception as e:
        await job_logs_cmd.finish(f"❌ 获取任务日志失败: {str(e)}")


@job_cleanup_cmd.handle()
async def handle_job_cleanup(bot: Bot, event: MessageEvent):
    """清理已死亡的任务"""
    if not _check_permission(bot, event):
        await job_cleanup_cmd.finish("❌ 仅限管理员使用此命令")

    try:
        job_manager = get_job_manager()
        cleaned = job_manager.cleanup_dead_jobs()
        
        if cleaned == 0:
            await job_cleanup_cmd.finish("✅ 没有需要清理的任务")
        else:
            await job_cleanup_cmd.finish(f"✅ 已清理 {cleaned} 个已死亡的任务")
            
    except Exception as e:
        await job_cleanup_cmd.finish(f"❌ 清理任务失败: {str(e)}")


@create_monitor_cmd.handle()
async def handle_create_monitor(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """创建监控任务"""
    if not _check_permission(bot, event):
        await create_monitor_cmd.finish("❌ 仅限管理员使用此命令")

    args_str = str(args).strip()
    if not args_str:
        await create_monitor_cmd.finish("❌ 请提供任务名称，例如：!创建监控 监控任务名称")

    try:
        import config as CFG
        from sja_booking.models import BookingTarget, MonitorPlan
        
        # 解析参数（简化版本，实际使用中可能需要更复杂的解析）
        job_name = args_str
        
        # 使用默认配置创建监控任务
        target = CFG.TARGET
        plan = CFG.MONITOR_PLAN
        
        # 创建任务配置
        config = {
            'target': {
                'venue_keyword': target.venue_keyword,
                'field_type_keyword': target.field_type_keyword,
                'date_offset': target.date_offset,
                'start_hour': target.start_hour,
                'duration_hours': target.duration_hours
            },
            'plan': {
                'enabled': plan.enabled,
                'interval_seconds': plan.interval_seconds,
                'auto_book': plan.auto_book,
                'preferred_hours': plan.preferred_hours
            }
        }
        
        job_manager = get_job_manager()
        job_id = job_manager.create_job(
            job_type=JobType.MONITOR,
            name=job_name,
            config=config,
            auto_start=True
        )
        
        await create_monitor_cmd.finish(f"✅ 监控任务已创建: {job_name} (ID: {job_id})\n🚀 任务已自动启动")
        
    except Exception as e:
        await create_monitor_cmd.finish(f"❌ 创建监控任务失败: {str(e)}")


@create_schedule_cmd.handle()
async def handle_create_schedule(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """创建定时任务"""
    if not _check_permission(bot, event):
        await create_schedule_cmd.finish("❌ 仅限管理员使用此命令")

    args_str = str(args).strip()
    if not args_str:
        await create_schedule_cmd.finish("❌ 请提供任务名称和时间，例如：!创建定时 定时任务名称 12:00")

    try:
        import config as CFG
        from sja_booking.models import BookingTarget
        
        # 解析参数（简化版本）
        parts = args_str.split()
        job_name = parts[0]
        
        # 默认时间12:00
        hour, minute = 12, 0
        if len(parts) > 1:
            time_str = parts[1]
            if ':' in time_str:
                hour, minute = map(int, time_str.split(':'))
            else:
                hour = int(time_str)
        
        # 使用默认配置创建定时任务
        target = CFG.TARGET
        
        # 创建任务配置
        config = {
            'target': {
                'venue_keyword': target.venue_keyword,
                'field_type_keyword': target.field_type_keyword,
                'date_offset': target.date_offset,
                'start_hour': target.start_hour,
                'duration_hours': target.duration_hours
            },
            'schedule': {
                'hour': hour,
                'minute': minute,
                'second': 0,
                'preset': None,
                'date_offset': 1,
                'start_hour': 18
            }
        }
        
        job_manager = get_job_manager()
        job_id = job_manager.create_job(
            job_type=JobType.SCHEDULE,
            name=job_name,
            config=config,
            auto_start=True
        )
        
        await create_schedule_cmd.finish(f"✅ 定时任务已创建: {job_name} (ID: {job_id})\n⏰ 计划时间: {hour:02d}:{minute:02d}:00\n🚀 任务已自动启动")
        
    except Exception as e:
        await create_schedule_cmd.finish(f"❌ 创建定时任务失败: {str(e)}")


@keep_alive_cmd.handle()
async def handle_keep_alive(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """处理Keep-Alive命令"""
    if not _check_permission(bot, event):
        await keep_alive_cmd.finish("❌ 权限不足")
        return
    
    try:
        from sja_booking.keep_alive import (
            KeepAliveResult,
            run_keep_alive_for_user,
            run_keep_alive_once,
        )
        
        args_str = str(args).strip()
        
        if args_str == "状态" or args_str == "status":
            # 显示Keep-Alive状态
            job_manager = get_job_manager()
            keep_alive_jobs = [job for job in job_manager.jobs.values() if job.job_type == JobType.KEEP_ALIVE]
            
            if not keep_alive_jobs:
                await keep_alive_cmd.finish("⚠️ 没有找到Keep-Alive任务")
                return
                
            status_msg = "📋 Keep-Alive任务状态:\n"
            for job in keep_alive_jobs:
                status_icon = "🟢" if job.status == JobStatus.RUNNING else "🟡"
                status_msg += f"{status_icon} {job.name} (ID: {job.job_id}) - {job.status.value}\n"
            
            await keep_alive_cmd.finish(status_msg)
            
        elif args_str.startswith("刷新"):
            # 刷新Cookie
            parts = args_str.split()
            if len(parts) > 1:
                # 刷新特定用户
                user_nickname = parts[1]
                await keep_alive_cmd.send(f"🔄 刷新用户 {user_nickname} 的Cookie...")
                result: KeepAliveResult = await run_keep_alive_for_user(user_nickname)
                display_name = result.nickname or result.username or user_nickname
                if result.success:
                    await keep_alive_cmd.finish(f"✅ {display_name}: {result.message}")
                else:
                    await keep_alive_cmd.finish(f"❌ {display_name}: {result.message}")
            else:
                # 刷新所有用户
                await keep_alive_cmd.send("🔄 刷新所有用户的Cookie...")
                results = await run_keep_alive_once()
                
                success_count = sum(1 for r in results if r.success)
                total_count = len(results)
                
                result_msg = f"✅ 刷新完成: {success_count}/{total_count} 成功\n"
                for result in results:
                    icon = "✅" if result.success else "❌"
                    display_name = result.nickname or result.username or "未命名用户"
                    result_msg += f"{icon} {display_name}: {result.message}\n"
                
                await keep_alive_cmd.finish(result_msg)
                
        elif args_str.startswith("创建"):
            # 创建Keep-Alive任务
            parts = args_str.split()
            if len(parts) < 2:
                await keep_alive_cmd.finish("❌ 请提供任务名称，例如: !保持活跃 创建 我的Keep-Alive")
                return
                
            job_name = parts[1]
            interval = 15  # 默认15分钟
            
            if len(parts) > 2:
                try:
                    interval = int(parts[2])
                except ValueError:
                    await keep_alive_cmd.finish("❌ 间隔时间必须是数字")
                    return
            
            job_manager = get_job_manager()
            config = {'interval_seconds': max(1, interval) * 60}
            
            job_id = job_manager.create_job(
                job_type=JobType.KEEP_ALIVE,
                name=job_name,
                config=config,
                auto_start=True
            )
            
            await keep_alive_cmd.finish(f"✅ Keep-Alive任务已创建: {job_name} (ID: {job_id})\n⏰ 刷新间隔: {interval}分钟\n🚀 任务已自动启动")
            
        else:
            # 显示帮助信息
            help_msg = """📋 Keep-Alive命令帮助:
• !保持活跃 状态 - 查看Keep-Alive任务状态
• !保持活跃 刷新 - 刷新所有用户Cookie
• !保持活跃 刷新 用户名 - 刷新指定用户Cookie
• !保持活跃 创建 任务名 [间隔分钟] - 创建Keep-Alive任务

示例:
• !保持活跃 创建 我的Keep-Alive 15
• !保持活跃 刷新 czq"""
            await keep_alive_cmd.finish(help_msg)
        
    except Exception as e:
        await keep_alive_cmd.finish(f"❌ Keep-Alive操作失败: {str(e)}")
