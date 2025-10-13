from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, Mapping

from llm_generic_bot.infra import collect_weekly_snapshot
from llm_generic_bot.infra.metrics import (
    CounterSnapshot,
    InMemoryMetricsService,
    ObservationSnapshot,
    WeeklyMetricsSnapshot,
    make_metrics_recorder,
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
            base,
        ]
    )
    service = InMemoryMetricsService(clock=_clock_from(clock_values))
    recorder = make_metrics_recorder(service)

    recorder.increment(
        "send.success",
        tags={"job": "weather", "platform": "slack"},
    )
    recorder.increment(
        "send.success",
        tags={"job": "weather", "platform": "slack"},
    )
    recorder.observe(
        "send.latency",
        0.75,
        tags={"job": "weather", "platform": "slack"},
    )

    snapshot = asyncio.run(service.collect_weekly_snapshot())

    key = (("job", "weather"), ("platform", "slack"))
    assert snapshot.counters["send.success"][key] == CounterSnapshot(count=1)
    assert snapshot.observations["send.latency"][key] == ObservationSnapshot(
        count=1,
        minimum=0.75,
        maximum=0.75,
        total=0.75,
        average=0.75,
    )


def test_collect_weekly_snapshot_returns_empty_snapshot() -> None:
    snapshot = asyncio.run(collect_weekly_snapshot(None))

    assert isinstance(snapshot, WeeklyMetricsSnapshot)
    assert snapshot.start == snapshot.end
    assert snapshot.counters == {}
    assert snapshot.observations == {}


def test_collect_weekly_snapshot_materializes_full_statistics() -> None:
    base = datetime(2024, 1, 15, tzinfo=timezone.utc)
    clock_values = iter(
        [
            base - timedelta(days=1),
            base - timedelta(hours=20),
            base - timedelta(hours=18),
            base - timedelta(hours=12),
            base,
        ]
    )
    service = InMemoryMetricsService(clock=_clock_from(clock_values))
    recorder = make_metrics_recorder(service)

    recorder.increment("send.success")
    recorder.increment("send.success")
    recorder.observe("send.latency", 0.2)
    recorder.observe("send.latency", 1.4, tags={"channel": "alerts"})

    snapshot = asyncio.run(service.collect_weekly_snapshot())

    assert snapshot.counters == {
        "send.success": {(): CounterSnapshot(count=2)}
    }
    assert snapshot.observations == {
        "send.latency": {
            (): ObservationSnapshot(count=1, minimum=0.2, maximum=0.2, total=0.2, average=0.2),
            (("channel", "alerts"),): ObservationSnapshot(
                count=1,
                minimum=1.4,
                maximum=1.4,
                total=1.4,
                average=1.4,
            ),
        }
    }


def test_collect_weekly_snapshot_respects_custom_retention_days() -> None:
    base = datetime(2024, 1, 20, tzinfo=timezone.utc)
    clock_values = iter(
        [
            base - timedelta(days=5),
            base - timedelta(days=2),
            base - timedelta(days=1),
        ]
    )
    service = InMemoryMetricsService(
        clock=_clock_from(clock_values),
        retention_days=3,
    )
    recorder = make_metrics_recorder(service)

    recorder.increment("send.success")
    recorder.increment("send.success")
    recorder.increment("send.success")

    snapshot = asyncio.run(service.collect_weekly_snapshot(now=base))

    assert snapshot.counters == {
        "send.success": {(): CounterSnapshot(count=2)}
    }
