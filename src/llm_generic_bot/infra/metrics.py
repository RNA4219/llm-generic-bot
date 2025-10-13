from __future__ import annotations

# LEGACY_METRICS_SPLIT_CHECKLIST
# - [x] Extracted service primitives into reusable classes
# - [ ] Replace module-level global aggregator with injectable counterpart
# - [ ] Remove legacy global wrappers once call sites migrate

from collections.abc import Mapping

from ._metrics.aggregator import GlobalMetricsAggregator
from ._metrics.service import (
    CounterSnapshot,
    InMemoryMetricsService,
    MetricsRecorder,
    MetricsService,
    NullMetricsRecorder,
    ObservationSnapshot,
    WeeklyMetricsSnapshot,
    collect_weekly_snapshot as _collect_weekly_snapshot,
    make_metrics_recorder,
)

__all__ = [
    "CounterSnapshot",
    "InMemoryMetricsService",
    "MetricsRecorder",
    "MetricsService",
    "NullMetricsRecorder",
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "collect_weekly_snapshot",
    "configure_backend",
    "make_metrics_recorder",
    "report_permit_denied",
    "report_send_failure",
    "report_send_success",
    "reset_for_test",
    "weekly_snapshot",
]

_AGGREGATOR = GlobalMetricsAggregator()


def configure_backend(recorder: MetricsRecorder | None) -> None:
    _AGGREGATOR.configure_backend(recorder)


async def report_send_success(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    _AGGREGATOR.report_send_success(
        job=job,
        platform=platform,
        channel=channel,
        duration_seconds=duration_seconds,
        permit_tags=permit_tags,
    )


async def report_send_failure(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    error_type: str,
) -> None:
    _AGGREGATOR.report_send_failure(
        job=job,
        platform=platform,
        channel=channel,
        duration_seconds=duration_seconds,
        error_type=error_type,
    )


def report_permit_denied(
    *,
    job: str,
    platform: str,
    channel: str | None,
    reason: str,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    _AGGREGATOR.report_permit_denied(
        job=job,
        platform=platform,
        channel=channel,
        reason=reason,
        permit_tags=permit_tags,
    )


def weekly_snapshot() -> dict[str, object]:
    return _AGGREGATOR.weekly_snapshot()


async def collect_weekly_snapshot(
    metrics: MetricsService | None,
) -> WeeklyMetricsSnapshot:
    return await _collect_weekly_snapshot(metrics)


def reset_for_test() -> None:
    _AGGREGATOR.reset()
