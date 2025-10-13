from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

from llm_generic_bot.infra.metrics import (
    CounterSnapshot,
    MetricsService,
    ObservationSnapshot,
)


def _clock_from(iterator: Iterator[datetime]) -> Callable[[], datetime]:
    def _inner() -> datetime:
        return next(iterator)

    return _inner


def test_collect_weekly_snapshot_filters_and_groups() -> None:
    base = datetime(2024, 1, 8, tzinfo=timezone.utc)
    clock_values = iter(
        [
            base - timedelta(days=8),
            base - timedelta(days=1),
            base - timedelta(hours=2),
        ]
    )
    service = MetricsService(clock=_clock_from(clock_values))

    service.increment(
        "send.success",
        tags={"job": "weather", "platform": "slack"},
    )
    service.increment(
        "send.success",
        tags={"job": "weather", "platform": "slack"},
    )
    service.observe(
        "send.latency",
        0.75,
        tags={"job": "weather", "platform": "slack"},
    )

    snapshot = service.collect_weekly_snapshot(base)

    key = (("job", "weather"), ("platform", "slack"))
    assert snapshot.counters["send.success"][key] == CounterSnapshot(count=1)
    assert snapshot.observations["send.latency"][key] == ObservationSnapshot(
        count=1,
        minimum=0.75,
        maximum=0.75,
        total=0.75,
        average=0.75,
    )
