from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import llm_generic_bot.infra.metrics.aggregator_state as aggregator_state
from llm_generic_bot.infra.metrics import reporting, service as service_module


@pytest.mark.anyio("asyncio")
async def test_weekly_snapshot_respects_configured_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_time = datetime(2025, 3, 10, tzinfo=timezone.utc)
    current = {"value": base_time}

    def clock() -> datetime:
        return current["value"]

    monkeypatch.setattr(aggregator_state, "_utcnow", lambda: current["value"])

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
