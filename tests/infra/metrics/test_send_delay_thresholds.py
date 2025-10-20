from __future__ import annotations

from typing import Callable, Protocol, cast

import pytest

from llm_generic_bot.core.orchestrator import MetricsRecorder
from llm_generic_bot.infra.metrics import reporting


class RecordingMetricsLike(MetricsRecorder, Protocol):
    observe_calls: list[tuple[str, float, dict[str, str]]]


@pytest.mark.anyio("asyncio")
@pytest.mark.parametrize("delay_seconds", [0.25, 3.5, 7.0])
async def test_report_send_delay_tracks_overridden_thresholds(
    delay_seconds: float,
    make_recording_metrics: Callable[[], MetricsRecorder],
) -> None:
    recorder = cast(RecordingMetricsLike, make_recording_metrics())
    reporting.configure_backend(recorder)

    await reporting.report_send_delay(
        job="news",
        platform="discord",
        channel="dispatch",
        delay_seconds=delay_seconds,
    )

    assert recorder.observe_calls == [
        (
            "send.delay_seconds",
            pytest.approx(delay_seconds),
            {"job": "news", "platform": "discord", "channel": "dispatch", "unit": "seconds"},
        )
    ]
