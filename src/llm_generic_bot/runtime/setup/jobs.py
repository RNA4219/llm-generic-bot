from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Optional

from ...core.scheduler import Scheduler
from ..jobs import JobContext, ScheduledJob


def register_job(
    scheduler: Scheduler,
    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]],
    job: ScheduledJob,
) -> None:
    jobs[job.name] = job.func
    for hhmm in job.schedules:
        scheduler.every_day(
            job.name,
            hhmm,
            job.func,
            channel=job.channel,
            priority=job.priority,
        )


def install_factories(
    scheduler: Scheduler,
    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]],
    factories: Iterable[Callable[[JobContext], Iterable[ScheduledJob]]],
    context: JobContext,
) -> None:
    for factory in factories:
        for scheduled in factory(context):
            register_job(scheduler, jobs, scheduled)
