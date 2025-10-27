from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sja_booking import service
from sja_booking.job_manager import JobInfo, JobType, get_job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobSummary(BaseModel):
    job_id: str
    name: str
    job_type: str
    status: str
    created_at: datetime
    started_at: Optional[datetime]
    stopped_at: Optional[datetime]
    pid: Optional[int]

    @classmethod
    def from_job(cls, job: JobInfo) -> "JobSummary":
        return cls(
            job_id=job.job_id,
            name=job.name,
            job_type=job.job_type.value,
            status=job.status.value,
            created_at=job.created_at,
            started_at=job.started_at,
            stopped_at=job.stopped_at,
            pid=job.pid,
        )


def _parse_datetime(value: Any) -> datetime:
    parsed = _parse_optional_datetime(value)
    return parsed or datetime.utcnow()


def _parse_optional_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _build_monitor_summaries(monitors: List[Dict[str, Any]]) -> List[JobSummary]:
    results: List[JobSummary] = []
    for monitor in monitors:
        monitor_id = str(monitor.get("id") or monitor.get("monitor_id") or "monitor")
        label = monitor.get("resolved", {}).get("label") if isinstance(monitor.get("resolved"), dict) else None
        name = label or f"监控任务 {monitor_id}"
        # 尝试获取PID
        pid = monitor.get("pid")
        results.append(
            JobSummary(
                job_id=f"monitor:{monitor_id}",
                name=name,
                job_type=JobType.MONITOR.value,
                status=str(monitor.get("status") or "unknown"),
                created_at=_parse_datetime(monitor.get("start_time") or monitor.get("created_at")),
                started_at=_parse_optional_datetime(monitor.get("start_time")),
                stopped_at=_parse_optional_datetime(monitor.get("stop_time")),
                pid=pid,
            )
        )
    return results


def _build_schedule_summaries(schedules: List[Dict[str, Any]]) -> List[JobSummary]:
    results: List[JobSummary] = []
    for schedule in schedules:
        schedule_id = str(schedule.get("id") or schedule.get("job_id") or "schedule")
        name = schedule.get("name") or f"定时任务 {schedule_id}"
        # 尝试获取PID，定时任务可能需要从系统进程获取
        pid = schedule.get("pid")
        results.append(
            JobSummary(
                job_id=f"schedule:{schedule_id}",
                name=name,
                job_type=JobType.SCHEDULE.value,
                status=str(schedule.get("status") or "unknown"),
                created_at=_parse_datetime(schedule.get("created_time") or schedule.get("created_at")),
                started_at=_parse_optional_datetime(schedule.get("next_run") or schedule.get("last_run")),
                stopped_at=_parse_optional_datetime(schedule.get("cancelled_time") or schedule.get("stopped_at")),
                pid=pid,
            )
        )
    return results


@router.get("/", response_model=List[JobSummary])
async def list_jobs(job_type: Optional[JobType] = None) -> List[JobSummary]:
    """List jobs, optionally filtered by type, including in-process monitors/schedules."""
    job_manager = get_job_manager()

    summaries: List[JobSummary] = []
    manager_jobs = job_manager.list_jobs(job_type) if job_type else job_manager.list_jobs()
    summaries.extend(JobSummary.from_job(job) for job in manager_jobs)

    if job_type is None or job_type == JobType.MONITOR:
        monitor_status = await service.monitor_status()
        monitor_entries: List[Dict[str, Any]] = []
        if isinstance(monitor_status.get("monitors"), list):
            monitor_entries = [entry for entry in monitor_status["monitors"] if isinstance(entry, dict)]
        elif isinstance(monitor_status.get("monitor_info"), dict):
            monitor_entries = [monitor_status["monitor_info"]]
        summaries.extend(_build_monitor_summaries(monitor_entries))

    if job_type is None or job_type == JobType.SCHEDULE:
        schedules_payload = await service.list_scheduled_jobs()
        schedule_entries = []
        if isinstance(schedules_payload, dict):
            jobs = schedules_payload.get("jobs")
            if isinstance(jobs, list):
                schedule_entries = [entry for entry in jobs if isinstance(entry, dict)]
        summaries.extend(_build_schedule_summaries(schedule_entries))

    # 如果用户请求了特定类型，需要确保结果只包含该类型
    if job_type:
        summaries = [summary for summary in summaries if summary.job_type == job_type.value]

    return summaries


@router.delete("/all")
def delete_all_jobs(job_type: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """删除所有任务"""
    job_manager = get_job_manager()
    
    # 转换任务类型
    job_type_enum = None
    if job_type:
        try:
            job_type_enum = JobType(job_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的任务类型: {job_type}")
    
    deleted_count = job_manager.delete_all_jobs(job_type_enum, force)
    
    return {
        "success": True,
        "message": f"成功删除 {deleted_count} 个任务",
        "deleted_count": deleted_count
    }
