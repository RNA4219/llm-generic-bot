from __future__ import annotations

from typing import Callable, Protocol, cast

import pytest

from llm_generic_bot.core.orchestrator import MetricsRecorder
from llm_generic_bot.core.queue import CoalesceQueue, QueueBatch
from llm_generic_bot.core.scheduler import Scheduler
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


@pytest.mark.anyio("asyncio")
@pytest.mark.parametrize(
    "jitter_range,threshold",
    [((3, 15), 3), ((6, 6), 1)],
)
async def test_scheduler_records_delay_threshold_metrics(
    make_recording_metrics: Callable[[], MetricsRecorder],
    monkeypatch: pytest.MonkeyPatch,
    jitter_range: tuple[int, int],
    threshold: int,
) -> None:
    recorder = cast(RecordingMetricsLike, make_recording_metrics())

    class _Sender:
        platform = "discord"

        async def send(
            self,
            text: str,
            channel: str | None,
            *,
            job: str | None = None,
        ) -> None:
            del text, channel, job

    queue = CoalesceQueue(window_seconds=0.0, threshold=threshold)
    scheduler = Scheduler(
        sender=_Sender(),
        queue=queue,
        jitter_range=jitter_range,
        metrics=recorder,
    )

    async def _fake_sleep(duration: float) -> None:
        del duration

    monkeypatch.setattr(scheduler, "_sleep", _fake_sleep)

    def _fake_next_slot(
        ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)
    ) -> float:
        if not clash:
            return ts
        return ts + float(jitter_range[0])

    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", _fake_next_slot)

    base_ts = 1_000_000.0
    batch = QueueBatch(
        priority=5,
        text="payload",
        channel="dispatch",
        job="news",
        created_at=base_ts,
        batch_id="one",
    )
    await scheduler._dispatch_batch(batch, reference_ts=base_ts)

    second_batch = QueueBatch(
        priority=5,
        text="payload",
        channel="dispatch",
        job="news",
        created_at=base_ts,
        batch_id="two",
    )
    await scheduler._dispatch_batch(second_batch, reference_ts=base_ts)

    effective_range = scheduler._effective_jitter_range()

    delay_threshold_calls = [
        call
        for call in recorder.observe_calls
        if call[0] == "send.delay_threshold_seconds"
    ]
    batch_threshold_calls = [
        call
        for call in recorder.observe_calls
        if call[0] == "send.batch_threshold_count"
    ]

    expected_min = (
        "send.delay_threshold_seconds",
        float(effective_range[0]),
        {"job": "news", "channel": "dispatch", "bound": "min"},
    )
    expected_max = (
        "send.delay_threshold_seconds",
        float(effective_range[1]),
        {"job": "news", "channel": "dispatch", "bound": "max"},
    )
    expected_threshold = (
        "send.batch_threshold_count",
        float(threshold),
        {"job": "news", "channel": "dispatch"},
    )

    assert any(call == expected_min for call in delay_threshold_calls)
    assert any(call == expected_max for call in delay_threshold_calls)
    assert any(call == expected_threshold for call in batch_threshold_calls)
