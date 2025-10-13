from __future__ import annotations

import sys as _sys
from typing import Any, Mapping, Protocol, runtime_checkable


WeeklyMetricsSnapshot = Mapping[str, Any]


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
        return {}
    return await metrics.collect_weekly_snapshot()


_sys.modules[__name__ + ".metrics"] = _sys.modules[__name__]
