"""
SJTU Sports Booking Bot entrypoint.
"""

import asyncio
import os
import sys
from pathlib import Path

import nonebot
from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter, Bot
from nonebot.log import default_format

# add project root to sys.path for sja_booking imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.nb_config import configure_driver, load_env

driver = None


def setup_logging(active_driver) -> None:
    log_level = getattr(active_driver.config, "log_level", "INFO")
    log_file = getattr(active_driver.config, "log_file", "logs/bot.log")

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    console_format = (
        "<g>{time:MM-DD HH:mm:ss}</g> "
        "[<lvl>{level}</lvl>] "
        "<c><u>{name}</u></c> | "
        "{message}"
    )

    logger.remove()
    logger.add(
        sys.stderr,
        format=console_format,
        level=log_level,
        colorize=True,
    )
    logger.add(
        log_file,
        format=default_format,
        level=log_level,
        rotation="1 day",
        retention="7 days",
        compression="zip",
    )


def init_bot() -> None:
    global driver

    load_env()
    
    # 根据环境变量选择驱动
    driver_type = os.getenv("DRIVER", "~fastapi")
    if driver_type == "~fastapi":
        nonebot.init(driver="nonebot.drivers.fastapi")
    else:
        nonebot.init()
    
    driver = get_driver()
    configure_driver(driver)
    setup_logging(driver)

    driver.register_adapter(OneBotAdapter)

    @driver.on_bot_connect
    async def _(bot: Bot) -> None:  # pylint: disable=unused-argument
        logger.success("OneBot 连接成功: %s", bot.self_id)

    @driver.on_bot_disconnect
    async def _(bot: Bot) -> None:  # pylint: disable=unused-argument
        logger.warning("OneBot 连接断开: %s", bot.self_id)

    plugins_dir = Path(__file__).parent / "plugins"
    nonebot.load_plugins(str(plugins_dir.resolve()))

    # Ensure hooks are registered (filters, preprocessors, etc.)
    from bot import hooks  # noqa: F401  pylint: disable=unused-import

    from nonebot.matcher import matchers
    from nonebot.plugin import get_loaded_plugins

    total_matchers = sum(len(group) for group in matchers.values())
    plugin_names = ", ".join(
        sorted(plugin.id_ for plugin in get_loaded_plugins())
    ) or "无"

    logger.debug(
        "插件加载完成: %s (匹配器=%s)",
        plugin_names,
        total_matchers,
    )

    logger.info("SJTU Sports Booking Bot 初始化完成")
    logger.info("机器人昵称: %s", getattr(driver.config, "nickname", "体育预订助手"))
    logger.info("命令前缀: %s", getattr(driver.config, "command_prefix", "!"))


def main() -> None:
    """主函数"""
    try:
        init_bot()
        logger.info("正在启动机器人…")
        nonebot.run()
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭机器人…")
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("机器人运行出错: %s", exc)
        raise


if __name__ == "__main__":
    main()
