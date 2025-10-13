import datetime as dt
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from llm_generic_bot.features.report import ReportPayload
from llm_generic_bot.infra.metrics import WeeklyMetricsSnapshot
from llm_generic_bot.runtime import setup as runtime_setup

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_weekly_report_respects_weekday_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    async def enqueue(
        text: str,
        *,
        job: str,
        platform: str,
        channel: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        del text, job, platform, channel, correlation_id
        return "corr"

    async def weekly_snapshot() -> WeeklyMetricsSnapshot:
        return WeeklyMetricsSnapshot(
            start=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
            end=dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc),
            counters={},
            observations={},
        )

    monkeypatch.setattr(
        runtime_setup,
        "Orchestrator",
        lambda *_, **__: SimpleNamespace(enqueue=enqueue, weekly_snapshot=weekly_snapshot),
    )
    for name in (
        "build_weather_jobs",
        "build_news_jobs",
        "build_omikuji_jobs",
        "build_dm_digest_jobs",
    ):
        monkeypatch.setattr(runtime_setup, name, lambda *_: [])

    summary_calls = 0

    def fake_summary(snapshot: WeeklyMetricsSnapshot, **_: Any) -> ReportPayload:
        nonlocal summary_calls
        summary_calls += 1
        return ReportPayload(body="body", channel="ops", tags={"locale": "ja"})

    monkeypatch.setattr(runtime_setup, "generate_weekly_summary", fake_summary)
    monkeypatch.setattr(runtime_setup.metrics_module, "weekly_snapshot", lambda: {})

    settings = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "report": {
            "enabled": True,
            "job": "weekly_report",
            "schedule": "Tue,Thu 09:00",
            "channel": "ops-weekly",
            "permit": {"platform": "discord", "channel": "ops-weekly", "job": "weekly_report"},
            "template": {"title": "title {week_range}", "line": "line {metric}: {value}"},
        },
    }

    scheduler, _orchestrator, jobs = runtime_setup.setup_runtime(settings)
    assert await jobs["weekly_report"]() == "body"
    assert summary_calls == 1

    scheduler._test_now = dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc)
    await scheduler._run_due_jobs(scheduler._test_now)
    assert summary_calls == 1

    scheduler._test_now = dt.datetime(2024, 1, 2, 9, 0, tzinfo=dt.timezone.utc)
    await scheduler._run_due_jobs(scheduler._test_now)
    assert summary_calls == 2

    scheduler._test_now = dt.datetime(2024, 1, 4, 9, 0, tzinfo=dt.timezone.utc)
    await scheduler._run_due_jobs(scheduler._test_now)
    assert summary_calls == 3

    del scheduler._test_now
