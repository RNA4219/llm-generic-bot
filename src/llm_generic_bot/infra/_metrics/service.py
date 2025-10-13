from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Protocol

TagsKey = tuple[tuple[str, str], ...]
MetricKind = str


def _normalize_tags(tags: Mapping[str, str] | None) -> TagsKey:
    if not tags:
        return ()
    return tuple(sorted(tags.items()))


def _utcnow() -> datetime:
    return datetime.fromtimestamp(time.time(), timezone.utc)


@dataclass(frozen=True)
class CounterSnapshot:
    count: int


@dataclass(frozen=True)
class ObservationSnapshot:
    count: int
    minimum: float
    maximum: float
    total: float
    average: float


@dataclass(frozen=True)
class WeeklyMetricsSnapshot:
    start: datetime
    end: datetime
    counters: Mapping[str, Mapping[TagsKey, CounterSnapshot]]
    observations: Mapping[str, Mapping[TagsKey, ObservationSnapshot]]

    @classmethod
    def empty(cls, *, now: datetime | None = None) -> WeeklyMetricsSnapshot:
        reference = now or _utcnow()
        return cls(start=reference, end=reference, counters={}, observations={})


SnapshotResult = WeeklyMetricsSnapshot | Awaitable[WeeklyMetricsSnapshot]


@dataclass(frozen=True)
class _MetricRecord:
    name: str
    recorded_at: datetime
    tags: TagsKey
    kind: MetricKind
    value: float


class MetricsRecorder(Protocol):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        ...

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        ...


class NullMetricsRecorder(MetricsRecorder):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        return None

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        return None


class MetricsService(MetricsRecorder):
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utcnow
        self._lock = Lock()
        self._records: list[_MetricRecord] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._store(name, 1.0, tags, "increment")

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._store(name, float(value), tags, "observe")

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        _ = metadata
        if measurements:
            value = next(iter(measurements.values()))
            self.observe(name, float(value), tags=tags)
            return
        self.increment(name, tags=tags)

    def collect_weekly_snapshot(
        self, now: datetime | None = None
    ) -> SnapshotResult:
        reference = now or self._clock()
        start = reference - timedelta(days=7)
        with self._lock:
            relevant = [
                record
                for record in self._records
                if start <= record.recorded_at <= reference
            ]
            self._records = [
                record for record in self._records if record.recorded_at >= start
            ]
        counters: dict[str, dict[TagsKey, int]] = {}
        observations: dict[str, dict[TagsKey, list[float]]] = {}
        for record in relevant:
            if record.kind == "increment":
                counter_metric = counters.setdefault(record.name, {})
                counter_metric[record.tags] = counter_metric.get(record.tags, 0) + 1
            elif record.kind == "observe":
                observation_metric = observations.setdefault(record.name, {})
                values = observation_metric.setdefault(record.tags, [])
                values.append(record.value)
        return WeeklyMetricsSnapshot(
            start=start,
            end=reference,
            counters=_materialize_counters(counters),
            observations=_materialize_observations(observations),
        )

    def _store(
        self,
        name: str,
        value: float,
        tags: Mapping[str, str] | None,
        kind: MetricKind,
    ) -> None:
        record = _MetricRecord(
            name=name,
            recorded_at=self._clock(),
            tags=_normalize_tags(tags),
            kind=kind,
            value=value,
        )
        with self._lock:
            self._records.append(record)


class InMemoryMetricsService(MetricsService):
    async def collect_weekly_snapshot(
        self, now: datetime | None = None
    ) -> WeeklyMetricsSnapshot:
        result = super().collect_weekly_snapshot(now=now)
        if isinstance(result, Awaitable):
            return await result
        return result


class _MetricsRecorderAdapter:
    __slots__ = ("_service",)

    def __init__(self, service: MetricsService) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(
        self, name: str, value: float, tags: Mapping[str, str] | None = None
    ) -> None:
        self._service.record_event(
            name, tags=tags, measurements={"value": float(value)}
        )


def make_metrics_recorder(service: MetricsService) -> MetricsRecorder:
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsService | None,
) -> WeeklyMetricsSnapshot:
    if metrics is None:
        return WeeklyMetricsSnapshot.empty()
    result = metrics.collect_weekly_snapshot()
    if isinstance(result, Awaitable):
        return await result
    return result


def _materialize_counters(
    data: Mapping[str, Mapping[TagsKey, int]]
) -> dict[str, dict[TagsKey, CounterSnapshot]]:
    materialized: dict[str, dict[TagsKey, CounterSnapshot]] = {}
    for name, series in data.items():
        counters: dict[TagsKey, CounterSnapshot] = {}
        for tags, count in series.items():
            counters[tags] = CounterSnapshot(count=count)
        materialized[name] = counters
    return materialized


def _materialize_observations(
    data: Mapping[str, Mapping[TagsKey, list[float]]]
) -> dict[str, dict[TagsKey, ObservationSnapshot]]:
    materialized: dict[str, dict[TagsKey, ObservationSnapshot]] = {}
    for name, series in data.items():
        observations: dict[TagsKey, ObservationSnapshot] = {}
        for tags, values in series.items():
            if not values:
                continue
            total = float(sum(values))
            count = len(values)
            observations[tags] = ObservationSnapshot(
                count=count,
                minimum=min(values),
                maximum=max(values),
                total=total,
                average=total / count,
            )
        materialized[name] = observations
    return materialized


__all__ = [
    "CounterSnapshot",
    "InMemoryMetricsService",
    "MetricsRecorder",
    "MetricsService",
    "NullMetricsRecorder",
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "TagsKey",
    "collect_weekly_snapshot",
    "make_metrics_recorder",
]
