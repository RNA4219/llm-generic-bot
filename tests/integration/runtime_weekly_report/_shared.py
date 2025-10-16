from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from llm_generic_bot.features.report import ReportPayload
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class FakeSummary:
    body: str = "body"
    channel: str = "ops"
    tags: Optional[dict[str, str]] = None
    calls: int = 0

    def __call__(self, snapshot: WeeklyMetricsSnapshot, **_: Any) -> ReportPayload:
        del snapshot
        self.calls += 1
        return ReportPayload(body=self.body, channel=self.channel, tags=self.tags or {"locale": "ja"})


def fake_summary(
    body: str = "body",
    *,
    channel: str = "ops",
    tags: Optional[dict[str, str]] = None,
) -> FakeSummary:
    return FakeSummary(body=body, channel=channel, tags=tags)


def weekly_snapshot(
    *,
    start: dt.datetime = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
    end: dt.datetime = dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc),
    counters: Optional[dict[str, dict[tuple[tuple[str, str], ...], CounterSnapshot]]] = None,
    observations: Optional[dict[str, Any]] = None,
) -> Callable[[], Awaitable[WeeklyMetricsSnapshot]]:
    async def _weekly_snapshot() -> WeeklyMetricsSnapshot:
        return WeeklyMetricsSnapshot(
            start=start,
            end=end,
            counters=counters or {},
            observations=observations or {},
        )

    return _weekly_snapshot


__all__ = [
    "FakeSummary",
    "anyio_backend",
    "fake_summary",
    "pytestmark",
    "weekly_snapshot",
]
