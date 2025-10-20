#!/usr/bin/env python3
"""
CatNapQQ 快速配置脚本
"""

import os
import sys
from pathlib import Path

def create_env_file():
    """创建 .env 配置文件"""
    bot_dir = Path("bot")
    env_file = bot_dir / ".env"
    
    if env_file.exists():
        print("⚠️  .env 文件已存在，是否覆盖？(y/N): ", end="")
        if input().lower() != 'y':
            print("❌ 取消配置")
            return False
    
    print("🔧 开始配置 CatNapQQ 连接...")
    
    # 获取用户输入
    print("\n📋 请输入以下配置信息：")
    
    # CatNapQQ 连接配置
    print("\n1. CatNapQQ 连接配置")
    ws_url = input("   WebSocket URL (默认: ws://127.0.0.1:6099/onebot/v11/ws): ").strip()
    if not ws_url:
        ws_url = "ws://127.0.0.1:6099/onebot/v11/ws"
    
    http_url = input("   HTTP URL (默认: http://127.0.0.1:6099): ").strip()
    if not http_url:
        http_url = "http://127.0.0.1:6099"
    
    access_token = input("   访问令牌 (可选，直接回车跳过): ").strip()
    
    # 机器人配置
    print("\n2. 机器人配置")
    nickname = input("   机器人昵称 (默认: 体育预订助手): ").strip()
    if not nickname:
        nickname = "体育预订助手"
    
    command_prefix = input("   命令前缀 (默认: !): ").strip()
    if not command_prefix:
        command_prefix = "!"
    
    # SJTU 认证配置
    print("\n3. SJTU 认证配置")
    print("   ⚠️  请先登录 https://sports.sjtu.edu.cn 获取 Cookie")
    sjtu_cookie = input("   SJTU Cookie (必需): ").strip()
    
    if not sjtu_cookie:
        print("❌ SJTU Cookie 是必需的，请重新运行脚本")
        return False
    
    # 管理员配置
    print("\n4. 管理员配置")
    superusers = input("   管理员QQ号 (多个用逗号分隔，可选): ").strip()
    
    # 创建 .env 文件内容
    env_content = f"""# CatNapQQ 连接配置
NTQQ_WS_URL={ws_url}
NTQQ_HTTP_URL={http_url}
NTQQ_ACCESS_TOKEN={access_token}

# 机器人配置
BOT_NICKNAME={nickname}
BOT_COMMAND_PREFIX={command_prefix}

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log

# 数据库配置
DATABASE_URL=sqlite:///data/bot.db

# 服务层配置
SERVICE_BASE_URL=https://sports.sjtu.edu.cn
SERVICE_AUTH_COOKIE={sjtu_cookie}

# 监控配置
DEFAULT_MONITOR_INTERVAL=240
DEFAULT_AUTO_BOOK=false

# 定时任务配置
DEFAULT_SCHEDULE_HOUR=8
DEFAULT_SCHEDULE_MINUTE=0

# 安全配置
SUPERUSERS={superusers}
COMMAND_WHITELIST=
"""
    
    # 写入文件
    try:
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        print(f"\n✅ 配置文件已创建: {env_file}")
        return True
        
    except Exception as e:
        print(f"❌ 创建配置文件失败: {e}")
        return False

def create_directories():
    """创建必要的目录"""
    directories = [
        "bot/logs",
        "bot/data",
        "logs",
        "data"
    ]
    
    for dir_path in directories:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        print(f"📁 创建目录: {dir_path}")

def check_dependencies():
    """检查依赖"""
    print("\n🔍 检查依赖...")
    
    # 检查 Python 包
    required_packages = [
        "nonebot2",
        "nonebot-adapter-onebot",
        "httpx",
        "sqlite3"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            if package == "sqlite3":
                import sqlite3
            else:
                __import__(package.replace("-", "_"))
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package}")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️  缺少依赖包: {', '.join(missing_packages)}")
        print("请运行以下命令安装：")
        print("pip install nonebot2 nonebot-adapter-onebot httpx")
        return False
    
    return True

def create_catnapqq_config():
    """创建 CatNapQQ 配置示例"""
    config_content = """# CatNapQQ 配置文件示例
# 请根据实际情况修改以下配置

qq:
  number: "your_qq_number"  # 你的QQ号
  password: "your_qq_password"  # 你的QQ密码

# OneBot 协议配置
onebot:
  ws:
    enabled: true
    host: "0.0.0.0"
    port: 6099
    path: "/onebot/v11/ws"
  http:
    enabled: true
    host: "0.0.0.0"
    port: 6099
    access_token: "your_access_token_here"  # 与 .env 中的一致

# 日志配置
log:
  level: "info"
  file: "logs/catnapqq.log"

# 数据库配置
database:
  type: "sqlite"
  path: "data/catnapqq.db"
"""
    
    config_file = Path("catnapqq_config.yaml")
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(config_content)
    
    print(f"📄 CatNapQQ 配置示例已创建: {config_file}")

def main():
    """主函数"""
    print("🚀 CatNapQQ 快速配置脚本")
    print("=" * 50)
    
    # 检查依赖
    if not check_dependencies():
        print("\n❌ 依赖检查失败，请先安装必要的包")
        return 1
    
    # 创建目录
    create_directories()
    
    # 创建配置文件
    if not create_env_file():
        return 1
    
    # 创建 CatNapQQ 配置示例
    create_catnapqq_config()
    
    print("\n" + "=" * 50)
    print("🎉 配置完成！")
    print("\n📋 下一步操作：")
    print("1. 安装并启动 CatNapQQ")
    print("2. 修改 catnapqq_config.yaml 中的 QQ 账号信息")
    print("3. 启动机器人: cd bot && python bot.py")
    print("\n📚 详细配置指南请查看: docs/guides/CATNAPQQ_SETUP.md")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
