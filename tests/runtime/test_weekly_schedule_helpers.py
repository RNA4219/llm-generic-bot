import datetime as dt
import zoneinfo

import pytest

from llm_generic_bot.runtime.setup.runtime_helpers import (
    _parse_weekday_schedule,
    _wrap_weekday_job,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    "value, expected_weekdays, expected_hhmm",
    [
        ("mon wed 18:30", frozenset({0, 2}), "18:30"),
        ("mon,wed,fri 07:15", frozenset({0, 2, 4}), "07:15"),
        ("mon,invalid wed 10:00", None, "10:00"),
    ],
)
def test_parse_weekday_schedule_variants(value, expected_weekdays, expected_hhmm):
    weekdays, hhmm = _parse_weekday_schedule(value)
    assert weekdays == expected_weekdays
    assert hhmm == expected_hhmm


class _StubScheduler:
    def __init__(self, tz: str = "UTC") -> None:
        self.tz = zoneinfo.ZoneInfo(tz)
        self._test_now: dt.datetime | None = None


@pytest.mark.anyio("asyncio")
async def test_wrap_weekday_job_respects_allowed_weekdays():
    scheduler = _StubScheduler()
    called: list[str] = []

    async def job() -> str:
        called.append("run")
        return "payload"

    wrapped = _wrap_weekday_job(job, weekdays=frozenset({0}), scheduler=scheduler)  # Monday

    scheduler._test_now = dt.datetime(2024, 4, 1, 12, 0, tzinfo=scheduler.tz)
    result = await wrapped()
    assert result == "payload"
    assert called == ["run"]

    scheduler._test_now = dt.datetime(2024, 4, 2, 12, 0, tzinfo=scheduler.tz)
    result = await wrapped()
    assert result is None
    assert called == ["run"]
