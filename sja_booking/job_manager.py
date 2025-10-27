"""
任务管理系统 - 管理monitor和schedule等长期运行的后台任务
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from rich.console import Console
from rich.table import Table


class JobType(Enum):
    """任务类型"""
    MONITOR = "monitor"
    SCHEDULE = "schedule"
    AUTO_BOOKING = "auto_booking"
    KEEP_ALIVE = "keep_alive"


class JobStatus(Enum):
    """任务状态"""
    PENDING = "pending"      # 等待启动
    RUNNING = "running"      # 运行中
    STOPPED = "stopped"      # 已停止
    FAILED = "failed"        # 失败
    COMPLETED = "completed"  # 已完成


@dataclass
class JobInfo:
    """任务信息"""
    job_id: str
    job_type: JobType
    name: str
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    pid: Optional[int] = None
    config: Dict[str, Any] = None
    error_message: Optional[str] = None
    logs: List[str] = None
    
    def __post_init__(self):
        if self.config is None:
            self.config = {}
        if self.logs is None:
            self.logs = []


class JobManager:
    """任务管理器"""
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".sja" / "jobs"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.data_dir / "jobs.json"
        self.jobs: Dict[str, JobInfo] = {}
        self.console = Console()
        self._load_jobs()
        # 自动恢复失败的KeepAlive任务
        self._auto_recover_jobs()
    
    def _load_jobs(self) -> None:
        """加载任务列表"""
        if self.jobs_file.exists():
            try:
                with open(self.jobs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for job_id, job_data in data.items():
                        # 转换枚举类型
                        job_data['job_type'] = JobType(job_data['job_type'])
                        job_data['status'] = JobStatus(job_data['status'])
                        job_data['created_at'] = datetime.fromisoformat(job_data['created_at'])
                        if job_data.get('started_at'):
                            job_data['started_at'] = datetime.fromisoformat(job_data['started_at'])
                        if job_data.get('stopped_at'):
                            job_data['stopped_at'] = datetime.fromisoformat(job_data['stopped_at'])
                        
                        self.jobs[job_id] = JobInfo(**job_data)
            except Exception as e:
                self.console.print(f"[red]加载任务列表失败: {e}[/red]")
    
    def _save_jobs(self) -> None:
        """保存任务列表"""
        try:
            data = {}
            for job_id, job in self.jobs.items():
                job_dict = asdict(job)
                # 转换枚举为字符串
                job_dict['job_type'] = job.job_type.value
                job_dict['status'] = job.status.value
                job_dict['created_at'] = job.created_at.isoformat()
                if job.started_at:
                    job_dict['started_at'] = job.started_at.isoformat()
                if job.stopped_at:
                    job_dict['stopped_at'] = job.stopped_at.isoformat()
                data[job_id] = job_dict
            
            with open(self.jobs_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.console.print(f"[red]保存任务列表失败: {e}[/red]")
    
    def create_job(
        self,
        job_type: JobType,
        name: str,
        config: Dict[str, Any],
        auto_start: bool = True
    ) -> str:
        """创建新任务"""
        # 生成简单的数字ID，从0开始递增
        if not self.jobs:
            job_id = "0"
        else:
            # 找到最大的数字ID并加1
            max_id = 0
            for existing_id in self.jobs.keys():
                try:
                    num_id = int(existing_id)
                    max_id = max(max_id, num_id)
                except ValueError:
                    # 如果遇到非数字ID，跳过
                    continue
            job_id = str(max_id + 1)
        
        job = JobInfo(
            job_id=job_id,
            job_type=job_type,
            name=name,
            status=JobStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            config=config
        )
        
        self.jobs[job_id] = job
        self._save_jobs()
        
        self.console.print(f"[green]✅ 创建任务: {name} (ID: {job_id})[/green]")
        
        if auto_start:
            self.start_job(job_id)
        
        return job_id
    
    def start_job(self, job_id: str) -> bool:
        """启动任务"""
        if job_id not in self.jobs:
            self.console.print(f"[red]❌ 任务不存在: {job_id}[/red]")
            return False
        
        job = self.jobs[job_id]
        
        if job.status == JobStatus.RUNNING:
            self.console.print(f"[yellow]⚠️  任务已在运行: {job.name}[/yellow]")
            return True
        
        try:
            # 根据任务类型启动不同的进程
            if job.job_type == JobType.MONITOR:
                pid = self._start_monitor_job(job)
            elif job.job_type == JobType.SCHEDULE:
                pid = self._start_schedule_job(job)
            elif job.job_type == JobType.AUTO_BOOKING:
                pid = self._start_auto_booking_job(job)
            elif job.job_type == JobType.KEEP_ALIVE:
                pid = self._start_keep_alive_job(job)
            else:
                raise ValueError(f"不支持的任务类型: {job.job_type}")
            
            job.pid = pid
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            job.stopped_at = None
            job.error_message = None
            
            self._save_jobs()
            self.console.print(f"[green]🚀 任务已启动: {job.name} (PID: {pid})[/green]")
            return True
            
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.stopped_at = datetime.now(timezone.utc)
            self._save_jobs()
            self.console.print(f"[red]❌ 启动任务失败: {e}[/red]")
            return False
    
    def stop_job(self, job_id: str) -> bool:
        """停止任务"""
        if job_id not in self.jobs:
            self.console.print(f"[red]❌ 任务不存在: {job_id}[/red]")
            return False
        
        job = self.jobs[job_id]
        
        if job.status != JobStatus.RUNNING:
            self.console.print(f"[yellow]⚠️  任务未在运行: {job.name}[/yellow]")
            return True
        
        try:
            if job.pid:
                # 尝试优雅停止
                try:
                    os.kill(job.pid, signal.SIGTERM)
                    time.sleep(2)
                    
                    # 检查进程是否还在运行
                    try:
                        os.kill(job.pid, 0)
                        # 进程还在运行，强制终止
                        os.kill(job.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        # 进程已终止
                        pass
                except ProcessLookupError:
                    # 进程不存在
                    pass
            
            job.status = JobStatus.STOPPED
            job.stopped_at = datetime.now(timezone.utc)
            self._save_jobs()
            self.console.print(f"[green]🛑 任务已停止: {job.name}[/green]")
            return True
            
        except Exception as e:
            self.console.print(f"[red]❌ 停止任务失败: {e}[/red]")
            return False
    
    def delete_job(self, job_id: str) -> bool:
        """删除任务"""
        if job_id not in self.jobs:
            self.console.print(f"[red]❌ 任务不存在: {job_id}[/red]")
            return False
        
        job = self.jobs[job_id]
        
        # 如果任务在运行，先停止
        if job.status == JobStatus.RUNNING:
            self.stop_job(job_id)
        
        del self.jobs[job_id]
        self._save_jobs()
        self.console.print(f"[green]🗑️  任务已删除: {job.name}[/green]")
        return True
    
    def delete_all_jobs(self, job_type: Optional[JobType] = None, force: bool = False) -> int:
        """删除所有任务
        
        Args:
            job_type: 指定任务类型，None表示所有类型
            force: 是否强制删除（不询问确认）
            
        Returns:
            删除的任务数量
        """
        jobs_to_delete = list(self.jobs.values())
        
        if job_type:
            jobs_to_delete = [job for job in jobs_to_delete if job.job_type == job_type]
        
        if not jobs_to_delete:
            self.console.print("[yellow]⚠️  没有找到要删除的任务[/yellow]")
            return 0
        
        # 显示要删除的任务列表
        self.console.print(f"[red]⚠️  即将删除 {len(jobs_to_delete)} 个任务:[/red]")
        for job in jobs_to_delete:
            status_color = "green" if job.status == JobStatus.RUNNING else "yellow"
            self.console.print(f"  [{status_color}]{job.name}[/{status_color}] (ID: {job.job_id}) - {job.status.value}")
        
        if not force:
            # 询问确认
            try:
                confirm = input("\n确认删除所有任务？(y/N): ").strip().lower()
                if confirm not in ['y', 'yes']:
                    self.console.print("[yellow]❌ 操作已取消[/yellow]")
                    return 0
            except KeyboardInterrupt:
                self.console.print("\n[yellow]❌ 操作已取消[/yellow]")
                return 0
        
        deleted_count = 0
        for job in jobs_to_delete:
            if self.delete_job(job.job_id):
                deleted_count += 1
        
        self.console.print(f"[green]✅ 已删除 {deleted_count} 个任务[/green]")
        return deleted_count
    
    def list_jobs(self, job_type: Optional[JobType] = None) -> List[JobInfo]:
        """列出任务"""
        jobs = list(self.jobs.values())
        
        if job_type:
            jobs = [job for job in jobs if job.job_type == job_type]
        
        return sorted(jobs, key=lambda x: x.created_at, reverse=True)
    
    def get_job(self, job_id: str) -> Optional[JobInfo]:
        """获取任务信息"""
        return self.jobs.get(job_id)
    
    def get_job_logs(self, job_id: str, lines: int = 50) -> List[str]:
        """获取任务日志"""
        if job_id not in self.jobs:
            return []
        
        job = self.jobs[job_id]
        log_file = self.data_dir / f"{job_id}.log"
        
        if not log_file.exists():
            return []
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return [line.strip() for line in all_lines[-lines:]]
        except Exception:
            return []
    
    def _start_monitor_job(self, job: JobInfo) -> int:
        """启动监控任务"""
        script_path = Path(__file__).parent.parent / "sjtu_sports.py"
        
        cmd = [
            sys.executable,
            str(script_path),
            "job", "monitor",
            "--job-id", job.job_id,
            "--config", json.dumps(job.config)
        ]
        
        # 创建日志文件
        log_file = self.data_dir / f"{job.job_id}.log"
        
        # 启动子进程，将输出重定向到日志文件
        with open(log_file, 'w', encoding='utf-8') as f:
            process = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=Path(__file__).parent.parent
            )
        
        return process.pid
    
    def _start_schedule_job(self, job: JobInfo) -> int:
        """启动定时任务"""
        script_path = Path(__file__).parent.parent / "run_schedule_job.py"
        
        cmd = [
            sys.executable,
            str(script_path),
            "--job-id", job.job_id,
            "--config", json.dumps(job.config)
        ]
        
        # 启动子进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        
        return process.pid
    
    def _start_auto_booking_job(self, job: JobInfo) -> int:
        """启动自动抢票任务"""
        script_path = Path(__file__).parent.parent / "run_auto_booking_job.py"
        
        cmd = [
            sys.executable,
            str(script_path),
            "--job-id", job.job_id,
            "--config", json.dumps(job.config)
        ]
        
        # 启动子进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        
        return process.pid

    def _start_keep_alive_job(self, job: JobInfo) -> int:
        """启动会话保活任务"""
        script_path = Path(__file__).parent.parent / "sjtu_sports.py"

        cmd = [
            sys.executable,
            str(script_path),
            "job",
            "keep_alive",
            "--job-id",
            job.job_id,
            "--config",
            json.dumps(job.config),
        ]

        log_file = self.data_dir / f"{job.job_id}.log"

        with open(log_file, "w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                cmd,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=Path(__file__).parent.parent,
            )

        return process.pid
    
    def show_jobs_table(self, job_type: Optional[JobType] = None) -> None:
        """显示任务表格"""
        jobs = self.list_jobs(job_type)
        
        if not jobs:
            self.console.print("[yellow]📋 没有找到任务[/yellow]")
            return
        
        table = Table(title="📋 任务列表", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="cyan", width=8)
        table.add_column("名称", style="green", width=20)
        table.add_column("类型", style="blue", width=12)
        table.add_column("状态", style="yellow", width=10)
        table.add_column("PID", style="dim", width=8)
        table.add_column("创建时间", style="dim", width=16)
        table.add_column("运行时间", style="dim", width=16)
        
        for job in jobs:
            status_color = {
                JobStatus.PENDING: "yellow",
                JobStatus.RUNNING: "green",
                JobStatus.STOPPED: "red",
                JobStatus.FAILED: "red",
                JobStatus.COMPLETED: "blue"
            }.get(job.status, "white")
            
            pid_str = str(job.pid) if job.pid else "-"
            
            created_str = job.created_at.strftime("%m-%d %H:%M")
            
            if job.started_at:
                if job.status == JobStatus.RUNNING:
                    runtime = datetime.now(timezone.utc) - job.started_at
                    runtime_str = str(runtime).split('.')[0]  # 去掉微秒
                else:
                    runtime = job.stopped_at - job.started_at if job.stopped_at else None
                    runtime_str = str(runtime).split('.')[0] if runtime else "-"
            else:
                runtime_str = "-"
            
            table.add_row(
                job.job_id,
                job.name,
                job.job_type.value,
                f"[{status_color}]{job.status.value}[/{status_color}]",
                pid_str,
                created_str,
                runtime_str
            )
        
        self.console.print(table)
    
    def cleanup_dead_jobs(self) -> int:
        """清理已死亡的任务"""
        cleaned = 0
        
        for job_id, job in list(self.jobs.items()):
            if job.status == JobStatus.RUNNING and job.pid:
                try:
                    # 检查进程是否还在运行
                    os.kill(job.pid, 0)
                except ProcessLookupError:
                    # 进程已死亡
                    job.status = JobStatus.FAILED
                    job.stopped_at = datetime.now(timezone.utc)
                    job.error_message = "进程意外终止"
                    cleaned += 1
        
        if cleaned > 0:
            self._save_jobs()
            self.console.print(f"[green]🧹 清理了 {cleaned} 个已死亡的任务[/green]")
        
        return cleaned
    
    def _auto_recover_jobs(self) -> None:
        """自动恢复失败的KeepAlive任务"""
        recovered = 0
        
        for job_id, job in list(self.jobs.items()):
            if job.job_type == JobType.KEEP_ALIVE and job.status in (JobStatus.FAILED, JobStatus.STOPPED):
                # 检查进程是否真的死亡
                if job.pid:
                    try:
                        os.kill(job.pid, 0)
                        # 进程还在运行，更新状态
                        job.status = JobStatus.RUNNING
                        recovered += 1
                        continue
                    except ProcessLookupError:
                        # 进程已死亡，尝试重启
                        pass
                
                # 尝试重启KeepAlive任务
                try:
                    self.console.print(f"[yellow]🔄 自动恢复KeepAlive任务: {job.name}[/yellow]")
                    self.start_job(job_id)
                    recovered += 1
                except Exception as e:
                    self.console.print(f"[red]❌ 恢复KeepAlive任务失败: {e}[/red]")
        
        if recovered > 0:
            self._save_jobs()
            self.console.print(f"[green]✅ 已恢复 {recovered} 个KeepAlive任务[/green]")
    
    def _start_keep_alive_job(self, job: JobInfo) -> int:
        """启动Keep-Alive任务"""
        script_path = Path(__file__).parent.parent / "sjtu_sports.py"
        
        cmd = [
            sys.executable,
            str(script_path),
            "job", "keep_alive",
            "--job-id", job.job_id,
            "--config", json.dumps(job.config)
        ]
        
        # 创建日志文件
        log_file = self.data_dir / f"{job.job_id}.log"
        
        # 启动子进程，将输出重定向到日志文件
        with open(log_file, 'w', encoding='utf-8') as f:
            process = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=Path(__file__).parent.parent
            )
        
        return process.pid


# 全局任务管理器实例
_job_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    """获取全局任务管理器实例"""
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager
