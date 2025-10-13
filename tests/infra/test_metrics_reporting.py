from __future__ import annotations

from typing import Mapping

import pytest

try:  # pragma: no cover
    from freezegun import freeze_time
except ModuleNotFoundError:  # pragma: no cover
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from unittest.mock import patch

    @contextmanager
    def freeze_time(iso_timestamp: str):
        frozen = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return frozen if tz is None else frozen.astimezone(tz)

            @classmethod
            def utcnow(cls):  # type: ignore[override]
                return frozen.astimezone(timezone.utc).replace(tzinfo=None)

        with patch("datetime.datetime", _Frozen), patch("time.time", lambda: frozen.timestamp()):
            yield

from llm_generic_bot.core.orchestrator import MetricsRecorder
from llm_generic_bot.infra import metrics


class RecordingMetrics(MetricsRecorder):
    def __init__(self) -> None:
        self.increment_calls: list[tuple[str, dict[str, str]]] = []
        self.observe_calls: list[tuple[str, float, dict[str, str]]] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self.increment_calls.append((name, dict(tags or {})))

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self.observe_calls.append((name, value, dict(tags or {})))


@pytest.fixture(autouse=True)
def reset_metrics_module() -> None:
    metrics.reset_for_test()
    yield
    metrics.reset_for_test()


@pytest.mark.asyncio
async def test_metrics_records_expected_labels_and_snapshot() -> None:
    recorder = RecordingMetrics()
    metrics.configure_backend(recorder)
    with freeze_time("2025-01-06T12:00:00+00:00"):
        await metrics.report_send_success(job="weather", platform="discord", channel="alerts", duration_seconds=0.42, permit_tags={"decision": "allow"})
        await metrics.report_send_failure(job="weather", platform="discord", channel="alerts", duration_seconds=2.4, error_type="http_500")
        metrics.report_permit_denied(job="alerts", platform="discord", channel=None, reason="quota_exceeded", permit_tags={"rule": "quota"})
        snapshot = metrics.weekly_snapshot()
    assert recorder.increment_calls == [
        ("send.success", {"job": "weather", "platform": "discord", "channel": "alerts", "decision": "allow"}),
        ("send.failure", {"job": "weather", "platform": "discord", "channel": "alerts", "error": "http_500"}),
        ("send.denied", {"job": "alerts", "platform": "discord", "channel": "-", "reason": "quota_exceeded", "rule": "quota"}),
    ]
    assert recorder.observe_calls == [
        ("send.duration", pytest.approx(0.42), {"job": "weather", "platform": "discord", "channel": "alerts", "unit": "seconds"}),
        ("send.duration", pytest.approx(2.4), {"job": "weather", "platform": "discord", "channel": "alerts", "unit": "seconds"}),
    ]
    assert snapshot == {
        "generated_at": "2025-01-06T12:00:00+00:00",
        "success_rate": {"weather": {"success": 1, "failure": 1, "ratio": 0.5}},
        "latency_histogram_seconds": {"weather": {"1s": 1, "3s": 1}},
        "permit_denials": [{"job": "alerts", "platform": "discord", "channel": "-", "reason": "quota_exceeded", "rule": "quota"}],
    }


@pytest.mark.asyncio
async def test_metrics_null_backend_falls_back_to_noop() -> None:
    with freeze_time("2025-01-06T09:00:00+00:00"):
        await metrics.report_send_success(job="weather", platform="discord", channel="alerts", duration_seconds=0.5, permit_tags={"decision": "allow"})
        snapshot = metrics.weekly_snapshot()
    assert snapshot == {
        "generated_at": "2025-01-06T09:00:00+00:00",
        "success_rate": {},
        "latency_histogram_seconds": {},
        "permit_denials": [],
    }
