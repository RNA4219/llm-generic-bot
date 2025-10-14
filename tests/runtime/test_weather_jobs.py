from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from llm_generic_bot.runtime.jobs import JobContext
from llm_generic_bot.runtime.jobs.weather import build_weather_jobs


async def _noop_job(*_: Any, **__: Any) -> None:
    return None


def _build_context(settings: Mapping[str, Any]) -> JobContext:
    scheduler = SimpleNamespace(every_day=lambda *args, **kwargs: None)
    return JobContext(
        settings=settings,
        scheduler=scheduler,
        platform="discord",
        default_channel="general",
        cooldown=SimpleNamespace(),
        permit=SimpleNamespace(),
        build_weather_post=_noop_job,
        build_news_post=_noop_job,
        build_omikuji_post=_noop_job,
        build_dm_digest=_noop_job,
    )


@pytest.mark.parametrize(
    ("config_key", "value"),
    [
        ("schedule", ["07:00", "19:00"]),
        ("schedules", ("08:00", "20:00")),
    ],
)
def test_build_weather_jobs_collects_multiple_schedules(
    config_key: str, value: list[str] | tuple[str, ...]
) -> None:
    settings: dict[str, Any] = {"weather": {"enabled": True, config_key: value}}
    context = _build_context(settings)

    jobs = build_weather_jobs(context)

    assert len(jobs) == 1
    assert jobs[0].schedules == tuple(value)
