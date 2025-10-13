from __future__ import annotations
from collections.abc import Awaitable
from datetime import datetime, timezone
from importlib import import_module
from typing import TYPE_CHECKING, Any, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .metrics import (
        CounterSnapshot,
        MetricsService,
        ObservationSnapshot,
        WeeklyMetricsSnapshot,
    )


__all__ = [
    "CounterSnapshot",
    "MetricsBackend",
    "MetricsService",
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "collect_weekly_snapshot",
    "make_metrics_recorder",
]


@runtime_checkable
class MetricsBackend(Protocol):
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

    def __init__(self, service: MetricsBackend) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags, measurements={"value": value})


def make_metrics_recorder(service: MetricsBackend) -> _MetricsRecorderAdapter:
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsBackend | None,
) -> WeeklyMetricsSnapshot:
    if metrics is None:
        return _empty_weekly_snapshot()
    result = metrics.collect_weekly_snapshot()
    if isinstance(result, Awaitable):
        return await result
    return result


def __getattr__(name: str) -> Any:
    if name in {"CounterSnapshot", "MetricsService", "ObservationSnapshot", "WeeklyMetricsSnapshot"}:
        module = import_module(__name__ + ".metrics")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def _empty_weekly_snapshot() -> "WeeklyMetricsSnapshot":
    module = import_module(__name__ + ".metrics")
    now = datetime.now(timezone.utc)
    return module.WeeklyMetricsSnapshot(
        start=now,
        end=now,
        counters={},
        observations={},
    )


