"""HTTP head: forward the same commands used by the CLI to one core process."""
import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sja_booking.cli import daemon_action
from sja_booking.daemon import request
from sja_booking.operations import CONTRACTS


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(daemon_action, "start")
    yield
    # Closing the Web head must not stop CLI monitors or session maintenance.


def create_app():
    app = FastAPI(title="SJTU Sports Core Gateway", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/api/schema")
    async def schema():
        return {name: {"description": description, "input": model.model_json_schema()} for name, (model, description) in CONTRACTS.items()}

    @app.get("/api/health")
    async def health():
        try:
            response = await request("daemon.status")
            return {"status": "ok", "core": response["result"]}
        except (OSError, asyncio.TimeoutError):
            return JSONResponse(status_code=503, content={"detail": "核心进程不可用，请运行 sja daemon start"})

    @app.post("/api/core/{operation}")
    async def command(operation: str, payload: dict[str, Any]):
        try:
            response = await request(operation, payload)
        except (OSError, asyncio.TimeoutError, ConnectionError):
            return JSONResponse(status_code=503, content={"detail": "核心连接中断。先检查订单状态，避免重复提交；运行 sja daemon status 排查。"})
        code = response.get("error", {}).get("code")
        status = {"login_required": 401, "invalid_input": 422, "invalid_request": 400, "operation_failed": 502}.get(code, 200)
        return JSONResponse(status_code=status, content=response)

    return app


app = create_app()
