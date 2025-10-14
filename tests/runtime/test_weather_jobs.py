from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping, cast

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.orchestrator import PermitEvaluator
from llm_generic_bot.core.scheduler import Scheduler
from llm_generic_bot.runtime.jobs import JobContext
from llm_generic_bot.runtime.jobs.weather import build_weather_jobs


async def _dummy_job(*args: Any, **kwargs: Any) -> None:
    return None


def _make_context(settings: Mapping[str, Any]) -> JobContext:
    async def _build_weather_post(
        *_args: Any,
        channel: str | None = None,
        job: str | None = None,
    ) -> str:
        return "ok"

    permit = lambda _platform, _channel, job: SimpleNamespace(  # noqa: E731
        allowed=True,
        retryable=True,
        reason=None,
        job=job,
    )

    return JobContext(
        settings=settings,
        scheduler=cast(Scheduler, object()),
        platform="discord",
        default_channel="general",
        cooldown=cast(CooldownGate, object()),
        permit=cast(PermitEvaluator, permit),
        build_weather_post=_build_weather_post,
        build_news_post=_dummy_job,
        build_omikuji_post=_dummy_job,
        build_dm_digest=_dummy_job,
    )


def test_build_weather_jobs_collects_schedule_and_schedules() -> None:
    context = _make_context(
        {
            "weather": {
                "enabled": True,
                "schedule": "07:00",
                "schedules": ("12:00", "18:00"),
            }
        }
    )

    jobs = build_weather_jobs(context)

    assert len(jobs) == 1
    assert jobs[0].schedules == ("07:00", "12:00", "18:00")


def test_build_weather_jobs_default_schedule_when_missing() -> None:
    context = _make_context({"weather": {"enabled": True}})

    jobs = build_weather_jobs(context)

    assert len(jobs) == 1
    assert jobs[0].schedules == ("21:00",)
