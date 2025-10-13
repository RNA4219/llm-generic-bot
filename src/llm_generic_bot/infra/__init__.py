from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sys as _sys
from threading import Lock
from typing import Any, Callable, Dict, Iterable, List, Mapping, Protocol, Tuple, runtime_checkable


TagsKey = Tuple[Tuple[str, str], ...]


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


@dataclass(frozen=True)
class _MetricRecord:
    name: str
    recorded_at: datetime
    tags: TagsKey
    kind: str
    value: float


@runtime_checkable
class MetricsService(Protocol):
    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        ...

    async def collect_weekly_snapshot(self) -> WeeklyMetricsSnapshot:
        ...


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
        self._service.record_event(name, tags=tags, measurements={"value": value})


def make_metrics_recorder(service: MetricsService) -> _MetricsRecorderAdapter:
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsService | None,
) -> WeeklyMetricsSnapshot:
    if metrics is None:
        now = _utcnow()
        return WeeklyMetricsSnapshot(
            start=now - timedelta(days=7),
            end=now,
            counters={},
            observations={},
        )
    return await metrics.collect_weekly_snapshot()


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
