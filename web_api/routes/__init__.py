from __future__ import annotations

from fastapi import APIRouter, FastAPI

from . import auth, booking, jobs, keep_alive, system


def register_routes(app: FastAPI) -> None:
    """Attach all routers to FastAPI application."""
    api_router = APIRouter(prefix="/api")

    for router in (system.router, keep_alive.router, jobs.router, booking.router, auth.router):
        api_router.include_router(router)

    app.include_router(api_router)
