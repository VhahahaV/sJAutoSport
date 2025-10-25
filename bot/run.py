#!/usr/bin/env python3
"""
机器人启动脚本
支持热加载模式
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.bot import main

def main_with_hot_reload():
    """带热加载的主函数"""
    # 检查是否启用热加载
    hot_reload = os.getenv("HOT_RELOAD", "false").lower() == "true"
    
    if hot_reload:
        print("🔥 热加载模式已启用")
        print("📁 监控目录: bot/plugins/, sja_booking/")
        print("💡 修改代码后会自动重新加载插件")
        print("⚠️  注意: 某些修改可能需要完全重启")
        print("-" * 50)
        
        # 使用watchdog进行热加载
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            import threading
            import time
            
            class HotReloadHandler(FileSystemEventHandler):
                def __init__(self):
                    self.last_reload = 0
                    self.reload_cooldown = 2  # 2秒冷却时间
                
                def on_modified(self, event):
                    if event.is_directory:
                        return
                    
                    # 只监控Python文件
                    if not event.src_path.endswith('.py'):
                        return
                    
                    current_time = time.time()
                    if current_time - self.last_reload < self.reload_cooldown:
                        return
                    
                    self.last_reload = current_time
                    print(f"\n🔄 检测到文件变化: {event.src_path}")
                    print("🔄 正在重新加载插件...")
                    
                    # 重新加载插件
                    try:
                        import nonebot
                        from nonebot import get_driver
                        
                        # 重新加载插件目录
                        plugins_dir = Path(__file__).parent / "plugins"
                        nonebot.load_plugins(str(plugins_dir.resolve()))
                        
                        print("✅ 插件重新加载完成")
                        
                    except Exception as e:
                        print(f"❌ 重新加载失败: {e}")
                        print("💡 建议完全重启机器人")
            
            # 设置文件监控
            event_handler = HotReloadHandler()
            observer = Observer()
            
            # 监控插件目录
            plugins_dir = Path(__file__).parent / "plugins"
            observer.schedule(event_handler, str(plugins_dir), recursive=True)
            
            # 监控sja_booking目录
            sja_dir = Path(__file__).parent.parent / "sja_booking"
            observer.schedule(event_handler, str(sja_dir), recursive=True)
            
            observer.start()
            
            # 在单独线程中运行机器人
            def run_bot():
                asyncio.run(main())
            
            bot_thread = threading.Thread(target=run_bot, daemon=True)
            bot_thread.start()
            
            try:
                # 主线程保持运行
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n🛑 收到停止信号，正在关闭...")
                observer.stop()
                observer.join()
                
        except ImportError:
            print("❌ watchdog未安装，无法使用热加载功能")
            print("💡 请运行: pip install watchdog")
            print("🔄 回退到普通模式...")
            asyncio.run(main())
    else:
        print("🚀 普通模式启动")
        asyncio.run(main())

if __name__ == "__main__":
    main_with_hot_reload()
