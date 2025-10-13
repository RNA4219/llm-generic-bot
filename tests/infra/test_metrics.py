from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, Mapping

import pytest

from llm_generic_bot.infra.metrics import MetricsService, collect_weekly_snapshot, make_metrics_recorder


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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

    assert snapshot["start"] == base - timedelta(days=7)
    assert snapshot["end"] == base

    jobs = snapshot["jobs"]
    assert jobs == {
        "weather": {
            "send.success": {"count": 1},
            "send.latency": {
                "count": 1,
                "measurements": {
                    "value": {
                        "count": 1,
                        "min": 0.75,
                        "max": 0.75,
                        "sum": 0.75,
                        "avg": 0.75,
                    }
                },
            },
        }
    }

    key = (("job", "weather"), ("platform", "slack"))
    tags_snapshot = snapshot["tags"]
    assert tags_snapshot["send.success"][key] == {"count": 1}
    assert tags_snapshot["send.latency"][key]["measurements"]["value"] == {
        "count": 1,
        "min": 0.75,
        "max": 0.75,
        "sum": 0.75,
        "avg": 0.75,
    }


def test_make_metrics_recorder_switches_to_null() -> None:
    recorder = make_metrics_recorder(None)
    recorder.increment("noop")
    recorder.observe("noop", 1.0)

    base = datetime(2024, 1, 8, tzinfo=timezone.utc)
    service = MetricsService(clock=lambda: base)
    recorder = make_metrics_recorder(service)
    recorder.increment("send.success", tags={"job": "alpha"})
    snapshot = service.collect_weekly_snapshot(base)
    assert snapshot["jobs"]["alpha"]["send.success"] == {"count": 1}


@pytest.mark.anyio
async def test_collect_weekly_snapshot_helper_uses_async_lock(anyio_backend: str) -> None:
    if anyio_backend != "asyncio":
        pytest.skip("asyncio backend required")
    base = datetime(2024, 1, 8, tzinfo=timezone.utc)
    service = MetricsService(clock=lambda: base)
    recorder = make_metrics_recorder(service)
    recorder.observe("send.latency", 1.2, tags={"job": "beta"})

    snapshot = await collect_weekly_snapshot(service)
    assert snapshot["jobs"]["beta"]["send.latency"]["measurements"]["value"]["avg"] == 1.2
