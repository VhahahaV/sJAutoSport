#!/usr/bin/env python3
"""
SJTU体育场馆预订系统 - 统一入口文件
支持所有功能：CLI、Bot、任务管理、热加载等
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))


def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    """设置日志"""
    import logging
    
    # 创建日志目录
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 配置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # 文件处理器（如果指定）
    handlers = [console_handler]
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    # 配置根日志器
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=handlers,
        force=True
    )
    
    return logging.getLogger(__name__)


def check_dependencies():
    """检查依赖"""
    logger = setup_logging()
    
    required_packages = [
        "nonebot2",
        "nonebot-adapter-onebot",
        "httpx",
        "rich",
        "pytesseract",
        "opencv-python",
        "cryptography"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            if package == "nonebot2":
                import nonebot
            elif package == "nonebot-adapter-onebot":
                from nonebot.adapters.onebot.v11 import Adapter
            elif package == "opencv-python":
                import cv2
            else:
                __import__(package.replace("-", "_"))
            logger.debug(f"✅ {package}")
        except ImportError:
            logger.warning(f"❌ {package}")
            missing_packages.append(package)
    
    if missing_packages:
        logger.error(f"缺少依赖包: {', '.join(missing_packages)}")
        logger.error("请运行: pip install -r requirements.txt")
        return False
    
    return True


def run_cli_mode_with_args(cli_args):
    """运行CLI模式（使用参数列表）"""
    logger = setup_logging()
    logger.info("🚀 启动CLI模式...")
    
    # 导入CLI模块
    from sja_booking.cli import build_parser, run_cli
    
    # 创建CLI解析器
    parser = build_parser()
    
    # 解析CLI参数
    try:
        cli_parsed_args = parser.parse_args(cli_args)
    except SystemExit:
        # 如果解析失败，显示帮助信息
        parser.print_help()
        return 1
    
    # 运行CLI
    return run_cli(cli_parsed_args)


def run_bot_mode(args):
    """运行Bot模式"""
    logger = setup_logging()
    logger.info("🤖 启动Bot模式...")
    
    # 检查CatNapQQ连接
    if not check_catnapqq_connection():
        logger.error("❌ CatNapQQ未运行，请先启动CatNapQQ")
        return 1
    
    # 设置环境变量
    if args.hot_reload:
        os.environ["HOT_RELOAD"] = "true"
        logger.info("🔥 热加载模式已启用")
    
    # 导入Bot模块
    if args.hot_reload:
        from bot.run import main_with_hot_reload
        main_with_hot_reload()
    else:
        from bot.run import main
        main()
    
    return 0










def check_catnapqq_connection():
    """检查CatNapQQ连接"""
    # 首先检查 Docker 容器是否在运行
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=napcat", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "napcat" not in result.stdout:
            return False
    except:
        # 如果无法检查 Docker，继续尝试 HTTP 检查
        pass
    
    # 尝试检查 HTTP API（即使未登录也可能返回响应）
    try:
        import requests
        headers = {"Authorization": "Bearer 123456"}
        # 尝试访问根路径或状态端点
        response = requests.get("http://127.0.0.1:3000/", headers=headers, timeout=3)
        # 如果返回 200 或 401（未授权但服务可用），都认为服务可用
        return response.status_code in (200, 401, 403)
    except requests.exceptions.Timeout:
        # 超时可能表示服务未启动
        return False
    except requests.exceptions.ConnectionError:
        # 连接错误可能表示服务未启动
        return False
    except:
        # 其他错误，可能是服务未完全启动，但容器在运行
        # 如果容器在运行，我们仍然允许启动 bot（让 NoneBot 自己处理连接）
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=napcat", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=3
            )
            return "napcat" in result.stdout
        except:
            return False


def run_setup_mode(args):
    """运行设置模式"""
    logger = setup_logging()
    logger.info("🔧 启动设置模式...")
    
    # 导入设置模块
    from setup_catnapqq import main as setup_main
    
    return setup_main()


def run_auto_booking_daemon(args):
    """运行自动抢票守护进程"""
    logger = setup_logging()
    logger.info("🚀 启动自动抢票守护进程...")
    
    # 导入自动抢票模块
    from start_auto_booking import AutoBookingDaemon
    
    async def main():
        daemon = AutoBookingDaemon()
        try:
            await daemon.start()
        except Exception as e:
            logger.error(f"启动失败: {e}")
            return 1
        return 0
    
    return asyncio.run(main())


def build_parser():
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="SJTU体育场馆预订系统 - 统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # CLI模式
  python sjtu_sports.py cli login
  python sjtu_sports.py cli slots --preset 13
  python sjtu_sports.py cli jobs
  
  # Bot模式
  python sjtu_sports.py bot
  python sjtu_sports.py bot --hot-reload
  
  # 任务模式
  python sjtu_sports.py cli create-monitor --name "监控任务" --preset 13 --interval 300
  python sjtu_sports.py cli create-schedule --name "定时任务" --preset 13 --hour 12 --minute 0
  
  # 设置模式
  python sjtu_sports.py setup
  
  # 自动抢票守护进程
  python sjtu_sports.py auto-booking
        """
    )
    
    subparsers = parser.add_subparsers(dest="mode", help="运行模式")
    
    # CLI模式
    cli_parser = subparsers.add_parser("cli", help="命令行界面模式")
    cli_parser.add_argument("command", nargs="*", help="CLI命令和参数")
    
    # Bot模式
    bot_parser = subparsers.add_parser("bot", help="机器人模式")
    bot_parser.add_argument("--hot-reload", action="store_true", help="启用热加载")
    
    # 内部任务模式（不对外暴露）
    job_parser = subparsers.add_parser("job", help="内部任务模式")
    job_parser.add_argument("job_type", choices=["monitor", "schedule", "auto_booking", "keep_alive"], help="任务类型")
    job_parser.add_argument("--job-id", required=True, help="任务ID")
    job_parser.add_argument("--config", required=True, help="任务配置JSON")
    
    # 设置模式
    subparsers.add_parser("setup", help="设置模式")
    
    # 自动抢票守护进程
    subparsers.add_parser("auto-booking", help="自动抢票守护进程")
    
    # 全局选项
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="日志级别")
    parser.add_argument("--log-file", help="日志文件路径")
    parser.add_argument("--check-deps", action="store_true", help="检查依赖")
    
    return parser


