from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter

from sja_booking import service

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Return basic application health information."""
    return {"status": "ok"}


@router.get("/status/login")
async def login_status() -> Dict[str, Any]:
    """Expose current login session status."""
    status = service.login_status()

    # ensure datetimes serialisable
    for entry in status.get("users", []):
        expires_at = entry.get("expires_at")
        if isinstance(expires_at, datetime):
            entry["expires_at"] = expires_at.isoformat()
    return status


@router.get("/users/info")
async def users_info() -> Dict[str, Any]:
    """Return detailed profile information for stored users."""
    records = await service.fetch_user_infos()
    return {"users": records}
