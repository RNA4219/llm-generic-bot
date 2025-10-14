import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from llm_generic_bot.features.report import ReportPayload
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot
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


async def test_weekly_report_config_template_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    settings.setdefault("report", {})
    report_cfg = settings["report"]
    report_cfg["enabled"] = True
    report_cfg.setdefault("schedule", "Tue 09:00")
    template_cfg = report_cfg.setdefault("template", {})
    template_cfg["line"] = str(template_cfg.get("line", "・{metric}: {value}")).replace(
        "{metric}", "{label}"
    )

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
            counters={
                "send.success": {(): CounterSnapshot(count=120)},
                "send.failure": {(): CounterSnapshot(count=5)},
            },
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

    monkeypatch.setattr(
        runtime_setup.metrics_module,
        "weekly_snapshot",
        lambda: {"success_rate": {"ops": {"ratio": 0.92}}},
    )

    scheduler, _orchestrator, jobs = runtime_setup.setup_runtime(settings)

    result = await jobs[report_cfg.get("job", "weekly_report",)]()
    assert isinstance(result, str)
    assert "ops success" in result


async def test_weekly_report_template_line_context(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    settings.setdefault("report", {})
    report_cfg = settings["report"]
    report_cfg["enabled"] = True
    report_cfg.setdefault("schedule", "Tue 09:00")
    template_cfg = report_cfg.setdefault("template", {})
    template_cfg["line"] = "stats total={total} success_rate={success_rate:.1f}% value={value}"

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
            counters={
                "send.success": {
                    (("channel", "ops"),): CounterSnapshot(count=8),
                },
                "send.failure": {
                    (("channel", "ops"),): CounterSnapshot(count=2),
                },
            },
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

    monkeypatch.setattr(runtime_setup.metrics_module, "weekly_snapshot", lambda: {})

    scheduler, _orchestrator, jobs = runtime_setup.setup_runtime(settings)

    result = await jobs[report_cfg.get("job", "weekly_report",)]()
    assert isinstance(result, str)
    assert "total=10" in result
    assert "success_rate=80.0%" in result
    assert "{total}" not in result


async def test_weekly_report_skips_self_success_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    settings.setdefault("report", {})
    report_cfg = settings["report"]
    report_cfg["enabled"] = True
    report_cfg.setdefault("schedule", "Tue 09:00")

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
            counters={
                "send.success": {(): CounterSnapshot(count=12)},
            },
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

    monkeypatch.setattr(
        runtime_setup.metrics_module,
        "weekly_snapshot",
        lambda: {
            "success_rate": {
                "weekly_report": {"ratio": 0.75},
                "ops": {"ratio": 0.92},
            }
        },
    )

    scheduler, _orchestrator, jobs = runtime_setup.setup_runtime(settings)

    result = await jobs[report_cfg.get("job", "weekly_report",)]()
    assert isinstance(result, str)
    assert "ops success" in result
    assert "weekly_report success" not in result
