from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable, ContextManager

import pytest

import llm_generic_bot.infra.metrics.aggregator_state as aggregator_state
from llm_generic_bot.infra.metrics import reporting

from tests.infra.metrics import RecordingMetricsLike


@pytest.mark.anyio("asyncio")
async def test_report_send_delay_records_unit_seconds(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)

    await reporting.report_send_delay(
        job="weather",
        platform="discord",
        channel="alerts",
        delay_seconds=1.25,
    )

    assert recorder.observe_calls == [
        (
            "send.delay_seconds",
            pytest.approx(1.25),
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "unit": "seconds",
            },
        )
    ]


def test_weekly_snapshot_trims_outdated_permit_denials(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
    freeze_time_ctx: Callable[[str], ContextManager[None]],
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)
    reporting.set_retention_days(2)

    with freeze_time_ctx("2024-01-01T00:00:00Z"):
        reporting.report_permit_denied(
            job="weather",
            platform="discord",
            channel="alerts",
            reason="quota_exceeded",
            permit_tags={"decision": "deny"},
        )

    with freeze_time_ctx("2024-01-04T00:00:00Z"):
        reporting.report_permit_denied(
            job="weather",
            platform="discord",
            channel="alerts",
            reason="maintenance",
            permit_tags={"decision": "deny"},
        )
        snapshot = reporting.weekly_snapshot()

    assert snapshot["permit_denials"] == [
        {
            "job": "weather",
            "platform": "discord",
            "channel": "alerts",
            "decision": "deny",
            "reason": "maintenance",
        }
    ]


def test_weekly_snapshot_ignores_permit_denials_newer_than_generated_at(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)
    reporting.set_retention_days(2)

    base = datetime(2024, 1, 4, tzinfo=timezone.utc)
    timestamps = deque(
        [
            base - timedelta(days=3),
            base + timedelta(days=1),
            base,
        ]
    )

    def fake_utcnow() -> datetime:
        return timestamps.popleft()

    monkeypatch.setattr(aggregator_state, "_utcnow", fake_utcnow)

    reporting.report_permit_denied(
        job="weather",
        platform="discord",
        channel="alerts",
        reason="old_quota",
        permit_tags={"decision": "deny"},
    )

    reporting.report_permit_denied(
        job="weather",
        platform="discord",
        channel="alerts",
        reason="maintenance",
        permit_tags={"decision": "deny"},
    )

    snapshot = reporting.weekly_snapshot()

    assert snapshot["permit_denials"] == []
    assert aggregator_state._AGGREGATOR._permit_denials == []
