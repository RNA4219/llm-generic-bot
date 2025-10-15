from __future__ import annotations

import datetime as dt
# NOTE: tests monkeypatch the module-level `dt` alias to control time.
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional, Protocol
import zoneinfo
import anyio

from .arbiter import next_slot
from .queue import CoalesceQueue, QueueBatch
from .types import Sender


class _JobCallable(Protocol):
    async def __call__(self) -> Optional[str]:
        ...


@dataclass(slots=True)
class _ScheduledJob:
    name: str
    hhmm: str
    handler: _JobCallable
    priority: int
    channel: Optional[str]


class Scheduler:
    def __init__(
        self,
        *,
        tz: str = "Asia/Tokyo",
        sender: Optional[Sender] = None,
        queue: Optional[CoalesceQueue] = None,
        jitter_enabled: bool = True,
        jitter_range: tuple[int, int] = (60, 180),
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self.tz = zoneinfo.ZoneInfo(tz)
        self.sender = sender
        self.queue = queue or CoalesceQueue(window_seconds=180.0, threshold=3)
        self.jitter_enabled = jitter_enabled
        self.jitter_range = jitter_range
        self._sleep = sleep
        self._jobs: List[_ScheduledJob] = []
        self._last_dispatch_ts: Optional[float] = None
        self._active_job: Optional[_ScheduledJob] = None

    def every_day(
        self,
        name: str,
        hhmm: str,
        handler: _JobCallable,
        *,
        priority: int = 5,
        channel: Optional[str] = None,
    ) -> None:
        self._jobs.append(_ScheduledJob(name, hhmm, handler, priority, channel))

    async def run_forever(self) -> None:
        while True:
            now = dt.datetime.now(self.tz)
            await self._run_due_jobs(now)
            await self.dispatch_ready_batches(now.timestamp())
            sleep_for = max(0.0, 60.0 - now.second - now.microsecond / 1_000_000)
            await self._sleep(sleep_for)

    async def _run_due_jobs(self, now: dt.datetime) -> None:
        hhmm = now.strftime("%H:%M")
        ts = now.timestamp()
        for job in self._jobs:
            if job.hhmm != hhmm:
                continue
            self._active_job = job
            try:
                result = await job.handler()
            finally:
                self._active_job = None
            if result:
                self.queue.push(
                    result,
                    priority=job.priority,
                    job=job.name,
                    created_at=ts,
                    channel=job.channel,
                )

    async def dispatch_ready_batches(self, now_ts: Optional[float] = None) -> None:
        if now_ts is None:
            now_ts = dt.datetime.now(self.tz).timestamp()
        current = now_ts
        for batch in self.queue.pop_ready(now_ts):
            current = await self._dispatch_batch(batch, current)

    async def _dispatch_batch(self, batch: QueueBatch, reference_ts: float) -> float:
        if self.sender is None:
            raise RuntimeError("Sender is not configured for Scheduler")
        clash = False
        if self._last_dispatch_ts is not None:
            clash = reference_ts <= self._last_dispatch_ts
            if not clash:
                clash = reference_ts - self._last_dispatch_ts < self.queue.window_seconds
        job_name = batch.job
        channel = batch.channel
        text = batch.text
        jitter_range = self._effective_jitter_range()

        target_ts = reference_ts
        if self.jitter_enabled:
            target_ts = next_slot(reference_ts, clash, jitter_range=jitter_range)
        delay = max(0.0, target_ts - reference_ts)
        job = batch.job
        channel = batch.channel
        text = batch.text
        await self._sleep(delay)
        await self.sender.send(text, channel, job=job_name)
        self._last_dispatch_ts = target_ts if delay > 0 else reference_ts
        return target_ts

    def _effective_jitter_range(self) -> tuple[int, int]:
        base_low, base_high = self.jitter_range
        window = self.queue.window_seconds
        if window <= 0.0:
            threshold = getattr(self.queue, "_threshold", None)
            if isinstance(threshold, int) and threshold > 0:
                base_low = min(base_low, threshold)
                upper_candidate = max(base_low, threshold * 2)
                base_high = min(base_high, upper_candidate)
        if base_low > base_high:
            return base_low, base_low
        return base_low, base_high
