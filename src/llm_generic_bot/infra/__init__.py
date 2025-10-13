from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys as _sys
from typing import Any, Mapping, Protocol, runtime_checkable

from .metrics import (
    CounterSnapshot,
    MetricsService as _InMemoryMetricsService,
    ObservationSnapshot,
    WeeklyMetricsSnapshot,
)


__all__ = [
    "CounterSnapshot",
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "MetricsService",
    "make_metrics_recorder",
    "collect_weekly_snapshot",
]


@runtime_checkable
class MetricsEventService(Protocol):
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


@runtime_checkable
class MetricsRecorderLike(Protocol):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        ...

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        ...


class _MetricsRecorderAdapter:
    __slots__ = ("_service",)

    def __init__(self, service: MetricsEventService) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags, measurements={"value": value})


MetricsService = _InMemoryMetricsService


def make_metrics_recorder(
    service: MetricsService | MetricsEventService,
) -> MetricsRecorderLike:
    if isinstance(service, MetricsService):
        return service
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsService | MetricsEventService | None,
) -> WeeklyMetricsSnapshot:
    if metrics is None:
        return _empty_weekly_snapshot()
    if isinstance(metrics, MetricsService):
        now = datetime.now(timezone.utc)
        return metrics.collect_weekly_snapshot(now)
    return await metrics.collect_weekly_snapshot()


def _empty_weekly_snapshot() -> WeeklyMetricsSnapshot:
    now = datetime.now(timezone.utc)
    return WeeklyMetricsSnapshot(
        start=now - timedelta(days=7),
        end=now,
        counters={},
        observations={},
    )


_sys.modules[__name__ + ".metrics"] = _sys.modules[__name__]
