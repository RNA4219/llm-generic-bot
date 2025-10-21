from __future__ import annotations

from typing import Callable, ContextManager

import pytest

from llm_generic_bot.infra.metrics import reporting

from tests.infra.metrics import RecordingMetricsLike


@pytest.mark.anyio("asyncio")
async def test_report_send_success_records_expected_labels(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)

    await reporting.report_send_success(
        job="weather",
        platform="discord",
        channel="alerts",
        duration_seconds=0.42,
        permit_tags={"decision": "allow"},
    )

    assert recorder.increment_calls == [
        (
            "send.success",
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "decision": "allow",
            },
        )
    ]
    assert recorder.observe_calls == [
        (
            "send.duration",
            pytest.approx(0.42),
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "unit": "seconds",
            },
        )
    ]


@pytest.mark.anyio("asyncio")
async def test_weekly_snapshot_trims_outdated_send_events(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
    freeze_time_ctx: Callable[[str], ContextManager[None]],
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)
    reporting.set_retention_days(2)

    with freeze_time_ctx("2024-01-01T00:00:00Z"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.8,
            permit_tags=None,
        )

    with freeze_time_ctx("2024-01-04T00:00:00Z"):
        await reporting.report_send_failure(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=2.5,
            error_type="timeout",
        )
        snapshot = reporting.weekly_snapshot()

    assert snapshot["success_rate"] == {
        "weather": {"success": 0, "failure": 1, "ratio": 0.0}
    }
    assert snapshot["latency_histogram_seconds"] == {
        "weather": {"3s": 1}
    }


@pytest.mark.anyio("asyncio")
async def test_report_send_success_records_engagement_tags(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)

    await reporting.report_send_success(
        job="weather",
        platform="discord",
        channel="alerts",
        duration_seconds=0.25,
        permit_tags={
            "engagement_score": "0.42",
            "engagement_trend": "0.75",
            "permit_quota": "0.5",
        },
    )

    assert recorder.increment_calls == [
        (
            "send.success",
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "engagement_score": "0.42",
                "engagement_trend": "0.75",
                "permit_quota": "0.5",
            },
        )
    ]
