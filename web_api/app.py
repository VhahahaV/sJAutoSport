from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import register_routes


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="SJTU Sports Automation API",
        description="API gateway for SJTU Sports automation services",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup_event():
        """服务启动时自动恢复KeepAlive任务"""
        from sja_booking.job_manager import get_job_manager
        job_manager = get_job_manager()
        job_manager.cleanup_dead_jobs()
        # 自动恢复功能已在构造函数中调用
        # get_job_manager()会自动触发_auto_recover_jobs()

    register_routes(app)
    return app


app = create_app()
