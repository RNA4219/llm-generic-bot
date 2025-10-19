from __future__ import annotations

from typing import Mapping

from . import aggregator_state
from .service import MetricsRecorder


def configure_backend(recorder: MetricsRecorder | None) -> None:
    aggregator_state._AGGREGATOR.configure_backend(recorder)


def clear_history() -> None:
    aggregator_state._AGGREGATOR.clear_history()


async def report_send_success(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    aggregator_state._AGGREGATOR.report_send_success(
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
    aggregator_state._AGGREGATOR.report_send_failure(
        job=job,
        platform=platform,
        channel=channel,
        duration_seconds=duration_seconds,
        error_type=error_type,
    )


async def report_send_delay(
    *,
    job: str,
    platform: str,
    channel: str | None,
    delay_seconds: float,
) -> None:
    aggregator_state._AGGREGATOR.report_send_delay(
        job=job,
        platform=platform,
        channel=channel,
        delay_seconds=delay_seconds,
    )


def report_permit_denied(
    *,
    job: str,
    platform: str,
    channel: str | None,
    reason: str,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    aggregator_state._AGGREGATOR.report_permit_denied(
        job=job,
        platform=platform,
        channel=channel,
        reason=reason,
        permit_tags=permit_tags,
    )


def reset_for_test() -> None:
    aggregator_state._AGGREGATOR.reset()


def set_retention_days(retention_days: int | None) -> None:
    aggregator_state._AGGREGATOR.set_retention_days(retention_days)


def weekly_snapshot() -> dict[str, object]:
    return aggregator_state._AGGREGATOR.weekly_snapshot()


__all__ = [
    "configure_backend",
    "clear_history",
    "report_permit_denied",
    "report_send_delay",
    "report_send_failure",
    "report_send_success",
    "reset_for_test",
    "set_retention_days",
    "weekly_snapshot",
]
