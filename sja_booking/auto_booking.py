"""
自动抢票系统
每天中午12点准时开始抢七天后的场地
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .api import SportsAPI
from .models import BookingTarget, PresetOption
from .order import OrderManager, OrderResult
from .database import get_db_manager

try:
    import config as CFG
except ImportError:
    CFG = None


class AutoBookingSystem:
    """自动抢票系统"""
    
    def __init__(self):
        self.api = None
        self.order_manager = None
        self.db_manager = get_db_manager()
        self.is_running = False
        self.booking_targets = []
        self.booking_results = []
        
    async def initialize(self):
        """初始化系统"""
        if not CFG:
            raise RuntimeError("配置模块未找到")
        
        self.api = SportsAPI(
            CFG.BASE_URL, 
            CFG.ENDPOINTS, 
            CFG.AUTH, 
            preset_targets=CFG.PRESET_TARGETS
        )
        self.order_manager = OrderManager(self.api, CFG.ENCRYPTION_CONFIG)
        
        # 加载抢票目标配置
        await self._load_booking_targets()
        
    async def _load_booking_targets(self):
        """加载抢票目标配置"""
        # 从数据库加载配置，如果没有则使用默认配置
        targets = await self.db_manager.load_auto_booking_targets()
        
        if not targets:
            # 使用默认配置
            self.booking_targets = [
                {
                    "preset": 13,  # 南洋北苑健身房
                    "priority": 1,
                    "enabled": True,
                    "time_slots": [18, 19, 20, 21],  # 优先时间段
                    "max_attempts": 3,
                    "description": "南洋北苑健身房"
                },
                {
                    "preset": 5,   # 气膜体育中心羽毛球
                    "priority": 2,
                    "enabled": True,
                    "time_slots": [18, 19, 20],
                    "max_attempts": 3,
                    "description": "气膜体育中心羽毛球"
                },
                {
                    "preset": 18,  # 霍英东体育中心羽毛球
                    "priority": 3,
                    "enabled": True,
                    "time_slots": [18, 19, 20],
                    "max_attempts": 3,
                    "description": "霍英东体育中心羽毛球"
                }
            ]
            # 保存默认配置到数据库
            await self.db_manager.save_auto_booking_targets(self.booking_targets)
        else:
            self.booking_targets = targets
            
    async def start_auto_booking_scheduler(self):
        """启动自动抢票调度器"""
        if self.is_running:
            return {"success": False, "message": "自动抢票系统已在运行"}
        
        self.is_running = True
        
        # 启动调度任务
        asyncio.create_task(self._scheduler_worker())
        
        return {"success": True, "message": "自动抢票调度器已启动"}
    
    async def stop_auto_booking_scheduler(self):
        """停止自动抢票调度器"""
        self.is_running = False
        return {"success": True, "message": "自动抢票调度器已停止"}
    
    async def _scheduler_worker(self):
        """调度器工作线程"""
        while self.is_running:
            try:
                now = datetime.now()
                
                # 检查是否到了抢票时间（12:00:00）
                if now.hour == 12 and now.minute == 0 and now.second < 5:
                    print(f"🕐 到达抢票时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                    await self._execute_auto_booking()
                    
                    # 等待5秒避免重复执行
                    await asyncio.sleep(5)
                else:
                    # 每分钟检查一次
                    await asyncio.sleep(60)
                    
            except Exception as e:
                print(f"❌ 调度器错误: {e}")
                await asyncio.sleep(60)
    
    async def _execute_auto_booking(self):
        """执行自动抢票"""
        print("🚀 开始执行自动抢票...")
        
        # 计算目标日期（7天后）
        target_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        print(f"🎯 目标日期: {target_date}")
        
        # 按优先级排序目标
        enabled_targets = [t for t in self.booking_targets if t.get("enabled", True)]
        enabled_targets.sort(key=lambda x: x.get("priority", 999))
        
        self.booking_results = []
        
        for target in enabled_targets:
            try:
                print(f"🏟️ 尝试抢票: {target['description']} (预设{target['preset']})")
                
                # 执行抢票
                result = await self._book_target(target, target_date)
                self.booking_results.append(result)
                
                # 如果成功，可以选择是否继续尝试其他目标
                if result["success"]:
                    print(f"✅ 抢票成功: {target['description']}")
                    # 可以选择停止或继续
                    # break
                else:
                    print(f"❌ 抢票失败: {target['description']} - {result['message']}")
                    
            except Exception as e:
                print(f"❌ 抢票异常: {target['description']} - {e}")
                self.booking_results.append({
                    "target": target,
                    "success": False,
                    "message": f"异常: {str(e)}",
                    "timestamp": datetime.now().isoformat()
                })
        
        # 保存抢票结果
        await self._save_booking_results(target_date)
        
        print(f"🏁 自动抢票完成，共尝试 {len(self.booking_results)} 个目标")
    
    async def _book_target(self, target: Dict, target_date: str) -> Dict[str, Any]:
        """抢票单个目标"""
        preset = target["preset"]
        time_slots = target.get("time_slots", [18, 19, 20, 21])
        max_attempts = target.get("max_attempts", 3)
        
        # 获取可用时间段
        slots_result = await self._get_available_slots(preset, target_date)
        
        if not slots_result["success"]:
            return {
                "target": target,
                "success": False,
                "message": f"获取时间段失败: {slots_result['message']}",
                "timestamp": datetime.now().isoformat()
            }
        
        slots = slots_result["slots"]
        if not slots:
            return {
                "target": target,
                "success": False,
                "message": "没有可用时间段",
                "timestamp": datetime.now().isoformat()
            }
        
        # 按优先级排序时间段
        prioritized_slots = self._prioritize_slots(slots, time_slots)
        
        # 尝试预订
        for attempt in range(max_attempts):
            for slot in prioritized_slots:
                try:
                    print(f"  🎯 尝试预订: {slot['start']}-{slot['end']} (尝试 {attempt + 1}/{max_attempts})")
                    
                    result = await self.order_manager.place_order_by_preset(
                        preset_index=preset,
                        date=target_date,
                        start_time=slot["start"],
                        end_time=slot["end"]
                    )
                    
                    if result.success:
                        return {
                            "target": target,
                            "success": True,
                            "message": f"预订成功: {slot['start']}-{slot['end']}",
                            "order_id": result.order_id,
                            "slot": slot,
                            "attempt": attempt + 1,
                            "timestamp": datetime.now().isoformat()
                        }
                    else:
                        print(f"    ❌ 预订失败: {result.message}")
                        
                except Exception as e:
                    print(f"    ❌ 预订异常: {e}")
                    continue
            
            # 等待一段时间后重试
            if attempt < max_attempts - 1:
                await asyncio.sleep(1)
        
        return {
            "target": target,
            "success": False,
            "message": f"所有时间段预订失败，已尝试 {max_attempts} 次",
            "timestamp": datetime.now().isoformat()
        }
    
    async def _get_available_slots(self, preset: int, target_date: str) -> Dict[str, Any]:
        """获取可用时间段"""
        try:
            # 创建临时API实例
            temp_api = SportsAPI(
                CFG.BASE_URL, 
                CFG.ENDPOINTS, 
                CFG.AUTH, 
                preset_targets=CFG.PRESET_TARGETS
            )
            
            # 查找预设配置
            preset_config = None
            for p in CFG.PRESET_TARGETS:
                if p.index == preset:
                    preset_config = p
                    break
            
            if not preset_config:
                return {"success": False, "message": f"未找到预设 {preset}"}
            
            # 获取可用时间段
            from .monitor import SlotMonitor
            from .models import BookingTarget, MonitorPlan
            
            target = BookingTarget(
                venue_id=preset_config.venue_id,
                field_type_id=preset_config.field_type_id,
                fixed_dates=[target_date]
            )
            
            monitor = SlotMonitor(temp_api, target, MonitorPlan(enabled=False))
            slots = monitor.run_once(include_full=False)
            
            # 转换为字典格式
            slot_dicts = []
            for date_str, slot in slots:
                if slot.available:
                    slot_dicts.append({
                        "date": date_str,
                        "start": slot.start,
                        "end": slot.end,
                        "remain": slot.remain,
                        "price": slot.price,
                        "available": slot.available
                    })
            
            temp_api.close()
            
            return {"success": True, "slots": slot_dicts}
            
        except Exception as e:
            return {"success": False, "message": f"获取时间段异常: {str(e)}"}
    
    def _prioritize_slots(self, slots: List[Dict], preferred_times: List[int]) -> List[Dict]:
        """按优先级排序时间段"""
        def get_priority(slot):
            try:
                start_hour = int(slot["start"].split(":")[0])
                if start_hour in preferred_times:
                    return preferred_times.index(start_hour)
                else:
                    return 999  # 低优先级
            except:
                return 999
        
        return sorted(slots, key=get_priority)
    
    async def _save_booking_results(self, target_date: str):
        """保存抢票结果"""
        try:
            result_data = {
                "target_date": target_date,
                "execution_time": datetime.now().isoformat(),
                "total_targets": len(self.booking_results),
                "successful_bookings": len([r for r in self.booking_results if r["success"]]),
                "results": self.booking_results
            }
            
            await self.db_manager.save_auto_booking_result(result_data)
            print(f"💾 抢票结果已保存到数据库")
            
        except Exception as e:
            print(f"❌ 保存抢票结果失败: {e}")
    
    async def get_booking_status(self) -> Dict[str, Any]:
        """获取抢票状态"""
        return {
            "is_running": self.is_running,
            "targets_count": len(self.booking_targets),
            "enabled_targets": len([t for t in self.booking_targets if t.get("enabled", True)]),
            "last_results": self.booking_results[-5:] if self.booking_results else []
        }
    
    async def update_booking_targets(self, targets: List[Dict]):
        """更新抢票目标配置"""
        self.booking_targets = targets
        await self.db_manager.save_auto_booking_targets(targets)
        return {"success": True, "message": "抢票目标配置已更新"}


# 全局自动抢票系统实例
_auto_booking_system: Optional[AutoBookingSystem] = None


def get_auto_booking_system() -> AutoBookingSystem:
    """获取自动抢票系统实例"""
    global _auto_booking_system
    if _auto_booking_system is None:
        _auto_booking_system = AutoBookingSystem()
    return _auto_booking_system
