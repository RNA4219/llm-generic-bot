from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sys as _sys
from threading import Lock
from typing import Any, Awaitable, Callable, Dict, Mapping

from .metrics import (
    CounterSnapshot,
    MetricsService as _SyncMetricsStorage,
    ObservationSnapshot,
    WeeklyMetricsSnapshot,
    _normalize_tags,
    _utcnow,
)

_HISTOGRAM_BUCKETS = (0.5, 1.0)


@dataclass
class _DurationRecord:
    recorded_at: datetime
    tags: tuple[tuple[str, str], ...]
    value: float


class MetricsService:
    __slots__ = ("_clock", "_storage", "_lock", "_durations")

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        clock_fn = clock or _utcnow
        self._clock = clock_fn
        self._storage = _SyncMetricsStorage(clock=clock_fn)
        self._lock = Lock()
        self._durations: list[_DurationRecord] = []

    @classmethod
    def create(
        cls,
        *,
        backend: str | None,
        clock: Callable[[], datetime] | None = None,
    ) -> "MetricsService":
        if backend is None:
            return _NullMetricsService(clock=clock)
        if backend == "inmemory":
            return cls(clock=clock)
        msg = f"unsupported metrics backend: {backend}"
        raise ValueError(msg)

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._storage.increment(name, tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._storage.observe(name, value, tags)

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        measurements = measurements or {}
        tags = tags or {}
        should_update = metadata is None
        if name == "send.success":
            if should_update:
                self._storage.increment(name, tags)
            duration = measurements.get("duration_sec")
            if duration is not None:
                value = float(duration)
                if should_update:
                    self._storage.observe("send.duration.histogram", value, tags)
                self._append_duration(value, tags)
            return
        if name == "send.failure":
            if should_update:
                self._storage.increment(name, tags)
            return
        if name == "send.denied":
            if should_update:
                self._storage.increment(name, tags)
            return
        if "value" in measurements and should_update:
            self._storage.observe(name, float(measurements["value"]), tags)
            return
        if should_update:
            self._storage.increment(name, tags)

    def collect_weekly_snapshot(
        self, now: datetime | None = None
    ) -> WeeklyMetricsSnapshot | Awaitable[Dict[str, Any]]:
        if now is not None:
            return self._storage.collect_weekly_snapshot(now)

        async def _collect() -> Dict[str, Any]:
            end = self._clock()
            start = end - timedelta(days=7)
            durations = self._drain_durations(start, end)
            snapshot = self._storage.collect_weekly_snapshot(end)
            return _build_report(start, end, snapshot, durations)

        return _collect()

    def _append_duration(self, value: float, tags: Mapping[str, str]) -> None:
        normalized = _normalize_tags(tags)
        record = _DurationRecord(self._clock(), normalized, value)
        with self._lock:
            self._durations.append(record)

    def _drain_durations(
        self, start: datetime, end: datetime
    ) -> Dict[tuple[tuple[str, str], ...], list[float]]:
        with self._lock:
            kept: list[_DurationRecord] = []
            grouped: Dict[tuple[tuple[str, str], ...], list[float]] = {}
            for item in self._durations:
                if item.recorded_at < start or item.recorded_at > end:
                    if item.recorded_at >= start:
                        kept.append(item)
                    continue
                kept.append(item)
                grouped.setdefault(item.tags, []).append(item.value)
            self._durations = kept
        return grouped


class _NullMetricsService(MetricsService):
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        super().__init__(clock=clock)

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        return None

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        return None

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        return None

    def collect_weekly_snapshot(
        self, now: datetime | None = None
    ) -> WeeklyMetricsSnapshot | Awaitable[Dict[str, Any]]:
        if now is not None:
            return super().collect_weekly_snapshot(now)

        async def _empty() -> Dict[str, Any]:
            return {}

        return _empty()


class _MetricsRecorderAdapter:
    __slots__ = ("_service",)

    def __init__(self, service: MetricsService) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags, measurements={"value": float(value)})


def make_metrics_recorder(service: MetricsService) -> _MetricsRecorderAdapter:
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsService | None,
) -> Dict[str, Any]:
    if metrics is None:
        return {}
    return await metrics.collect_weekly_snapshot()


def _build_report(
    start: datetime,
    end: datetime,
    snapshot: WeeklyMetricsSnapshot,
    durations: Dict[tuple[tuple[str, str], ...], list[float]],
) -> Dict[str, Any]:
    metrics: Dict[str, list[Dict[str, Any]]] = {}
    denied = snapshot.counters.get("send.denied")
    if denied:
        metrics["send.denied"] = [
            {"tags": dict(tags), "count": counter.count}
            for tags, counter in sorted(denied.items())
        ]
    success = snapshot.counters.get("send.success", {})
    failure = snapshot.counters.get("send.failure", {})
    success_rate: list[Dict[str, Any]] = []
    for tags in sorted({*success.keys(), *failure.keys()}):
        success_count = success.get(tags, CounterSnapshot(0)).count
        failure_count = failure.get(tags, CounterSnapshot(0)).count
        total = success_count + failure_count
        if total == 0:
            continue
        success_rate.append(
            {
                "tags": dict(tags),
                "success": success_count,
                "failure": failure_count,
                "rate": _format_decimal(success_count / total),
            }
        )
    if success_rate:
        metrics["send.success_rate"] = success_rate
    if durations:
        histogram: list[Dict[str, Any]] = []
        for tags, values in sorted(durations.items()):
            sorted_values = sorted(values)
            total = sum(sorted_values)
            count = len(sorted_values)
            idx = 0
            buckets: list[Dict[str, Any]] = []
            for bound in _HISTOGRAM_BUCKETS:
                while idx < count and sorted_values[idx] <= bound:
                    idx += 1
                buckets.append({"le": _format_decimal(bound), "count": idx})
            buckets.append({"le": "+Inf", "count": count})
            histogram.append(
                {
                    "tags": dict(tags),
                    "sum": _format_decimal(total),
                    "count": count,
                    "buckets": buckets,
                }
            )
        metrics["send.duration.histogram"] = histogram
    return {"window": {"start": start.isoformat(), "end": end.isoformat()}, "metrics": metrics}


def _format_decimal(value: float) -> str:
    return f"{value:.3f}"


__all__ = [
    "MetricsService",
    "CounterSnapshot",
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "make_metrics_recorder",
    "collect_weekly_snapshot",
]


_sys.modules[__name__ + ".metrics"] = _sys.modules[__name__]
