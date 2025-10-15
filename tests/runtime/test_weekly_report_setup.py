from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional, cast

import pytest

from llm_generic_bot.runtime.setup.runtime_helpers import register_weekly_report_job


async def _noop_enqueue(
    text: str,
    *,
    job: str,
    platform: str,
    channel: Optional[str],
) -> str:
    del text, job, platform, channel
    return "corr"


async def _noop_snapshot() -> SimpleNamespace:
    now = dt.datetime.now(dt.timezone.utc)
    return SimpleNamespace(start=now, end=now, counters={}, observations={})


class _StubScheduler:
    def __init__(self) -> None:
        self.tz = dt.timezone.utc

    def every_day(
        self,
        name: str,
        hhmm: str,
        handler: Callable[[], Awaitable[Optional[str]]],
        *,
        channel: Optional[str] = None,
        priority: int = 5,
    ) -> None:
        del name, hhmm, handler, channel, priority


def test_register_weekly_report_job_keeps_default_permit_platform() -> None:
    scheduler = cast(Any, _StubScheduler())
    orchestrator = cast(
        Any,
        SimpleNamespace(enqueue=_noop_enqueue, weekly_snapshot=_noop_snapshot),
    )
    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]] = {}
    permit_overrides: dict[str, tuple[str, Optional[str], str]] = {}

    register_weekly_report_job(
        config={
            "enabled": True,
            "permit": {"platform": None},
        },
        scheduler=scheduler,
        orchestrator=orchestrator,
        default_channel="ops",
        platform="discord",
        permit_overrides=permit_overrides,
        jobs=jobs,
    )

    assert permit_overrides["weekly_report"][0] == "discord"


@pytest.mark.parametrize("enabled_value", ["false", "0", 0, 0.0])
def test_register_weekly_report_job_respects_disabled_non_bool_values(
    enabled_value: Any,
) -> None:
    scheduler = cast(Any, _StubScheduler())
    orchestrator = cast(
        Any,
        SimpleNamespace(enqueue=_noop_enqueue, weekly_snapshot=_noop_snapshot),
    )
    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]] = {}
    permit_overrides: dict[str, tuple[str, Optional[str], str]] = {}

    register_weekly_report_job(
        config={"enabled": enabled_value},
        scheduler=scheduler,
        orchestrator=orchestrator,
        default_channel="ops",
        platform="discord",
        permit_overrides=permit_overrides,
        jobs=jobs,
    )

    assert jobs == {}
    assert permit_overrides == {}
