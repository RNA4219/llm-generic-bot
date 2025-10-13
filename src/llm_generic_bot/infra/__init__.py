from __future__ import annotations

import sys as _sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Protocol, TypedDict, TypeVar

import anyio


TagsKey = tuple[tuple[str, str], ...]


class HistogramSnapshot(TypedDict):
    count: int
    min: float
    max: float
    sum: float
    avg: float


class MetricSnapshot(TypedDict, total=False):
    count: int
    measurements: Dict[str, HistogramSnapshot]


class WeeklyMetricsSnapshot(TypedDict):
    start: datetime
    end: datetime
    jobs: Dict[str, Dict[str, MetricSnapshot]]
    tags: Dict[str, Dict[TagsKey, MetricSnapshot]]


class MetricsRecorder(Protocol):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        ...

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        ...


@dataclass(slots=True)
class _MetricEvent:
    recorded_at: datetime
    name: str
    tags: TagsKey
    job: str
    measurements: tuple[tuple[str, float], ...] | None


class MetricsService(MetricsRecorder):
    __slots__ = ("_clock", "_lock", "_async_lock", "_events")

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utcnow
        self._lock = Lock()
        self._async_lock = anyio.Lock()
        self._events: list[_MetricEvent] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self.record_event(name, tags=tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self.record_event(name, tags=tags, measurements={"value": float(value)})

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        del metadata  # 未使用
        tag_items = _normalize_tags(tags)
        measurement_items: tuple[tuple[str, float], ...] | None = None
        if measurements:
            measurement_items = tuple(sorted((key, float(value)) for key, value in measurements.items()))
        event = _MetricEvent(
            recorded_at=self._clock(),
            name=name,
            tags=tag_items,
            job=_extract_job(tag_items),
            measurements=measurement_items,
        )
        with self._lock:
            self._events.append(event)

    def collect_weekly_snapshot(self, now: datetime) -> WeeklyMetricsSnapshot:
        start = now - timedelta(days=7)
        with self._lock:
            relevant = [event for event in self._events if start <= event.recorded_at <= now]
            self._events = [event for event in self._events if event.recorded_at >= start]
        jobs: Dict[str, Dict[str, MetricSnapshot]] = {}
        tags: Dict[str, Dict[TagsKey, MetricSnapshot]] = {}
        for event in relevant:
            _touch_metric(jobs.setdefault(event.job, {}), event.name, event.measurements)
            _touch_metric(tags.setdefault(event.name, {}), event.tags, event.measurements)
        _finalize_measurements(jobs.values())
        _finalize_measurements(tags.values())
        return {
            "start": start,
            "end": now,
            "jobs": jobs,
            "tags": tags,
        }

    async def collect_weekly_snapshot_async(self) -> WeeklyMetricsSnapshot:
        async with self._async_lock:
            return self.collect_weekly_snapshot(self.now())

    def now(self) -> datetime:
        return self._clock()


class _MetricsRecorderAdapter:
    __slots__ = ("_service",)

    def __init__(self, service: MetricsService) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags, measurements={"value": float(value)})


class _NullMetricsRecorder:
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        return None

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        return None


def make_metrics_recorder(service: MetricsService | None = None) -> MetricsRecorder:
    if service is None:
        return _NullMetricsRecorder()
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(metrics: MetricsService | None) -> WeeklyMetricsSnapshot:
    if metrics is None:
        now = _utcnow()
        empty = _empty_snapshot(now)
        return empty
    snapshot = await metrics.collect_weekly_snapshot_async()
    return snapshot


def _empty_snapshot(now: datetime) -> WeeklyMetricsSnapshot:
    start = now - timedelta(days=7)
    return {"start": start, "end": now, "jobs": {}, "tags": {}}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_tags(tags: Mapping[str, str] | None) -> TagsKey:
    if not tags:
        return ()
    return tuple(sorted(tags.items()))


def _extract_job(tags: TagsKey) -> str:
    for key, value in tags:
        if key == "job":
            return value
    return "-"


KT = TypeVar("KT")


def _touch_metric(
    container: MutableMapping[KT, MetricSnapshot],
    key: KT,
    measurements: tuple[tuple[str, float], ...] | None,
) -> None:
    metric = container.get(key)
    if metric is None:
        metric = {"count": 0}
        container[key] = metric
    metric["count"] = metric.get("count", 0) + 1
    if not measurements:
        return
    measurement_map = metric.setdefault("measurements", {})
    for m_key, value in measurements:
        histogram = measurement_map.get(m_key)
        if histogram is None:
            histogram = {"count": 0, "min": value, "max": value, "sum": 0.0, "avg": 0.0}
            measurement_map[m_key] = histogram
        histogram["count"] += 1
        histogram["sum"] += value
        histogram["min"] = min(histogram["min"], value)
        histogram["max"] = max(histogram["max"], value)


def _finalize_measurements(
    containers: Iterable[Mapping[Any, MetricSnapshot]]
) -> None:
    for metrics in containers:
        for metric in metrics.values():
            measurements = metric.get("measurements")
            if not measurements:
                continue
            for histogram in measurements.values():
                histogram["avg"] = histogram["sum"] / histogram["count"]


_sys.modules[__name__ + ".metrics"] = _sys.modules[__name__]
