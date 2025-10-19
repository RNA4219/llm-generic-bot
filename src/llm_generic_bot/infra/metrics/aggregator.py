from __future__ import annotations

# LEGACY_METRICS_AGGREGATOR_CHECKLIST
# - [x] reporting.py から直接 aggregator_state を参照する  # 2024-06 完了: reporting.py は aggregator_state._AGGREGATOR を直接利用
# - [x] orchestrator_metrics が新ファサードに移行する  # 2024-06 完了: orchestrator_metrics は aggregator_state ベースのファサードで統一
# - [x] tests が aggregator_state を優先的に import する  # 2024-06 完了: テストは aggregator_state を参照する互換レイヤーを使用
# - [x] aggregator_state の純粋関数を aggregator_records へ移管する  # 2025-05 再確認: aggregator_state は状態管理のみに専念
# NOTE: reporting.py・core/orchestrator_metrics.py・関連テストは aggregator_state ベースのファサードへ移行済み。

from typing import Mapping

from .aggregator_state import (
    _AGGREGATOR as _STATE_AGGREGATOR,
    _GlobalMetricsAggregator as _StateGlobalMetricsAggregator,
    _utcnow as _state_utcnow,
)
from .service import MetricsRecorder

_GlobalMetricsAggregator = _StateGlobalMetricsAggregator
_utcnow = _state_utcnow
_AGGREGATOR = _STATE_AGGREGATOR


def configure_backend(recorder: MetricsRecorder | None) -> None:
    _AGGREGATOR.configure_backend(recorder)


def set_retention_days(retention_days: int | None) -> None:
    _AGGREGATOR.set_retention_days(retention_days)


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


def weekly_snapshot() -> dict[str, object]:
    return _AGGREGATOR.weekly_snapshot()


def reset_for_test() -> None:
    _AGGREGATOR.reset()

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
