#!/usr/bin/env python3
"""
机器人启动脚本
"""

import os
import sys
import subprocess
from pathlib import Path

def check_catnapqq():
    """检查 CatNapQQ 是否运行"""
    import requests
    
    try:
        # 尝试连接 CatNapQQ HTTP 接口
        response = requests.get("http://127.0.0.1:6099/", timeout=5)
        if response.status_code == 200:
            print("✅ CatNapQQ 正在运行")
            return True
    except:
        pass
    
    print("❌ CatNapQQ 未运行")
    print("请先启动 CatNapQQ，然后重新运行此脚本")
    return False

def check_config():
    """检查配置文件"""
    env_file = Path("bot/.env")
    
    if not env_file.exists():
        print("❌ 配置文件不存在: bot/.env")
        print("请先运行: python setup_catnapqq.py")
        return False
    
    # 检查关键配置
    with open(env_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if "SERVICE_AUTH_COOKIE=your_sjtu_cookie_here" in content:
        print("⚠️  请先配置 SJTU Cookie")
        print("编辑 bot/.env 文件，设置正确的 SERVICE_AUTH_COOKIE")
        return False
    
    print("✅ 配置文件检查通过")
    return True

def start_bot():
    """启动机器人"""
    print("🚀 启动机器人...")
    
    # 切换到 bot 目录
    os.chdir("bot")
    
    try:
        # 启动机器人
        subprocess.run([sys.executable, "bot.py"], check=True)
    except KeyboardInterrupt:
        print("\n👋 机器人已停止")
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动失败: {e}")
        return 1
    
    return 0

def main():
    """主函数"""
    print("🤖 体育预订机器人启动器")
    print("=" * 40)
    
    # 检查 CatNapQQ
    if not check_catnapqq():
        return 1
    
    # 检查配置
    if not check_config():
        return 1
    
    # 启动机器人
    return start_bot()

if __name__ == "__main__":
    sys.exit(main())
