from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable, Dict, Iterable, List, Mapping, Protocol, Tuple

TagsKey = Tuple[Tuple[str, str], ...]
MetricKind = str


def _normalize_tags(tags: Mapping[str, str] | None) -> TagsKey:
    if not tags:
        return ()
    return tuple(sorted(tags.items()))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    def empty(cls, *, now: datetime | None = None) -> "WeeklyMetricsSnapshot":
        reference = now or datetime.now(timezone.utc)
        return cls(start=reference, end=reference, counters={}, observations={})


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


class MetricsService(MetricsRecorder):
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utcnow
        self._lock = Lock()
        self._records: List[_MetricRecord] = []

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
        if measurements:
            value = next(iter(measurements.values()))
            self.observe(name, float(value), tags=tags)
            return
        self.increment(name, tags=tags)

    def collect_weekly_snapshot(self, now: datetime | None = None) -> WeeklyMetricsSnapshot:
        reference = now or self._clock()
        start = reference - timedelta(days=7)
        with self._lock:
            relevant = [r for r in self._records if start <= r.recorded_at <= reference]
            self._records = [r for r in self._records if r.recorded_at >= start]
        counters: Dict[str, Dict[TagsKey, int]] = {}
        observations: Dict[str, Dict[TagsKey, List[float]]] = {}
        for record in relevant:
            if record.kind == "increment":
                counter_metric = counters.get(record.name)
                if counter_metric is None:
                    counter_metric = {}
                    counters[record.name] = counter_metric
                counter_metric[record.tags] = counter_metric.get(record.tags, 0) + 1
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

def _materialize_counters(
    data: Mapping[str, Mapping[TagsKey, int]]
) -> Dict[str, Dict[TagsKey, CounterSnapshot]]:
    return {
        "generated_at": generated,
        "success_rate": success_rate,
        "latency_histogram_seconds": latency,
        "permit_denials": denials,
    }


def reset_for_test() -> None:
    global _backend, _backend_configured
    with _lock:
        _backend = NullMetricsRecorder()
        _backend_configured = False
        for store in (_success, _failure, _histogram, _denials):
            store.clear()
