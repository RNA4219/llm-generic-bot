from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


class InMemoryMetricsService:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utcnow
        self._lock = Lock()
        self._records: List[_MetricRecord] = []

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        timestamp = self._clock()
        tag_key = _normalize_tags(tags)
        new_records: List[_MetricRecord] = []
        if measurements:
            for key, raw_value in measurements.items():
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                metric_name = name if key == "value" else f"{name}.{key}"
                new_records.append(
                    _MetricRecord(
                        name=metric_name,
                        recorded_at=timestamp,
                        tags=tag_key,
                        kind="observe",
                        value=value,
                    )
                )
        else:
            new_records.append(
                _MetricRecord(
                    name=name,
                    recorded_at=timestamp,
                    tags=tag_key,
                    kind="increment",
                    value=1.0,
                )
            )
        if not new_records:
            return
        with self._lock:
            self._records.extend(new_records)

    async def collect_weekly_snapshot(self) -> WeeklyMetricsSnapshot:
        now = self._clock()
        start = now - timedelta(days=7)
        with self._lock:
            relevant = [r for r in self._records if start <= r.recorded_at <= now]
            self._records = [r for r in self._records if r.recorded_at >= start]
        counters: Dict[str, Dict[TagsKey, int]] = {}
        observations: Dict[str, Dict[TagsKey, List[float]]] = {}
        for record in relevant:
            if record.kind == "increment":
                counter_metric = counters.setdefault(record.name, {})
                counter_metric[record.tags] = counter_metric.get(record.tags, 0) + 1
            elif record.kind == "observe":
                observation_metric = observations.setdefault(record.name, {})
                value_list = observation_metric.setdefault(record.tags, [])
                value_list.append(record.value)
        return WeeklyMetricsSnapshot(
            start=start,
            end=now,
            counters=_materialize_counters(counters),
            observations=_materialize_observations(observations),
        )


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


def _materialize_counters(
    data: Mapping[str, Mapping[TagsKey, int]]
) -> Dict[str, Dict[TagsKey, CounterSnapshot]]:
    return {
        name: {tags: CounterSnapshot(count=count) for tags, count in per_tags.items()}
        for name, per_tags in data.items()
    }


def _materialize_observations(
    data: Mapping[str, Mapping[TagsKey, Iterable[float]]]
) -> Dict[str, Dict[TagsKey, ObservationSnapshot]]:
    result: Dict[str, Dict[TagsKey, ObservationSnapshot]] = {}
    for name, per_tags in data.items():
        result[name] = {}
        for tags, values in per_tags.items():
            value_list = list(values)
            if not value_list:
                continue
            total = sum(value_list)
            count = len(value_list)
            minimum = min(value_list)
            maximum = max(value_list)
            result[name][tags] = ObservationSnapshot(
                count=count,
                minimum=minimum,
                maximum=maximum,
                total=total,
                average=total / count,
            )
    return result


__all__ = [
    "CounterSnapshot",
    "InMemoryMetricsService",
    "MetricsService",
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "collect_weekly_snapshot",
    "make_metrics_recorder",
]


_sys.modules[__name__ + ".metrics"] = _sys.modules[__name__]
