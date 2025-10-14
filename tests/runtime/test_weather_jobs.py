from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from llm_generic_bot.runtime.jobs import JobContext
from llm_generic_bot.runtime.jobs.weather import build_weather_jobs


async def _dummy_async(*args: Any, **kwargs: Any) -> None:
    return None


def _create_context(settings: Mapping[str, Any]) -> JobContext:
    return JobContext(
        settings=settings,
        scheduler=object(),
        platform="discord",
        default_channel="general",
        cooldown=object(),
        permit=object(),
        build_weather_post=_dummy_async,
        build_news_post=_dummy_async,
        build_omikuji_post=_dummy_async,
        build_dm_digest=_dummy_async,
    )


def test_build_weather_jobs_with_single_schedule() -> None:
    context = _create_context(
        {
            "weather": {
                "enabled": True,
                "schedule": "08:00",
                "channel": "weather-channel",
                "priority": 3,
            }
        }
    )

    jobs = build_weather_jobs(context)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.schedules == ("08:00",)
    assert job.channel == "weather-channel"
    assert job.priority == 3


def test_build_weather_jobs_with_multiple_schedules() -> None:
    context = _create_context(
        {
            "weather": {
                "enabled": True,
                "schedule": "08:00",
                "schedules": ["09:00", "10:00"],
                "channel": "weather-channel",
                "priority": 4,
            }
        }
    )

    jobs = build_weather_jobs(context)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.schedules == ("08:00", "09:00", "10:00")
    assert job.channel == "weather-channel"
    assert job.priority == 4