def main():
    """主函数"""
    parser = build_parser()
    
    # 特殊处理CLI模式
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        # 对于CLI模式，直接传递所有参数给CLI解析器
        cli_args = sys.argv[2:]  # 跳过 'python sjtu_sports.py cli'
        logger = setup_logging()
        logger.info(f"🔍 CLI参数: {cli_args}")
        return run_cli_mode_with_args(cli_args)
    
    # 其他模式正常解析
    args = parser.parse_args()
    
    # 设置日志
    logger = setup_logging(args.log_level, args.log_file)
    
    # 检查依赖
    if args.check_deps:
        if not check_dependencies():
            return 1
        logger.info("✅ 所有依赖检查通过")
        return 0
    
    # 根据模式运行
    try:
        if args.mode == "bot":
            return run_bot_mode(args)
        elif args.mode == "job":
            return run_job_mode(args)
        elif args.mode == "setup":
            return run_setup_mode(args)
        elif args.mode == "auto-booking":
            return run_auto_booking_daemon(args)
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        logger.info("👋 程序被用户中断")
        return 0
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
        return 1


def run_job_mode(args):
    """运行内部任务模式"""
    logger = setup_logging()
    logger.info("⚙️ 启动内部任务模式...")
    
    try:
        config = json.loads(args.config)
    except json.JSONDecodeError as e:
        logger.error(f"配置解析失败: {e}")
        return 1
    
    # 根据任务类型运行不同的任务
    if args.job_type == "monitor":
        return run_monitor_job(args.job_id, config, logger)
    elif args.job_type == "schedule":
        return run_schedule_job(args.job_id, config, logger)
    elif args.job_type == "auto_booking":
        return run_auto_booking_job(args.job_id, config, logger)
    elif args.job_type == "keep_alive":
        return run_keep_alive_job(args.job_id, config, logger)
    else:
        logger.error(f"不支持的任务类型: {args.job_type}")
        return 1


def run_monitor_job(job_id: str, config: dict, logger):
    """运行监控任务"""
    try:
        logger.info(f"开始运行监控任务: {job_id}")
        
        # 解析配置
        target_config = config.get('target', {})
        plan_config = config.get('plan', {})
        
        # 导入必要模块
        from sja_booking.api import SportsAPI
        from sja_booking.monitor import SlotMonitor
        from sja_booking.models import BookingTarget, MonitorPlan
        import config as CFG
        
        # 创建BookingTarget
        target = BookingTarget(**target_config)
        
        # 创建MonitorPlan
        plan = MonitorPlan(**plan_config)
        
        # 创建API实例
        api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH, preset_targets=CFG.PRESET_TARGETS)
        
        # 创建监控器
        monitor = SlotMonitor(api, target, plan)
        
        logger.info(f"监控目标: {target.venue_keyword} - {target.field_type_keyword}")
        logger.info(f"监控间隔: {plan.interval_seconds}秒")
        logger.info(f"自动预订: {plan.auto_book}")
        
        # 开始监控循环
        monitor.monitor_loop()
        
        logger.info("监控任务正常结束")
        return 0
        
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在退出...")
        return 0
    except Exception as e:
        logger.error(f"监控任务失败: {e}")
        return 1
    finally:
        try:
            api.close()
        except:
            pass


