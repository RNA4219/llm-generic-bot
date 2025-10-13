from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Awaitable, Callable, Mapping, MutableMapping, Protocol

from .metrics_snapshot import (
    CounterSnapshot as CounterSnapshot,
    ObservationSnapshot as ObservationSnapshot,
    TagsKey,
    WeeklyMetricsSnapshot as WeeklyMetricsSnapshot,
    materialize_counters,
    materialize_observations,
)

MetricKind = str


def normalize_tags(tags: Mapping[str, str] | None) -> TagsKey:
    if not tags:
        return ()
    return tuple(sorted(tags.items()))


def utcnow() -> datetime:
    return datetime.fromtimestamp(time.time(), timezone.utc)


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
        self._clock = clock or utcnow
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
    ) -> WeeklyMetricsSnapshot | Awaitable[WeeklyMetricsSnapshot]:
        reference = now or self._clock()
        start = reference - timedelta(days=7)
        with self._lock:
            relevant = [r for r in self._records if start <= r.recorded_at <= reference]
            self._records = [r for r in self._records if r.recorded_at >= start]
        counters: dict[str, MutableMapping[TagsKey, int]] = {}
        observations: dict[str, MutableMapping[TagsKey, list[float]]] = {}
        for record in relevant:
            if record.kind == "increment":
                counter_metric = counters.get(record.name)
                if counter_metric is None:
                    counter_metric = {}
                    counters[record.name] = counter_metric
                current = counter_metric.get(record.tags, 0)
                counter_metric[record.tags] = current + 1
            elif record.kind == "observe":
                observation_metric = observations.get(record.name)
                if observation_metric is None:
                    observation_metric = {}
                    observations[record.name] = observation_metric
                value_list = observation_metric.get(record.tags)
                if value_list is None:
                    value_list = []
                    observation_metric[record.tags] = value_list
                value_list.append(record.value)
        return WeeklyMetricsSnapshot(
            start=start,
            end=reference,
            counters=materialize_counters(counters),
            observations=materialize_observations(observations),
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
            tags=normalize_tags(tags),
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
        if inspect.isawaitable(result):
            return await result
        return result


class _MetricsRecorderAdapter:
    __slots__ = ("_service",)

    def __init__(self, service: MetricsService) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags, measurements={"value": value})


def make_metrics_recorder(service: MetricsService) -> _MetricsRecorderAdapter:
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsService | None,
) -> WeeklyMetricsSnapshot:
    if metrics is None:
        return WeeklyMetricsSnapshot.empty()
    result = metrics.collect_weekly_snapshot()
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = [
    "CounterSnapshot",
    "InMemoryMetricsService",
    "MetricsRecorder",
    "MetricsService",
    "NullMetricsRecorder",
    "ObservationSnapshot",
    "TagsKey",
    "WeeklyMetricsSnapshot",
    "collect_weekly_snapshot",
    "make_metrics_recorder",
    "normalize_tags",
    "utcnow",
]
