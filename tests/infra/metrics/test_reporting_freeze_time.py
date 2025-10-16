from __future__ import annotations

from typing import Callable, ContextManager, Protocol, cast

import pytest

import llm_generic_bot.infra.metrics.aggregator_state as aggregator_state
from llm_generic_bot.infra.metrics import reporting
from llm_generic_bot.core.orchestrator import MetricsRecorder


class RecordingMetricsLike(Protocol):
    increment_calls: list[tuple[str, dict[str, str]]]
    observe_calls: list[tuple[str, float, dict[str, str]]]


FreezeTime = Callable[[str], ContextManager[None]]


@pytest.mark.anyio("asyncio")
async def test_reset_for_test_restores_defaults(
    freeze_time_ctx: FreezeTime,
    make_recording_metrics: Callable[[], MetricsRecorder],
) -> None:
    recorder = cast(RecordingMetricsLike, make_recording_metrics())
    reporting.configure_backend(recorder)
    reporting.set_retention_days(3)

    with freeze_time_ctx("2025-05-01T00:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.5,
            permit_tags=None,
        )

    assert aggregator_state._AGGREGATOR.retention_days == 3

    reporting.reset_for_test()

    assert aggregator_state._AGGREGATOR.retention_days == 7
    snapshot = reporting.weekly_snapshot()
    assert snapshot["success_rate"] == {}
    assert snapshot["latency_histogram_seconds"] == {}
    assert snapshot["permit_denials"] == []


@pytest.mark.anyio("asyncio")
async def test_metrics_null_backend_falls_back_to_noop(
    freeze_time_ctx: FreezeTime,
) -> None:
    reporting.configure_backend(None)
    with freeze_time_ctx("2025-01-06T09:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.5,
            permit_tags={"decision": "allow"},
        )
        snapshot = reporting.weekly_snapshot()
    assert snapshot == {
        "generated_at": "2025-01-06T09:00:00+00:00",
        "success_rate": {},
        "latency_histogram_seconds": {},
        "permit_denials": [],
    }


@pytest.mark.anyio("asyncio")
async def test_metrics_weekly_snapshot_latency_boundaries(
    freeze_time_ctx: FreezeTime,
    make_recording_metrics: Callable[[], MetricsRecorder],
) -> None:
    recorder = cast(RecordingMetricsLike, make_recording_metrics())
    reporting.configure_backend(recorder)
    with freeze_time_ctx("2025-02-03T00:00:00+00:00"):
        await reporting.report_send_success(
            job="edge",
            platform="web",
            channel="status",
            duration_seconds=1.0,
            permit_tags=None,
        )
        await reporting.report_send_success(
            job="edge",
            platform="web",
            channel="status",
            duration_seconds=1.01,
            permit_tags=None,
        )
        await reporting.report_send_failure(
            job="edge",
            platform="web",
            channel="status",
            duration_seconds=3.5,
            error_type="timeout",
        )
        snapshot = reporting.weekly_snapshot()

    assert snapshot["success_rate"] == {
        "edge": {"success": 2, "failure": 1, "ratio": pytest.approx(2 / 3)}
    }
    assert snapshot["latency_histogram_seconds"] == {
        "edge": {"1s": 1, "3s": 1, ">3s": 1}
    }
    assert snapshot["permit_denials"] == []


@pytest.mark.anyio("asyncio")
async def test_weekly_snapshot_ignores_events_older_than_seven_days(
    freeze_time_ctx: FreezeTime,
    make_recording_metrics: Callable[[], MetricsRecorder],
) -> None:
    recorder = cast(RecordingMetricsLike, make_recording_metrics())
    reporting.configure_backend(recorder)

    with freeze_time_ctx("2025-02-02T12:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.2,
            permit_tags={"decision": "allow"},
        )
        await reporting.report_send_failure(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=2.5,
            error_type="timeout",
        )
        reporting.report_permit_denied(
            job="weather",
            platform="discord",
            channel="alerts",
            reason="old_quota",
            permit_tags={"rule": "legacy"},
        )

    with freeze_time_ctx("2025-02-04T12:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.7,
            permit_tags={"decision": "allow"},
        )

    with freeze_time_ctx("2025-02-08T12:00:00+00:00"):
        await reporting.report_send_failure(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=3.5,
            error_type="timeout",
        )
        reporting.report_permit_denied(
            job="weather",
            platform="discord",
            channel="alerts",
            reason="fresh_quota",
            permit_tags={"rule": "current"},
        )

    with freeze_time_ctx("2025-02-10T12:00:00+00:00"):
        snapshot = reporting.weekly_snapshot()

    assert snapshot["generated_at"] == "2025-02-10T12:00:00+00:00"
    assert snapshot["success_rate"] == {
        "weather": {
            "success": 1,
            "failure": 1,
            "ratio": pytest.approx(0.5),
        }
    }
    assert snapshot["latency_histogram_seconds"] == {
        "weather": {"1s": 1, ">3s": 1}
    }
    assert snapshot["permit_denials"] == [
        {
            "job": "weather",
            "platform": "discord",
            "channel": "alerts",
            "reason": "fresh_quota",
            "rule": "current",
        }
    ]
