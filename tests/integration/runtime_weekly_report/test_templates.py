from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from llm_generic_bot.infra.metrics import CounterSnapshot
from llm_generic_bot.runtime import setup as runtime_setup

from ._shared import anyio_backend, pytestmark, weekly_snapshot


async def test_weekly_report_config_template_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    settings.setdefault("report", {})
    report_cfg = settings["report"]
    report_cfg["enabled"] = True
    report_cfg.setdefault("schedule", "Tue 09:00")
    template_cfg = report_cfg.setdefault("template", {})
    template_cfg["line"] = str(template_cfg.get("line", "・{metric}: {value}")).replace("{metric}", "{label}")

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

    counters = {
        "send.success": {(): CounterSnapshot(count=120)},
        "send.failure": {(): CounterSnapshot(count=5)},
    }

    monkeypatch.setattr(
        runtime_setup,
        "Orchestrator",
        lambda *_, **__: SimpleNamespace(enqueue=enqueue, weekly_snapshot=weekly_snapshot(counters=counters)),
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

    counters = {
        "send.success": {
            (("channel", "ops"),): CounterSnapshot(count=8),
        },
        "send.failure": {
            (("channel", "ops"),): CounterSnapshot(count=2),
        },
    }

    monkeypatch.setattr(
        runtime_setup,
        "Orchestrator",
        lambda *_, **__: SimpleNamespace(enqueue=enqueue, weekly_snapshot=weekly_snapshot(counters=counters)),
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
