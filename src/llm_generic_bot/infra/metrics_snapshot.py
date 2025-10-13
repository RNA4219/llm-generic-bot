from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Tuple


TagsKey = Tuple[Tuple[str, str], ...]


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


def materialize_counters(
    data: Mapping[str, Mapping[TagsKey, int]]
) -> dict[str, dict[TagsKey, CounterSnapshot]]:
    materialized: dict[str, dict[TagsKey, CounterSnapshot]] = {}
    for name, series in data.items():
        counters: dict[TagsKey, CounterSnapshot] = {}
        for tags, count in series.items():
            counters[tags] = CounterSnapshot(count=count)
        materialized[name] = counters
    return materialized


def materialize_observations(
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
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "TagsKey",
    "materialize_counters",
    "materialize_observations",
]
