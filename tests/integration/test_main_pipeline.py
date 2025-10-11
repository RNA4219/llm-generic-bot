import asyncio
from collections import deque
from typing import Deque, List, Mapping, Optional

import pytest

from llm_generic_bot.main import bootstrap_main

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RecordingSender:
    def __init__(self) -> None:
        self.calls: List[tuple[str, Optional[str], str]] = []

    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        self.calls.append((job, channel, text))


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now_value = start

    def now(self) -> float:
        return self.now_value

    def advance(self, seconds: float) -> None:
        self.now_value += seconds


async def test_pipeline_respects_quota_and_applies_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = RecordingSender()
    clock = Clock()
    sleep_calls: Deque[float] = deque()

    async def fake_sleep(value: float) -> None:
        sleep_calls.append(value)

    jitter_values = deque([0.0, 42.0])

    def fake_next_slot(ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)) -> float:
        assert clash in (False, True)
        delta = jitter_values.popleft()
        return ts + delta

    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", fake_next_slot)

    config: Mapping[str, object] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "alerts"}},
        "cooldown": {"window_sec": 60, "mult_min": 1.0, "mult_max": 2.0, "coeff": {"rate": 0.0, "time": 0.0, "eng": 0.0}},
        "dedupe": {"recent_k": 5, "sim_threshold": 0.99},
        "quota": {"per_channel": {"day": 5, "window_min": 60, "burst_limit": 1}},
    }

    scheduler, orchestrator = bootstrap_main(
        config,
        sender=sender,
        queue_window_seconds=60.0,
        queue_threshold=1,
        sleep=fake_sleep,
        now=clock.now,
    )

    scheduler.queue.push(
        "first", priority=5, created_at=clock.now(), channel="alerts", job="weather"
    )
    await scheduler.dispatch_ready_batches(clock.now())
    await asyncio.wait_for(orchestrator.flush(), timeout=0.1)

    scheduler.queue.push(
        "second", priority=5, created_at=clock.now(), channel="alerts", job="weather"
    )
    await scheduler.dispatch_ready_batches(clock.now())
    await asyncio.wait_for(orchestrator.flush(), timeout=0.1)

    assert list(sleep_calls) == [0.0, 42.0]
    assert sender.calls == [("weather", "alerts", "first")]
