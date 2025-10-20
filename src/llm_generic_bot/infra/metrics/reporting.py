from __future__ import annotations

from typing import Mapping

from .aggregator_state import _AGGREGATOR
from .service import MetricsRecorder


def configure_backend(recorder: MetricsRecorder | None) -> None:
    _AGGREGATOR.configure_backend(recorder)


def clear_history() -> None:
    _AGGREGATOR.clear_history()


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


async def report_send_delay(
    *,
    job: str,
    platform: str,
    channel: str | None,
    delay_seconds: float,
) -> None:
    _AGGREGATOR.report_send_delay(
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
    _AGGREGATOR.report_permit_denied(
        job=job,
        platform=platform,
        channel=channel,
        reason=reason,
        permit_tags=permit_tags,
    )


async def report_permit_reevaluation(
    *,
    job: str,
    platform: str,
    channel: str | None,
    level: str,
    reason: str | None,
    retry_after_seconds: float,
    decision: str,
) -> None:
    _AGGREGATOR.report_permit_reevaluation(
        job=job,
        platform=platform,
        channel=channel,
        level=level,
        reason=reason,
        retry_after_seconds=retry_after_seconds,
        decision=decision,
    )


def reset_for_test() -> None:
    _AGGREGATOR.reset()


def set_retention_days(retention_days: int | None) -> None:
    _AGGREGATOR.set_retention_days(retention_days)


def weekly_snapshot() -> dict[str, object]:
    return _AGGREGATOR.weekly_snapshot()


__all__ = [
    "configure_backend",
    "clear_history",
    "report_permit_denied",
    "report_permit_reevaluation",
    "report_send_delay",
    "report_send_failure",
    "report_send_success",
    "reset_for_test",
    "set_retention_days",
    "weekly_snapshot",
]