def run_schedule_job(job_id: str, config: dict, logger):
    """运行定时任务"""
    try:
        logger.info(f"开始运行定时任务: {job_id}")
        
        # 解析配置
        target_config = config.get('target', {})
        schedule_config = config.get('schedule', {})
        
        # 导入必要模块
        from sja_booking.api import SportsAPI
        from sja_booking.service import order_once
        from sja_booking.models import BookingTarget
        from sja_booking.multi_user import MultiUserManager
        import config as CFG
        from datetime import datetime, timedelta
        
        # 创建BookingTarget
        target = BookingTarget(**target_config)
        
        # 创建API实例
        api = SportsAPI(CFG.BASE_URL, CFG.ENDPOINTS, CFG.AUTH, preset_targets=CFG.PRESET_TARGETS)
        
        # 处理多用户参数
        multi_user_manager = MultiUserManager(CFG.AUTH)
        target_users = multi_user_manager.get_users_for_booking(target)
        
        if not target_users:
            logger.error("没有可用的用户进行预订")
            return 1
        
        # 计算目标日期和时间
        date_offset = schedule_config.get('date_offset', 1)
        start_hour = schedule_config.get('start_hour', 18)
        
        target_date = datetime.now() + timedelta(days=date_offset)
        date_str = target_date.strftime("%Y-%m-%d")
        start_time = str(start_hour)
        
        logger.info(f"预订日期: {date_str}")
        logger.info(f"预订时间: {start_time}:00")
        logger.info(f"目标用户: {[u.nickname for u in target_users]}")
        
        # 执行预订
        results = []
        for user in target_users:
            try:
                api.switch_to_user(user)
                logger.info(f"使用用户: {user.nickname}")
                
                result = order_once(
                    preset=schedule_config.get('preset'),
                    date=date_str,
                    start_time=start_time,
                    base_target=target,
                    user=user.nickname
                )
                
                results.append({
                    'user': user.nickname,
                    'success': result.success,
                    'message': result.message,
                    'order_id': result.order_id
                })
                
                logger.info(f"用户 {user.nickname} 预订结果: {result.message}")
                
            except Exception as e:
                logger.error(f"用户 {user.nickname} 预订失败: {e}")
                results.append({
                    'user': user.nickname,
                    'success': False,
                    'message': str(e),
                    'order_id': None
                })
        
        # 汇总结果
        success_count = sum(1 for r in results if r['success'])
        total_count = len(results)
        
        logger.info(f"定时任务完成: {success_count}/{total_count} 成功")
        return 0
        
    except Exception as e:
        logger.error(f"定时任务失败: {e}")
        return 1
    finally:
        try:
            api.close()
        except:
            pass


def run_auto_booking_job(job_id: str, config: dict, logger):
    """运行自动抢票任务"""
    try:
        logger.info(f"开始运行自动抢票任务: {job_id}")
        
        # 导入必要模块
        from sja_booking.auto_booking import get_auto_booking_system
        
        # 获取自动抢票系统
        auto_booking = get_auto_booking_system()
        
        # 解析配置
        target_config = config.get('target', {})
        booking_config = config.get('booking', {})
        
        logger.info(f"抢票目标: {target_config}")
        logger.info(f"抢票配置: {booking_config}")
        
        # 启动自动抢票
        auto_booking.start_auto_booking(
            target_config=target_config,
            booking_config=booking_config
        )
        
        logger.info("自动抢票任务正常结束")
        return 0
        
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在退出...")
        return 0
    except Exception as e:
        logger.error(f"自动抢票任务失败: {e}")
        return 1
    finally:
        try:
            auto_booking.stop_auto_booking()
        except:
            pass


def run_keep_alive_job(job_id: str, config: dict, logger):
    """运行Keep-Alive任务"""
    logger.info(f"开始运行Keep-Alive任务: {job_id}")
    
    if "interval_seconds" in config:
        interval_seconds = int(config.get("interval_seconds", 15 * 60))
    else:
        interval_minutes = int(config.get("interval_minutes", 15))
        interval_seconds = max(1, interval_minutes) * 60
    if interval_seconds <= 0:
        interval_seconds = 15 * 60

    import asyncio
    from sja_booking import keep_alive

    stop_event = asyncio.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _request_shutdown():
        if not stop_event.is_set():
            stop_event.set()

    try:
        for signal_name in ("SIGINT", "SIGTERM"):
            if hasattr(signal, signal_name):
                try:
                    loop.add_signal_handler(getattr(signal, signal_name), _request_shutdown)
                except NotImplementedError:
                    # add_signal_handler may not be available on some platforms (e.g., Windows)
                    pass

        loop.run_until_complete(
            keep_alive.keep_alive_loop(
                interval_seconds=interval_seconds,
                stop_event=stop_event,
            )
        )
        logger.info("Keep-Alive任务正常结束")
        return 0
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在退出...")
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"Keep-Alive任务失败: {exc}")
        return 1
    finally:
        stop_event.set()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
