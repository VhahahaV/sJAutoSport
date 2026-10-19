from __future__ import annotations

import uvicorn

from .app import app


def run() -> None:
    """Entry point for launching the API with uvicorn."""
    uvicorn.run(
        "web_api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
