"""
数据库模块
提供 SQLite 数据库持久化支持
"""

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import BookingTarget


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_path: str = "data/bot.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建监控任务表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monitors (
                    id TEXT PRIMARY KEY,
                    preset INTEGER,
                    venue_id TEXT,
                    venue_keyword TEXT,
                    field_type_id TEXT,
                    field_type_keyword TEXT,
                    date TEXT,
                    start_hour INTEGER,
                    interval_seconds INTEGER,
                    operating_start_hour INTEGER,
                    operating_end_hour INTEGER,
                    auto_book BOOLEAN,
                    status TEXT,
                    start_time TEXT,
                    last_check TEXT,
                    found_slots TEXT,
                    booking_attempts INTEGER,
                    successful_bookings INTEGER,
                    last_error TEXT,
                    last_booking_error TEXT,
                    window_active BOOLEAN,
                    next_window_start TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)

            cursor.execute("PRAGMA table_info(monitors)")
            monitor_columns = {row[1] for row in cursor.fetchall()}
            if "operating_start_hour" not in monitor_columns:
                cursor.execute("ALTER TABLE monitors ADD COLUMN operating_start_hour INTEGER")
            if "operating_end_hour" not in monitor_columns:
                cursor.execute("ALTER TABLE monitors ADD COLUMN operating_end_hour INTEGER")
            if "window_active" not in monitor_columns:
                cursor.execute("ALTER TABLE monitors ADD COLUMN window_active BOOLEAN")
            if "next_window_start" not in monitor_columns:
                cursor.execute("ALTER TABLE monitors ADD COLUMN next_window_start TEXT")
            
            # 创建定时任务表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    hour INTEGER,
                    minute INTEGER,
                    second INTEGER,
                    preset INTEGER,
                    venue_id TEXT,
                    venue_keyword TEXT,
                    field_type_id TEXT,
                    field_type_keyword TEXT,
                    date TEXT,
                    start_hour INTEGER,
                    status TEXT,
                    created_time TEXT,
                    last_run TEXT,
                    next_run TEXT,
                    run_count INTEGER,
                    success_count INTEGER,
                    last_error TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # 创建预订记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS booking_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT,
                    preset INTEGER,
                    venue_name TEXT,
                    field_type_name TEXT,
                    date TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    status TEXT,
                    message TEXT,
                    created_at TEXT
                )
            """)
            
            # 创建验证码记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS verification_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT,
                    status TEXT,
                    created_at TEXT,
                    used_at TEXT
                )
            """)
            
            # 创建自动抢票目标表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auto_booking_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    preset INTEGER,
                    priority INTEGER,
                    enabled BOOLEAN,
                    time_slots TEXT,
                    max_attempts INTEGER,
                    description TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # 创建自动抢票结果表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auto_booking_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_date TEXT,
                    execution_time TEXT,
                    total_targets INTEGER,
                    successful_bookings INTEGER,
                    results TEXT,
                    created_at TEXT
                )
            """)
            
            conn.commit()
    
    async def save_monitor(self, monitor_info: Dict[str, Any]) -> bool:
        """保存监控任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 序列化复杂字段
                found_slots = json.dumps(monitor_info.get("found_slots", []))
                base_target = json.dumps(monitor_info.get("base_target", {}).__dict__ if monitor_info.get("base_target") else {})
                
                cursor.execute("""
                    INSERT OR REPLACE INTO monitors (
                        id, preset, venue_id, venue_keyword, field_type_id, field_type_keyword,
                        date, start_hour, interval_seconds, operating_start_hour, operating_end_hour,
                        auto_book, status, start_time,
                        last_check, found_slots, booking_attempts, successful_bookings,
                        last_error, last_booking_error, window_active, next_window_start,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    monitor_info["id"],
                    monitor_info.get("preset"),
                    monitor_info.get("venue_id"),
                    monitor_info.get("venue_keyword"),
                    monitor_info.get("field_type_id"),
                    monitor_info.get("field_type_keyword"),
                    monitor_info.get("date"),
                    monitor_info.get("start_hour"),
                    monitor_info.get("interval_seconds"),
                    monitor_info.get("operating_start_hour"),
                    monitor_info.get("operating_end_hour"),
                    monitor_info.get("auto_book", False),
                    monitor_info.get("status"),
                    monitor_info.get("start_time"),
                    monitor_info.get("last_check"),
                    found_slots,
                    monitor_info.get("booking_attempts", 0),
                    monitor_info.get("successful_bookings", 0),
                    monitor_info.get("last_error"),
                    monitor_info.get("last_booking_error"),
                    monitor_info.get("window_active"),
                    monitor_info.get("next_window_start"),
                    datetime.now().isoformat(),
                    datetime.now().isoformat()
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"保存监控任务失败: {e}")
            return False
    
    async def load_monitor(self, monitor_id: str) -> Optional[Dict[str, Any]]:
        """加载监控任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM monitors WHERE id = ?", (monitor_id,))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                # 构建字段名
                columns = [description[0] for description in cursor.description]
                
                # 构建结果字典
                monitor_info = dict(zip(columns, row))
                
                # 反序列化复杂字段
                if monitor_info.get("found_slots"):
                    monitor_info["found_slots"] = json.loads(monitor_info["found_slots"])
                
                return monitor_info
                
        except Exception as e:
            print(f"加载监控任务失败: {e}")
            return None
    
    async def load_all_monitors(self) -> List[Dict[str, Any]]:
        """加载所有监控任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM monitors")
                rows = cursor.fetchall()
                
                # 构建字段名
                columns = [description[0] for description in cursor.description]
                
                monitors = []
                for row in rows:
                    monitor_info = dict(zip(columns, row))
                    
                    # 反序列化复杂字段
                    if monitor_info.get("found_slots"):
                        monitor_info["found_slots"] = json.loads(monitor_info["found_slots"])
                    
                    monitors.append(monitor_info)
                
                return monitors
                
        except Exception as e:
            print(f"加载所有监控任务失败: {e}")
            return []
    
    async def delete_monitor(self, monitor_id: str) -> bool:
        """删除监控任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            print(f"删除监控任务失败: {e}")
            return False
    
    async def save_scheduled_job(self, job_info: Dict[str, Any]) -> bool:
        """保存定时任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO scheduled_jobs (
                        id, hour, minute, second, preset, venue_id, venue_keyword,
                        field_type_id, field_type_keyword, date, start_hour, status,
                        created_time, last_run, next_run, run_count, success_count,
                        last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_info["id"],
                    job_info.get("hour"),
                    job_info.get("minute"),
                    job_info.get("second"),
                    job_info.get("preset"),
                    job_info.get("venue_id"),
                    job_info.get("venue_keyword"),
                    job_info.get("field_type_id"),
                    job_info.get("field_type_keyword"),
                    job_info.get("date"),
                    job_info.get("start_hour"),
                    job_info.get("status"),
                    job_info.get("created_time"),
                    job_info.get("last_run"),
                    job_info.get("next_run"),
                    job_info.get("run_count", 0),
                    job_info.get("success_count", 0),
                    job_info.get("last_error"),
                    datetime.now().isoformat(),
                    datetime.now().isoformat()
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"保存定时任务失败: {e}")
            return False
    
    async def load_scheduled_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """加载定时任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                # 构建字段名
                columns = [description[0] for description in cursor.description]
                
                # 构建结果字典
                job_info = dict(zip(columns, row))
                
                return job_info
                
        except Exception as e:
            print(f"加载定时任务失败: {e}")
            return None
    
    async def load_all_scheduled_jobs(self) -> List[Dict[str, Any]]:
        """加载所有定时任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM scheduled_jobs")
                rows = cursor.fetchall()
                
                # 构建字段名
                columns = [description[0] for description in cursor.description]
                
                jobs = []
                for row in rows:
                    job_info = dict(zip(columns, row))
                    jobs.append(job_info)
                
                return jobs
                
        except Exception as e:
            print(f"加载所有定时任务失败: {e}")
            return []
    
    async def delete_scheduled_job(self, job_id: str) -> bool:
        """删除定时任务"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            print(f"删除定时任务失败: {e}")
            return False
    
    async def save_booking_record(self, order_id: str, preset: int, venue_name: str, 
                                field_type_name: str, date: str, start_time: str, 
                                end_time: str, status: str, message: str) -> bool:
        """保存预订记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO booking_records (
                        order_id, preset, venue_name, field_type_name, date,
                        start_time, end_time, status, message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id, preset, venue_name, field_type_name, date,
                    start_time, end_time, status, message, datetime.now().isoformat()
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"保存预订记录失败: {e}")
            return False
    
    async def save_verification_code(self, code: str, status: str = "pending") -> bool:
        """保存验证码"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO verification_codes (
                        code, status, created_at
                    ) VALUES (?, ?, ?)
                """, (code, status, datetime.now().isoformat()))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"保存验证码失败: {e}")
            return False
    
    async def mark_verification_code_used(self, code: str) -> bool:
        """标记验证码为已使用"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE verification_codes 
                    SET status = 'used', used_at = ?
                    WHERE code = ? AND status = 'pending'
                """, (datetime.now().isoformat(), code))
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            print(f"标记验证码失败: {e}")
            return False
    
    async def save_auto_booking_targets(self, targets: List[Dict[str, Any]]) -> bool:
        """保存自动抢票目标配置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 清空现有配置
                cursor.execute("DELETE FROM auto_booking_targets")
                
                # 插入新配置
                for target in targets:
                    cursor.execute("""
                        INSERT INTO auto_booking_targets (
                            preset, priority, enabled, time_slots, max_attempts,
                            description, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        target.get("preset"),
                        target.get("priority", 1),
                        target.get("enabled", True),
                        json.dumps(target.get("time_slots", [])),
                        target.get("max_attempts", 3),
                        target.get("description", ""),
                        datetime.now().isoformat(),
                        datetime.now().isoformat()
                    ))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"保存自动抢票目标失败: {e}")
            return False
    
    async def load_auto_booking_targets(self) -> List[Dict[str, Any]]:
        """加载自动抢票目标配置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM auto_booking_targets ORDER BY priority")
                rows = cursor.fetchall()
                
                # 构建字段名
                columns = [description[0] for description in cursor.description]
                
                targets = []
                for row in rows:
                    target = dict(zip(columns, row))
                    
                    # 反序列化复杂字段
                    if target.get("time_slots"):
                        target["time_slots"] = json.loads(target["time_slots"])
                    
                    targets.append(target)
                
                return targets
                
        except Exception as e:
            print(f"加载自动抢票目标失败: {e}")
            return []
    
    async def save_auto_booking_result(self, result_data: Dict[str, Any]) -> bool:
        """保存自动抢票结果"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO auto_booking_results (
                        target_date, execution_time, total_targets, successful_bookings,
                        results, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    result_data.get("target_date"),
                    result_data.get("execution_time"),
                    result_data.get("total_targets", 0),
                    result_data.get("successful_bookings", 0),
                    json.dumps(result_data.get("results", [])),
                    datetime.now().isoformat()
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"保存自动抢票结果失败: {e}")
            return False
    
    async def load_auto_booking_results(self, limit: int = 10) -> List[Dict[str, Any]]:
        """加载自动抢票结果"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM auto_booking_results 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                # 构建字段名
                columns = [description[0] for description in cursor.description]
                
                results = []
                for row in rows:
                    result = dict(zip(columns, row))
                    
                    # 反序列化复杂字段
                    if result.get("results"):
                        result["results"] = json.loads(result["results"])
                    
                    results.append(result)
                
                return results
                
        except Exception as e:
            print(f"加载自动抢票结果失败: {e}")
            return []


# 全局数据库管理器实例
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """获取数据库管理器实例"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
