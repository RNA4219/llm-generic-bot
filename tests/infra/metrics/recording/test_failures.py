from __future__ import annotations

from typing import Callable

import pytest

from llm_generic_bot.infra.metrics import reporting

from tests.infra.metrics import RecordingMetricsLike


@pytest.mark.anyio("asyncio")
async def test_report_send_failure_records_expected_labels(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)

    await reporting.report_send_failure(
        job="weather",
        platform="discord",
        channel="alerts",
        duration_seconds=2.4,
        error_type="http_500",
    )

    assert recorder.increment_calls == [
        (
            "send.failure",
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "error": "http_500",
            },
        )
    ]
    assert recorder.observe_calls == [
        (
            "send.duration",
            pytest.approx(2.4),
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "unit": "seconds",
            },
        )
    ]
