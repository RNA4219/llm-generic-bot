from __future__ import annotations

from typing import Callable

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
