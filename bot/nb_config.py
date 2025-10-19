"""
NoneBot 配置文件
"""

import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent

# 环境变量加载
def load_env():
    """加载环境变量"""
    env_file = BASE_DIR / "env.example"  # 默认使用示例文件
    if (BASE_DIR / ".env").exists():
        env_file = BASE_DIR / ".env"
    
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

# 加载环境变量
load_env()

# NoneBot 配置
from nonebot import get_driver

driver = get_driver()

# 基础配置
driver.config.nickname = os.getenv("BOT_NICKNAME", "体育预订助手")
driver.config.command_prefix = os.getenv("BOT_COMMAND_PREFIX", "!")

# OneBot / NTQQ 适配器配置
ntqq_ws = os.getenv("NTQQ_WS_URL")
ntqq_http = os.getenv("NTQQ_HTTP_URL")
driver.config.onebot_ws_url = ntqq_ws or os.getenv("ONEBOT_WS_URL", "ws://127.0.0.1:6090/onebot/v11/ws")
driver.config.onebot_http_url = ntqq_http or os.getenv("ONEBOT_HTTP_URL", "http://127.0.0.1:6090")
driver.config.onebot_access_token = os.getenv("NTQQ_ACCESS_TOKEN") or os.getenv("ONEBOT_ACCESS_TOKEN")

# 日志配置
driver.config.log_level = os.getenv("LOG_LEVEL", "INFO")
driver.config.log_file = os.getenv("LOG_FILE", "logs/bot.log")

# 服务层配置
driver.config.service_base_url = os.getenv("SERVICE_BASE_URL", "https://sports.sjtu.edu.cn")
driver.config.service_auth_cookie = os.getenv("SERVICE_AUTH_COOKIE", "")

# 监控配置
driver.config.default_monitor_interval = int(os.getenv("DEFAULT_MONITOR_INTERVAL", "240"))
driver.config.default_auto_book = os.getenv("DEFAULT_AUTO_BOOK", "false").lower() == "true"

# 定时任务配置
driver.config.default_schedule_hour = int(os.getenv("DEFAULT_SCHEDULE_HOUR", "8"))
driver.config.default_schedule_minute = int(os.getenv("DEFAULT_SCHEDULE_MINUTE", "0"))

# 数据库配置
driver.config.database_url = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")

# 插件配置
driver.config.plugins_dirs = ["plugins"]
driver.config.plugin_dirs = [str(BASE_DIR / "plugins")]

# 安全配置
driver.config.superusers = set(os.getenv("SUPERUSERS", "").split(",")) if os.getenv("SUPERUSERS") else set()
driver.config.command_whitelist = set(os.getenv("COMMAND_WHITELIST", "").split(",")) if os.getenv("COMMAND_WHITELIST") else set()
