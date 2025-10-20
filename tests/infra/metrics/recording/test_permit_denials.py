from __future__ import annotations

from typing import Callable

import pytest

from llm_generic_bot.infra.metrics import reporting

from tests.infra.metrics import RecordingMetricsLike


@pytest.mark.anyio("asyncio")
async def test_report_permit_denied_records_expected_labels(
    make_recording_metrics: Callable[[], RecordingMetricsLike],
) -> None:
    recorder = make_recording_metrics()
    reporting.configure_backend(recorder)

    reporting.report_permit_denied(
        job="alerts",
        platform="discord",
        channel=None,
        reason="quota_exceeded",
        permit_tags={"rule": "quota"},
    )

    assert recorder.increment_calls == [
        (
            "send.denied",
            {
                "job": "alerts",
                "platform": "discord",
                "channel": "-",
                "reason": "quota_exceeded",
                "rule": "quota",
            },
        )
    ]
