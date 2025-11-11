from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("czq_debug")


def start(label: str) -> float:
    """Record start timestamp for a debug span."""
    timestamp = time.perf_counter()
    logger.info("#CZQ_DEBUG %s start %.6fs", label, timestamp)
    return timestamp


def end(label: str, start_time: float, extra: Optional[str] = None) -> None:
    """Log elapsed time for a debug span."""
    elapsed = time.perf_counter() - start_time
    suffix = f" {extra}" if extra else ""
    logger.info("#CZQ_DEBUG %s elapsed %.6fs%s", label, elapsed, suffix)


def log(label: str, message: str) -> None:
    """Log a single debug message."""
    logger.info("#CZQ_DEBUG %s %s", label, message)
