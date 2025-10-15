from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from llm_generic_bot.infra.metrics import (
    aggregator as aggregator_module,
    reporting,
    service as service_module,
)


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
    reporting.reset_for_test()
    yield
    reporting.reset_for_test()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_metrics_records_expected_labels_and_snapshot() -> None:
    recorder = RecordingMetrics()
    reporting.configure_backend(recorder)
    with freeze_time("2025-01-06T12:00:00+00:00"):
        await reporting.report_send_success(job="weather", platform="discord", channel="alerts", duration_seconds=0.42, permit_tags={"decision": "allow"})
        await reporting.report_send_failure(job="weather", platform="discord", channel="alerts", duration_seconds=2.4, error_type="http_500")
        reporting.report_permit_denied(job="alerts", platform="discord", channel=None, reason="quota_exceeded", permit_tags={"rule": "quota"})
        snapshot = reporting.weekly_snapshot()
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


@pytest.mark.anyio("asyncio")
async def test_metrics_null_backend_falls_back_to_noop() -> None:
    reporting.configure_backend(None)
    with freeze_time("2025-01-06T09:00:00+00:00"):
        await reporting.report_send_success(job="weather", platform="discord", channel="alerts", duration_seconds=0.5, permit_tags={"decision": "allow"})
        snapshot = reporting.weekly_snapshot()
    assert snapshot == {
        "generated_at": "2025-01-06T09:00:00+00:00",
        "success_rate": {},
        "latency_histogram_seconds": {},
        "permit_denials": [],
    }


@pytest.mark.anyio("asyncio")
async def test_metrics_weekly_snapshot_latency_boundaries() -> None:
    recorder = RecordingMetrics()
    reporting.configure_backend(recorder)
    with freeze_time("2025-02-03T00:00:00+00:00"):
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
async def test_weekly_snapshot_ignores_events_older_than_seven_days() -> None:
    recorder = RecordingMetrics()
    reporting.configure_backend(recorder)

    with freeze_time("2025-02-02T12:00:00+00:00"):
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

    with freeze_time("2025-02-04T12:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.7,
            permit_tags={"decision": "allow"},
        )

    with freeze_time("2025-02-08T12:00:00+00:00"):
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

    with freeze_time("2025-02-10T12:00:00+00:00"):
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


@pytest.mark.anyio("asyncio")
async def test_weekly_snapshot_respects_configured_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_time = datetime(2025, 3, 10, tzinfo=timezone.utc)
    current = {"value": base_time}

    def clock() -> datetime:
        return current["value"]

    monkeypatch.setattr(aggregator_module, "_utcnow", lambda: current["value"])

    service = service_module.MetricsService(clock=clock, retention_days=3)
    reporting.configure_backend(service)
    reporting.set_retention_days(3)

    current["value"] = base_time - timedelta(days=5)
    await reporting.report_send_success(
        job="weather",
        platform="discord",
        channel="alerts",
        duration_seconds=0.4,
        permit_tags={"decision": "allow"},
    )

    current["value"] = base_time
    await reporting.report_send_success(
        job="weather",
        platform="discord",
        channel="alerts",
        duration_seconds=0.6,
        permit_tags={"decision": "allow"},
    )

    snapshot = reporting.weekly_snapshot()

    assert snapshot["generated_at"] == base_time.isoformat()
    assert snapshot["success_rate"] == {
        "weather": {"success": 1, "failure": 0, "ratio": pytest.approx(1.0)}
    }
    assert snapshot["latency_histogram_seconds"] == {"weather": {"1s": 1}}
    assert snapshot["permit_denials"] == []


@pytest.mark.anyio("asyncio")
async def test_collect_weekly_snapshot_threshold_includes_boundary() -> None:
    current = {"value": datetime(2025, 2, 10, tzinfo=timezone.utc)}

    def clock() -> datetime:
        return current["value"]

    service = service_module.MetricsService(clock=clock)

    current["value"] = current["value"] - timedelta(days=8)
    service.increment("events", tags={"bucket": "too_old"})

    current["value"] = current["value"] + timedelta(days=1)
    service.increment("events", tags={"bucket": "boundary"})

    current["value"] = current["value"] + timedelta(days=6)
    service.increment("events", tags={"bucket": "fresh"})

    current["value"] = datetime(2025, 2, 10, tzinfo=timezone.utc)
    snapshot = await service_module.collect_weekly_snapshot(service)

    boundary_tags = tuple(sorted({"bucket": "boundary"}.items()))
    fresh_tags = tuple(sorted({"bucket": "fresh"}.items()))

    assert snapshot.start == datetime(2025, 2, 3, tzinfo=timezone.utc)
    assert snapshot.end == datetime(2025, 2, 10, tzinfo=timezone.utc)
    assert "events" in snapshot.counters
    counters = snapshot.counters["events"]
    assert counters.get(boundary_tags) == service_module.CounterSnapshot(count=1)
    assert counters.get(fresh_tags) == service_module.CounterSnapshot(count=1)
    assert tuple(sorted({"bucket": "too_old"}.items())) not in counters


@pytest.mark.anyio("asyncio")
async def test_configure_backend_reconfiguration_uses_latest_backend() -> None:
    first = RecordingMetrics()
    second = RecordingMetrics()

    reporting.configure_backend(first)
    with freeze_time("2025-04-01T00:00:00+00:00"):
        await reporting.report_send_success(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=0.25,
            permit_tags={"decision": "allow"},
        )

    reporting.configure_backend(second)
    with freeze_time("2025-04-02T00:00:00+00:00"):
        await reporting.report_send_failure(
            job="weather",
            platform="discord",
            channel="alerts",
            duration_seconds=1.5,
            error_type="timeout",
        )

    with freeze_time("2025-04-03T00:00:00+00:00"):
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_time = datetime(2025, 4, 10, tzinfo=timezone.utc)
    current = {"value": base_time}

    monkeypatch.setattr(aggregator_module, "_utcnow", lambda: current["value"])

    reporting.set_retention_days(3)

    first = RecordingMetrics()
    second = RecordingMetrics()

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
