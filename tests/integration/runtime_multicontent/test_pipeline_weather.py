from __future__ import annotations

import datetime as dt
import zoneinfo
from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module

from ._helpers import (
    create_queue,
    freeze_scheduler,
    record_orchestrator_enqueue,
    record_queue_push,
)


pytestmark = pytest.mark.anyio("asyncio")


async def test_setup_runtime_uses_weather_channel_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = create_queue()

    weather_calls: List[Dict[str, Any]] = []

    async def fake_weather(
        cfg: Dict[str, Any],
        *,
        channel: Optional[str] = None,
        job: str = "weather",
    ) -> str:
        weather_calls.append({"cfg": cfg, "channel": channel, "job": job})
        return "weather-post"

    monkeypatch.setattr(main_module, "build_weather_post", fake_weather)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"schedule": "00:00", "channel": "weather-alerts"},
    }

    scheduler, orchestrator, _jobs = main_module.setup_runtime(
        settings,
        queue=queue,
    )

    pushed = record_queue_push(monkeypatch, scheduler)

    try:
        now = dt.datetime(2024, 1, 1, 0, 0, tzinfo=scheduler.tz)
        await scheduler._run_due_jobs(now)

        assert weather_calls
        assert weather_calls[0]["channel"] == "weather-alerts"
        assert pushed
        assert pushed[0].channel == "weather-alerts"
    finally:
        await orchestrator.close()


async def test_setup_runtime_skips_weather_job_when_disabled() -> None:
    queue = create_queue()

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"enabled": False, "schedule": "00:00"},
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)

    try:
        assert "weather" not in jobs
        assert all(job.name != "weather" for job in scheduler._jobs)
    finally:
        await orchestrator.close()


async def test_setup_runtime_uses_custom_weather_job_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = create_queue()
    custom_job = "daily_weather"

    weather_calls: List[Dict[str, Any]] = []

    async def fake_weather_post(
        settings: Dict[str, Any],
        *,
        reaction_history_provider: Optional[object] = None,
        cooldown: object | None = None,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
        job: Optional[str] = None,
    ) -> str:
        del settings, reaction_history_provider, cooldown, platform, channel
        weather_calls.append({"job": job})
        return "weather-text"

    async def fake_history_provider(
        *,
        job: str,
        limit: int,
        platform: Optional[str],
        channel: Optional[str],
    ) -> List[int]:
        del job, limit, platform, channel
        return []

    monkeypatch.setattr(main_module, "build_weather_post", fake_weather_post)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {
            "schedule": "00:00",
            "job": custom_job,
            "engagement": {"history_provider": fake_history_provider},
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    freeze_scheduler(monkeypatch, scheduler)

    enqueue_calls = record_orchestrator_enqueue(monkeypatch, orchestrator)
    pushed_jobs = record_queue_push(monkeypatch, scheduler)

    try:
        assert set(jobs) == {custom_job}
        assert [job.name for job in scheduler._jobs] == [custom_job]

        tz = zoneinfo.ZoneInfo("UTC")
        now = dt.datetime(2024, 1, 1, 0, 0, tzinfo=tz)
        await scheduler._run_due_jobs(now)
        await scheduler.dispatch_ready_batches(now.timestamp())

        assert weather_calls == [{"job": custom_job}]
        assert [call.job for call in pushed_jobs] == [custom_job]
        assert enqueue_calls and enqueue_calls[-1].job == custom_job
    finally:
        await orchestrator.close()


async def test_weather_job_uses_weather_channel_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = create_queue()

    recorded_channels: List[Optional[str]] = []

    async def fake_weather_post(
        settings: Dict[str, Any],
        *,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> str:
        del settings, platform
        recorded_channels.append(channel)
        return "weather-text"

    monkeypatch.setattr(main_module, "build_weather_post", fake_weather_post)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"schedule": "00:00", "channel": "weather-override"},
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    freeze_scheduler(monkeypatch, scheduler)

    enqueue_calls = record_orchestrator_enqueue(monkeypatch, orchestrator)

    try:
        assert set(jobs) == {"weather"}

        tz = zoneinfo.ZoneInfo("UTC")
        now = dt.datetime(2024, 1, 1, 0, 0, tzinfo=tz)
        await scheduler._run_due_jobs(now)
        await scheduler.dispatch_ready_batches(now.timestamp())

        assert recorded_channels == ["weather-override"]
        assert [call.channel for call in enqueue_calls] == ["weather-override"]
    finally:
        await orchestrator.close()
