"""
SJTU Sports Booking Bot
体育预订机器人主程序
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加父目录到 Python 路径，以便导入 sja_booking 模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter
from nonebot.log import default_format

# 导入配置
from .nb_config import driver

# 配置日志
def setup_logging():
    """设置日志配置"""
    log_level = getattr(driver.config, "log_level", "INFO")
    log_file = getattr(driver.config, "log_file", "logs/bot.log")
    
    # 创建日志目录
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 配置日志格式
    log_format = (
        "<g>{time:MM-DD HH:mm:ss}</g> "
        "[<lvl>{level}</lvl>] "
        "<c><u>{name}</u></c> | "
        "{message}"
    )
    
    # 配置控制台日志
    logger.remove()
    logger.add(
        sys.stderr,
        format=log_format,
        level=log_level,
        colorize=True,
    )
    
    # 配置文件日志
    logger.add(
        log_file,
        format=default_format,
        level=log_level,
        rotation="1 day",
        retention="7 days",
        compression="zip",
    )


def init_bot():
    """初始化机器人"""
    # 设置日志
    setup_logging()
    
    # 注册适配器
    driver.register_adapter(OneBotAdapter)
    
    # 加载插件
    driver.load_plugins("plugins")
    
    logger.info("SJTU Sports Booking Bot 初始化完成")
    logger.info(f"机器人昵称: {getattr(driver.config, 'nickname', '体育预订助手')}")
    logger.info(f"命令前缀: {getattr(driver.config, 'command_prefix', '!')}")


async def main():
    """主函数"""
    try:
        # 初始化机器人
        init_bot()
        
        # 启动机器人
        logger.info("正在启动机器人...")
        await driver.start()
        
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭机器人...")
    except Exception as e:
        logger.error(f"机器人运行出错: {e}")
        raise
    finally:
        await driver.stop()


if __name__ == "__main__":
    asyncio.run(main())
