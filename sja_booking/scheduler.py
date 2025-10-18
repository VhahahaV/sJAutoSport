from __future__ import annotations

from datetime import time as dt_time
from typing import Callable, Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from tzlocal import get_localzone


def schedule_daily(
    job: Callable[[], None],
    *,
    run_time: dt_time = dt_time(hour=12, minute=0, second=0),
    warmup: Optional[Callable[[], None]] = None,
    warmup_offset_seconds: int = 3,
) -> None:
    tz = get_localzone()
    scheduler = BlockingScheduler(timezone=str(tz))

    if warmup:
        warmup_time = (
            dt_time(
                hour=run_time.hour,
                minute=run_time.minute,
                second=max(run_time.second - warmup_offset_seconds, 0),
            )
            if warmup_offset_seconds and run_time.second >= warmup_offset_seconds
            else dt_time(hour=run_time.hour, minute=run_time.minute, second=0)
        )
        scheduler.add_job(warmup, CronTrigger(hour=warmup_time.hour, minute=warmup_time.minute, second=warmup_time.second))

    scheduler.add_job(job, CronTrigger(hour=run_time.hour, minute=run_time.minute, second=run_time.second))
    scheduler.print_jobs()
    scheduler.start()
