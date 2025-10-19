#!/usr/bin/env python3
"""
自动抢票系统启动脚本
每天中午12点准时开始抢七天后的场地
"""

import asyncio
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加当前目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from sja_booking.service import start_auto_booking, stop_auto_booking, get_auto_booking_status
from sja_booking.auto_booking import get_auto_booking_system


class AutoBookingDaemon:
    """自动抢票守护进程"""
    
    def __init__(self):
        self.running = False
        self.auto_booking = None
        
    async def start(self):
        """启动守护进程"""
        print("🚀 启动自动抢票守护进程...")
        
        # 初始化自动抢票系统
        self.auto_booking = get_auto_booking_system()
        await self.auto_booking.initialize()
        
        # 启动自动抢票调度器
        result = await self.auto_booking.start_auto_booking_scheduler()
        
        if result["success"]:
            print("✅ 自动抢票系统启动成功")
            print(f"🕐 抢票时间: 每天中午12:00:00")
            print(f"📅 目标日期: 7天后的场地")
            print(f"🎯 系统状态: 运行中")
            
            self.running = True
            
            # 显示下次抢票时间
            now = datetime.now()
            next_booking = now.replace(hour=12, minute=0, second=0, microsecond=0)
            if next_booking <= now:
                next_booking += timedelta(days=1)
            
            print(f"⏰ 下次抢票时间: {next_booking.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏳ 距离下次抢票: {next_booking - now}")
            
            # 设置信号处理
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            
            # 主循环
            await self._main_loop()
        else:
            print(f"❌ 自动抢票系统启动失败: {result.get('message', '未知错误')}")
            return False
    
    async def _main_loop(self):
        """主循环"""
        try:
            while self.running:
                # 每分钟检查一次状态
                await asyncio.sleep(60)
                
                # 显示状态信息
                if datetime.now().minute == 0:  # 每小时显示一次状态
                    status = await self.auto_booking.get_booking_status()
                    print(f"📊 系统状态: 运行中, 目标数量: {status.get('targets_count', 0)}")
                    
        except KeyboardInterrupt:
            print("\n🛑 收到停止信号...")
        except Exception as e:
            print(f"❌ 主循环异常: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """停止守护进程"""
        if self.running:
            print("🛑 正在停止自动抢票系统...")
            
            result = await self.auto_booking.stop_auto_booking_scheduler()
            
            if result["success"]:
                print("✅ 自动抢票系统已停止")
            else:
                print(f"❌ 停止失败: {result.get('message', '未知错误')}")
            
            self.running = False
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\n📡 收到信号 {signum}，准备停止...")
        self.running = False


async def main():
    """主函数"""
    daemon = AutoBookingDaemon()
    
    try:
        await daemon.start()
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 再见！")
        sys.exit(0)
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        sys.exit(1)
