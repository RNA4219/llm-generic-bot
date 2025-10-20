from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot

from ._helpers import create_queue, record_orchestrator_enqueue


pytestmark = pytest.mark.anyio("asyncio")


async def test_weekly_report_job_uses_metrics_and_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = create_queue()
    snapshot = WeeklyMetricsSnapshot(
        start=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
        end=dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc),
        counters={"send.success": {(): CounterSnapshot(count=4)}},
        observations={},
    )

    class RecordingMetricsService:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.calls = 0

        def record_event(
            self,
            name: str,
            *,
            tags: Optional[Dict[str, str]] = None,
            measurements: Optional[Dict[str, float]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> None:
            del name, tags, measurements, metadata
            return None

        async def collect_weekly_snapshot(
            self, now: dt.datetime | None = None
        ) -> WeeklyMetricsSnapshot:
            del now
            self.calls += 1
            return snapshot

    from llm_generic_bot.runtime import setup as runtime_setup

    metrics_service = RecordingMetricsService()
    monkeypatch.setattr(runtime_setup, "MetricsService", lambda *_: metrics_service)

    weekly_snapshot_calls: List[Dict[str, Any]] = []

    def fake_weekly_snapshot() -> Dict[str, Any]:
        payload = {
            "generated_at": "2024-01-08T00:00:00+00:00",
            "success_rate": {"weather": {"ratio": 0.75}},
        "latency_histogram_seconds": {},
        "permit_denials": [],
        "permit_reevaluations": [],
    }
        weekly_snapshot_calls.append(payload)
        return payload

    monkeypatch.setattr(runtime_setup.metrics_module, "weekly_snapshot", fake_weekly_snapshot)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "metrics": {"backend": "memory"},
        "report": {
            "enabled": True,
            "job": "weekly_report",
            "schedule": "09:00",
            "channel": "ops-weekly",
            "priority": 7,
            "permit": {
                "platform": "discord",
                "channel": "ops-weekly",
                "job": "weekly_report",
            },
            "template": {
                "title": "📊 運用サマリ ({week_range})",
                "line": "・{metric}: {value}",
                "footer": "詳細は運用ダッシュボードを参照",
            },
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)

    enqueue_calls = record_orchestrator_enqueue(monkeypatch, orchestrator)

    try:
        assert "weekly_report" in jobs

        job_func = jobs["weekly_report"]
        text = await job_func()

        assert metrics_service.calls == 1
        assert len(weekly_snapshot_calls) == 1
        assert isinstance(text, str)
        lines = text.splitlines()
        assert lines[0] == "📊 運用サマリ (2024-01-01〜2024-01-08)"
        assert "weather" in lines[1] and "75%" in lines[1]
        assert lines[-1] == "詳細は運用ダッシュボードを参照"

        assert scheduler.sender is not None
        await scheduler.sender.send(text, job="weekly_report")
        assert enqueue_calls and enqueue_calls[-1].job == "weekly_report"
        assert enqueue_calls[-1].platform == "discord"
        assert enqueue_calls[-1].channel == "ops-weekly"
    finally:
        await orchestrator.close()
