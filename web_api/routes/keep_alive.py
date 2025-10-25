from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sja_booking.keep_alive import (
    KeepAliveResult,
    run_keep_alive_for_user,
    run_keep_alive_once,
)
from sja_booking.job_manager import JobStatus, JobType, get_job_manager

router = APIRouter(prefix="/keep-alive", tags=["keep-alive"])


class KeepAliveSummary(BaseModel):
    username: Optional[str]
    nickname: Optional[str]
    success: bool
    message: str

    @classmethod
    def from_result(cls, result: KeepAliveResult) -> "KeepAliveSummary":
        return cls(
            username=result.username,
            nickname=result.nickname,
            success=result.success,
            message=result.message,
        )


class KeepAliveRunRequest(BaseModel):
    user: Optional[str] = Field(
        default=None,
        description="Specific username or nickname to refresh. Leave empty to refresh all users.",
    )


class KeepAliveJobRequest(BaseModel):
    name: str = Field(..., description="Job name shown in dashboard and logs.")
    interval_minutes: int = Field(
        default=15,
        ge=1,
        description="Refresh interval in minutes (minimum 1).",
    )
    auto_start: bool = Field(default=True, description="Start the job immediately after creation.")


class KeepAliveJobResponse(BaseModel):
    job_id: str
    name: str
    status: str
    interval_minutes: int
    created_at: datetime
    started_at: Optional[datetime]
    pid: Optional[int]


@router.post("/run", response_model=List[KeepAliveSummary])
async def run_keep_alive(request: KeepAliveRunRequest) -> List[KeepAliveSummary]:
    """Refresh cookies for either all users or a specific user."""
    if request.user:
        result = await run_keep_alive_for_user(request.user)
        return [KeepAliveSummary.from_result(result)]

    results = await run_keep_alive_once()
    return [KeepAliveSummary.from_result(item) for item in results]


@router.get("/jobs", response_model=List[KeepAliveJobResponse])
def list_keep_alive_jobs() -> List[KeepAliveJobResponse]:
    """List all keep-alive jobs tracked by the job manager."""
    job_manager = get_job_manager()
    jobs = job_manager.list_jobs(JobType.KEEP_ALIVE)

    payload: List[KeepAliveJobResponse] = []
    for job in jobs:
        payload.append(
            KeepAliveJobResponse(
                job_id=job.job_id,
                name=job.name,
                status=job.status.value,
                interval_minutes=int(job.config.get("interval_seconds", 900)) // 60,
                created_at=job.created_at,
                started_at=job.started_at,
                pid=job.pid,
            )
        )
    return payload


@router.post("/jobs", response_model=KeepAliveJobResponse, status_code=201)
def create_keep_alive_job(request: KeepAliveJobRequest) -> KeepAliveJobResponse:
    """Create a new keep-alive background job."""
    job_manager = get_job_manager()
    interval_minutes = max(1, request.interval_minutes)
    config: Dict[str, Any] = {"interval_seconds": interval_minutes * 60}

    job_id = job_manager.create_job(
        job_type=JobType.KEEP_ALIVE,
        name=request.name,
        config=config,
        auto_start=request.auto_start,
    )

    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=500, detail="Job creation failed")

    return KeepAliveJobResponse(
        job_id=job.job_id,
        name=job.name,
        status=job.status.value,
        interval_minutes=interval_minutes,
        created_at=job.created_at,
        started_at=job.started_at,
        pid=job.pid,
    )


@router.delete("/jobs/{job_id}", status_code=204)
def delete_keep_alive_job(job_id: str) -> None:
    """Delete keep-alive job if it exists."""
    job_manager = get_job_manager()
    job = job_manager.get_job(job_id)
    if not job or job.job_type != JobType.KEEP_ALIVE:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.RUNNING:
        job_manager.stop_job(job_id)

    job_manager.delete_job(job_id)
