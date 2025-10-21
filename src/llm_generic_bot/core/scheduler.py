from __future__ import annotations

import datetime as dt
# NOTE: tests monkeypatch the module-level `dt` alias to control time.
from collections import OrderedDict
from dataclasses import dataclass
from importlib import import_module
from typing import Awaitable, Callable, Final, List, Mapping, Optional, Protocol, cast
import zoneinfo
import anyio

from .arbiter.jitter import next_slot
from .queue import CoalesceQueue, QueueBatch
from .types import Sender
from ..infra import metrics as metrics_module


class _JobCallable(Protocol):
    async def __call__(self) -> Optional[str]:
        ...


class _MetricsRecorder(Protocol):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        ...

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        ...


def _resolve_metrics(
    metrics: Optional[_MetricsRecorder],
) -> Optional[_MetricsRecorder]:
    if metrics is not None:
        return metrics
    try:
        aggregator_module = import_module("llm_generic_bot.infra.metrics.aggregator_state")
    except ModuleNotFoundError:
        return None
    aggregator = getattr(aggregator_module, "_AGGREGATOR", None)
    if aggregator is None:
        return None
    configured = bool(getattr(aggregator, "backend_configured", False))
    backend = getattr(aggregator, "backend", None)
    if not configured or backend is None:
        return None
    if hasattr(backend, "increment") and hasattr(backend, "observe"):
        return cast(_MetricsRecorder, backend)
    return None


def _metric_tags(job: str, channel: Optional[str], *, platform: Optional[str]) -> dict[str, str]:
    resolved_platform = platform if platform else "-"
    return {"job": job, "channel": channel or "-", "platform": resolved_platform}


@dataclass(slots=True)
class _ScheduledJob:
    name: str
    hhmm: str
    handler: _JobCallable
    priority: int
    channel: Optional[str]


_JITTER_CAP: Final[tuple[int, int]] = (5, 10)


class Scheduler:
    def __init__(
        self,
        *,
        tz: str = "Asia/Tokyo",
        sender: Optional[Sender] = None,
        queue: Optional[CoalesceQueue] = None,
        jitter_enabled: bool = True,
        jitter_range: tuple[int, int] = (60, 180),
        jitter_range_overridden: bool = False,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
        metrics: Optional[_MetricsRecorder] = None,
    ) -> None:
        self.tz = zoneinfo.ZoneInfo(tz)
        self.sender = sender
        self.queue = queue or CoalesceQueue(window_seconds=180.0, threshold=3)
        self.jitter_enabled = jitter_enabled
        self.jitter_range = jitter_range
        self._jitter_range_overridden = jitter_range_overridden
        self._sleep = sleep
        self._jobs: List[_ScheduledJob] = []
        self._last_dispatch_ts: Optional[float] = None
        self._active_job: Optional[_ScheduledJob] = None
        self._metrics = _resolve_metrics(metrics)
        self._dispatched_batches: OrderedDict[str, float] = OrderedDict()
        self._dispatch_guard_limit = 1024

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
        if self._should_skip_dispatch(batch):
            return reference_ts
        clash = False
        if self._last_dispatch_ts is not None:
            clash = reference_ts <= self._last_dispatch_ts
            if not clash:
                clash = reference_ts - self._last_dispatch_ts < self.queue.window_seconds
        job_name = batch.job
        channel = batch.channel
        text = batch.text
        platform_value = getattr(self.sender, "platform", None)
        platform = platform_value if isinstance(platform_value, str) and platform_value else "-"
        jitter_range = self._effective_jitter_range()
        self._record_delay_metrics(job_name, channel, jitter_range, platform)

        target_ts = reference_ts
        if self.jitter_enabled:
            target_ts = next_slot(reference_ts, clash, jitter_range=jitter_range)
        delay = max(0.0, target_ts - reference_ts)
        if delay > 0.0:
            await metrics_module.report_send_delay(
                job=job_name,
                platform=platform,
                channel=channel,
                delay_seconds=delay,
            )
        await self._sleep(delay)
        await self.sender.send(text, channel, job=job_name)
        self._last_dispatch_ts = target_ts if delay > 0 else reference_ts
        self._record_dispatch(batch)
        return target_ts

    def _effective_jitter_range(self) -> tuple[int, int]:
        base_low, base_high = self.jitter_range
        window = self.queue.window_seconds
        if window <= 0.0:
            threshold = getattr(self.queue, "_threshold", None)
            if isinstance(threshold, int) and threshold > 0:
                adjusted_low = min(base_low, threshold)
                upper_candidate = max(adjusted_low, threshold * 2)
                adjusted_high = min(base_high, upper_candidate)
                base_low, base_high = adjusted_low, adjusted_high
        if base_low > base_high:
            return base_low, base_low
        return base_low, base_high

    def _should_skip_dispatch(self, batch: QueueBatch) -> bool:
        last_batch_seen = self._dispatched_batches.get(batch.batch_id)
        if last_batch_seen is not None and batch.created_at <= last_batch_seen:
            return True
        key = (batch.job, batch.channel)
        last_slot_seen = self._reevaluation_waits.get(key)
        if last_slot_seen is not None and batch.created_at < last_slot_seen:
            return True
        return False

    def _record_dispatch(self, batch: QueueBatch) -> None:
        self._dispatched_batches[batch.batch_id] = batch.created_at
        self._dispatched_batches.move_to_end(batch.batch_id)
        while len(self._dispatched_batches) > self._dispatch_guard_limit:
            self._dispatched_batches.popitem(last=False)
    def _record_delay_metrics(
        self,
        job_name: str,
        channel: Optional[str],
        jitter_range: tuple[int, int],
        platform: str,
    ) -> None:
        if self._metrics is None:
            return
        tags = _metric_tags(job_name, channel, platform=platform)
        min_tags = dict(tags)
        min_tags["bound"] = "min"
        max_tags = dict(tags)
        max_tags["bound"] = "max"
        low, high = jitter_range
        self._metrics.observe(
            "send.delay_threshold_seconds",
            float(low),
            tags=min_tags,
        )
        self._metrics.observe(
            "send.delay_threshold_seconds",
            float(high),
            tags=max_tags,
        )
        threshold_value = getattr(self.queue, "_threshold", None)
        if isinstance(threshold_value, int) and threshold_value > 0:
            self._metrics.observe(
                "send.batch_threshold_count",
                float(threshold_value),
                tags=tags,
            )
