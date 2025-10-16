from __future__ import annotations

from typing import Callable, ContextManager, Protocol, cast

from datetime import datetime, timedelta, timezone

import pytest

import llm_generic_bot.infra.metrics.aggregator_state as aggregator_state
from llm_generic_bot.core.orchestrator import MetricsRecorder
from llm_generic_bot.infra.metrics import reporting


class RecordingMetricsLike(Protocol):
    increment_calls: list[tuple[str, dict[str, str]]]
    observe_calls: list[tuple[str, float, dict[str, str]]]


@pytest.mark.anyio("asyncio")
async def test_metrics_records_expected_labels_and_snapshot(
    freeze_time_ctx: Callable[[str], ContextManager[None]],
    make_recording_metrics: Callable[[], MetricsRecorder],
) -> None:
    recorder = cast(RecordingMetricsLike, make_recording_metrics())
    reporting.configure_backend(recorder)
    with freeze_time_ctx("2025-01-06T12:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.42,
            permit_tags={"decision": "allow"},
        )
        await reporting.report_send_failure(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=2.4,
            error_type="http_500",
        )
        reporting.report_permit_denied(
            job="alerts",
            platform="discord",
            channel=None,
            reason="quota_exceeded",
            permit_tags={"rule": "quota"},
        )
        snapshot = reporting.weekly_snapshot()
    assert recorder.increment_calls == [
        ("send.success", {"job": "weather", "platform": "discord", "channel": "alerts", "decision": "allow"}),
        ("send.failure", {"job": "weather", "platform": "discord", "channel": "alerts", "error": "http_500"}),
        (
            "send.denied",
            {
                "job": "alerts",
                "platform": "discord",
                "channel": "-",
                "reason": "quota_exceeded",
                "rule": "quota",
            },
        ),
    ]
    assert recorder.observe_calls == [
        (
            "send.duration",
            pytest.approx(0.42),
            {"job": "weather", "platform": "discord", "channel": "alerts", "unit": "seconds"},
        ),
        (
            "send.duration",
            pytest.approx(2.4),
            {"job": "weather", "platform": "discord", "channel": "alerts", "unit": "seconds"},
        ),
    ]
    assert snapshot == {
        "generated_at": "2025-01-06T12:00:00+00:00",
        "success_rate": {"weather": {"success": 1, "failure": 1, "ratio": 0.5}},
        "latency_histogram_seconds": {"weather": {"1s": 1, "3s": 1}},
        "permit_denials": [
            {
                "job": "alerts",
                "platform": "discord",
                "channel": "-",
                "reason": "quota_exceeded",
                "rule": "quota",
            }
        ],
    }


@pytest.mark.anyio("asyncio")
async def test_configure_backend_reconfiguration_uses_latest_backend(
    freeze_time_ctx: Callable[[str], ContextManager[None]],
    make_recording_metrics: Callable[[], MetricsRecorder],
) -> None:
    first = cast(RecordingMetricsLike, make_recording_metrics())
    second = cast(RecordingMetricsLike, make_recording_metrics())

    reporting.configure_backend(first)
    with freeze_time_ctx("2025-04-01T00:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.25,
            permit_tags={"decision": "allow"},
        )

    reporting.configure_backend(second)
    with freeze_time_ctx("2025-04-02T00:00:00+00:00"):
        await reporting.report_send_failure(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=1.5,
            error_type="timeout",
        )

    with freeze_time_ctx("2025-04-03T00:00:00+00:00"):
        snapshot = reporting.weekly_snapshot()

    assert first.increment_calls == [
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
    assert first.observe_calls == [
        (
            "send.duration",
            pytest.approx(0.25),
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "unit": "seconds",
            },
        )
    ]
    assert second.increment_calls == [
        (
            "send.failure",
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "error": "timeout",
            },
        )
    ]
    assert second.observe_calls == [
        (
            "send.duration",
            pytest.approx(1.5),
            {
                "job": "weather",
                "platform": "discord",
                "channel": "alerts",
                "unit": "seconds",
            },
        )
    ]
    assert snapshot["success_rate"] == {
        "weather": {
            "success": 1,
            "failure": 1,
            "ratio": pytest.approx(0.5),
        }
    }
    assert snapshot["latency_histogram_seconds"] == {
        "weather": {"1s": 1, "3s": 1}
    }
    assert snapshot["permit_denials"] == []


@pytest.mark.anyio("asyncio")
async def test_weekly_snapshot_retention_survives_backend_reconfiguration(
    make_recording_metrics: Callable[[], MetricsRecorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_time = datetime(2025, 4, 10, tzinfo=timezone.utc)
    current = {"value": base_time}

    monkeypatch.setattr(
        aggregator_state,
        "_utcnow",
        lambda: current["value"],
    )

    reporting.set_retention_days(3)

    first = cast(RecordingMetricsLike, make_recording_metrics())
    second = cast(RecordingMetricsLike, make_recording_metrics())

    reporting.configure_backend(first)

    current["value"] = base_time - timedelta(days=4)
    await reporting.report_send_success(
        job="weather",
        platform="discord",
        channel="alerts",
        duration_seconds=0.4,
        permit_tags={"decision": "allow"},
    )

    reporting.configure_backend(second)

    current["value"] = base_time
    await reporting.report_send_success(
        job="weather",
        platform="discord",
        channel="alerts",
        duration_seconds=0.6,
        permit_tags={"decision": "allow"},
    )

    current["value"] = base_time
    snapshot = reporting.weekly_snapshot()

    assert len(first.increment_calls) == 1
    assert len(second.increment_calls) == 1
    assert snapshot["success_rate"] == {
        "weather": {
            "success": 1,
            "failure": 0,
            "ratio": pytest.approx(1.0),
        }
    }
    assert snapshot["latency_histogram_seconds"] == {
        "weather": {"1s": 1}
    }
    assert snapshot["permit_denials"] == []
