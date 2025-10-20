from __future__ import annotations

from typing import Callable

import pytest

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
