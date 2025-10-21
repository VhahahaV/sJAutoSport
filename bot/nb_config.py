"""
NoneBot configuration helpers.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


def load_env() -> None:
    """Load environment variables from .env/ env.example."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        env_file = BASE_DIR / "env.example"
    if not env_file.exists():
        return
    with env_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def configure_driver(driver) -> None:
    """Apply configuration values to the initialized NoneBot driver."""
    driver.config.nickname = os.getenv("BOT_NICKNAME", "体育预订助手")

    command_prefix = os.getenv("BOT_COMMAND_PREFIX", "!").strip()
    command_starts = {"/"}
    if command_prefix:
        command_starts.add(command_prefix)
    # 允许无前缀命令，但仅在事件预处理器确认是 @ 机器人的情况下放行
    command_starts.add("")
    driver.config.command_prefix = command_prefix or "/"
    driver.config.command_start = command_starts

    ntqq_ws = os.getenv("NTQQ_WS_URL")
    ntqq_http = os.getenv("NTQQ_HTTP_URL")
    driver.config.onebot_ws_url = ntqq_ws or os.getenv("ONEBOT_WS_URL", "ws://127.0.0.1:6099/onebot/v11/ws")
    driver.config.onebot_http_url = ntqq_http or os.getenv("ONEBOT_HTTP_URL", "http://127.0.0.1:6099")
    driver.config.onebot_access_token = os.getenv("NTQQ_ACCESS_TOKEN") or os.getenv("ONEBOT_ACCESS_TOKEN")

    driver.config.log_level = os.getenv("LOG_LEVEL", "INFO")
    driver.config.log_file = os.getenv("LOG_FILE", "logs/bot.log")

    driver.config.service_base_url = os.getenv("SERVICE_BASE_URL", "https://sports.sjtu.edu.cn")
    driver.config.service_auth_cookie = os.getenv("SERVICE_AUTH_COOKIE", "")

    driver.config.default_monitor_interval = int(os.getenv("DEFAULT_MONITOR_INTERVAL", "240"))
    driver.config.default_auto_book = os.getenv("DEFAULT_AUTO_BOOK", "false").lower() == "true"

    driver.config.default_schedule_hour = int(os.getenv("DEFAULT_SCHEDULE_HOUR", "8"))
    driver.config.default_schedule_minute = int(os.getenv("DEFAULT_SCHEDULE_MINUTE", "0"))

    driver.config.database_url = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")

    driver.config.plugins_dirs = ["bot/plugins"]
    driver.config.plugin_dirs = [str(BASE_DIR / "plugins")]

    superusers = os.getenv("SUPERUSERS", "")
    driver.config.superusers = {ident for ident in superusers.split(",") if ident.strip()}

    whitelist = os.getenv("COMMAND_WHITELIST", "")
    driver.config.command_whitelist = {cmd for cmd in whitelist.split(",") if cmd.strip()}
