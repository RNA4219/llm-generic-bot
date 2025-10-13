from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable, Dict, Iterable, List, Mapping, Tuple

from llm_generic_bot.core.orchestrator import MetricsRecorder

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


@dataclass(frozen=True)
class _MetricRecord:
    name: str
    recorded_at: datetime
    tags: TagsKey
    kind: MetricKind
    value: float


class MetricsService(MetricsRecorder):
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utcnow
        self._lock = Lock()
        self._records: List[_MetricRecord] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._store(name, 1.0, tags, "increment")

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._store(name, float(value), tags, "observe")

    def collect_weekly_snapshot(self, now: datetime) -> WeeklyMetricsSnapshot:
        start = now - timedelta(days=7)
        with self._lock:
            relevant = [r for r in self._records if start <= r.recorded_at <= now]
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
            end=now,
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
