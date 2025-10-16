from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Optional

import pytest

from llm_generic_bot.runtime import setup as runtime_setup

from ._shared import FakeSummary, anyio_backend, fake_summary, pytestmark, weekly_snapshot


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

    monkeypatch.setattr(
        runtime_setup,
        "Orchestrator",
        lambda *_, **__: SimpleNamespace(enqueue=enqueue, weekly_snapshot=weekly_snapshot()),
    )
    for name in (
        "build_weather_jobs",
        "build_news_jobs",
        "build_omikuji_jobs",
        "build_dm_digest_jobs",
    ):
        monkeypatch.setattr(runtime_setup, name, lambda *_: [])

    summary: FakeSummary = fake_summary(tags={"locale": "ja"})
    monkeypatch.setattr(runtime_setup, "generate_weekly_summary", summary)
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
    assert summary.calls == 1

    scheduler._test_now = dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc)
    await scheduler._run_due_jobs(scheduler._test_now)
    assert summary.calls == 1

    scheduler._test_now = dt.datetime(2024, 1, 2, 9, 0, tzinfo=dt.timezone.utc)
    await scheduler._run_due_jobs(scheduler._test_now)
    assert summary.calls == 2

    scheduler._test_now = dt.datetime(2024, 1, 4, 9, 0, tzinfo=dt.timezone.utc)
    await scheduler._run_due_jobs(scheduler._test_now)
    assert summary.calls == 3

    del scheduler._test_now


async def test_weekly_report_permit_override_applies_to_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue_calls: list[dict[str, Optional[str]]] = []

    async def enqueue(
        text: str,
        *,
        job: str,
        platform: str,
        channel: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        del correlation_id
        enqueue_calls.append(
            {
                "text": text,
                "job": job,
                "platform": platform,
                "channel": channel,
            }
        )
        return "corr"

    monkeypatch.setattr(
        runtime_setup,
        "Orchestrator",
        lambda *_, **__: SimpleNamespace(enqueue=enqueue, weekly_snapshot=weekly_snapshot()),
    )
    for name in (
        "build_weather_jobs",
        "build_news_jobs",
        "build_omikuji_jobs",
        "build_dm_digest_jobs",
    ):
        monkeypatch.setattr(runtime_setup, name, lambda *_: [])

    summary = fake_summary(body="header\nline", tags={"severity": "normal"})
    monkeypatch.setattr(runtime_setup, "generate_weekly_summary", summary)
    monkeypatch.setattr(runtime_setup.metrics_module, "weekly_snapshot", lambda: {})

    settings = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "report": {
            "enabled": True,
            "job": "weekly_report",
            "schedule": "Mon 09:00",
            "channel": "ops-weekly",
            "permit": {
                "platform": "slack",
                "channel": "reports",
                "job": "weekly_report_alias",
            },
            "template": {"title": "title {week_range}", "line": "line {metric}: {value}"},
        },
    }

    scheduler, _orchestrator, _jobs = runtime_setup.setup_runtime(settings)
    scheduler.jitter_enabled = False

    current = dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc)
    scheduler._test_now = current
    await scheduler._run_due_jobs(current)
    await scheduler.dispatch_ready_batches(current.timestamp() + 600.0)
    del scheduler._test_now

    assert len(enqueue_calls) == 1
    enqueue_call = enqueue_calls[0]
    assert enqueue_call["platform"] == "slack"
    assert enqueue_call["channel"] == "reports"
    assert enqueue_call["job"] == "weekly_report_alias"
