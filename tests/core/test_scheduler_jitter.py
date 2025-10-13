from collections import deque
from typing import List

import pytest

from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.core.scheduler import Scheduler


pytestmark = pytest.mark.anyio("asyncio")


class StubSender:
    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        self.sent.append(text if channel is None else f"{channel}:{text}")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_scheduler_applies_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = StubSender()
    queue = CoalesceQueue(window_seconds=0.0, threshold=5)
    delays: deque[float] = deque()

    async def fake_sleep(duration: float) -> None:
        delays.append(duration)

    jitter_values = deque([0.0, 30.0])

    def fake_next_slot(ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)) -> float:
        assert clash in (False, True)
        delta = jitter_values.popleft()
        return ts + delta

    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", fake_next_slot)

    scheduler = Scheduler(
        tz="UTC",
        sender=sender,
        queue=queue,
        jitter_enabled=True,
        jitter_range=(10, 40),
        sleep=fake_sleep,
    )

    base = 1000.0
    queue.push("first", priority=5, job="daily", created_at=base)
    await scheduler.dispatch_ready_batches(base)
    assert list(delays) == [0.0]
    assert sender.sent == ["first"]

    queue.push("second", priority=3, job="daily", created_at=base)
    await scheduler.dispatch_ready_batches(base)
    assert list(delays) == [0.0, 30.0]
    assert sender.sent == ["first", "second"]


async def test_scheduler_immediate_when_jitter_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = StubSender()
    queue = CoalesceQueue(window_seconds=0.0, threshold=5)
    delays: deque[float] = deque()

    async def fake_sleep(duration: float) -> None:
        delays.append(duration)

    def fake_next_slot(ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)) -> float:
        raise AssertionError("next_slot should not be called when jitter disabled")

    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", fake_next_slot)

    scheduler = Scheduler(
        tz="UTC",
        sender=sender,
        queue=queue,
        jitter_enabled=False,
        sleep=fake_sleep,
    )

    base = 5000.0
    queue.push("only", priority=1, job="daily", created_at=base)
    await scheduler.dispatch_ready_batches(base)

    assert list(delays) == [0.0]
    assert sender.sent == ["only"]


@pytest.mark.parametrize("expected_delay", [5.0, 25.0])
async def test_scheduler_jitter_respects_bounds(
    monkeypatch: pytest.MonkeyPatch, expected_delay: float
) -> None:
    sender = StubSender()
    queue = CoalesceQueue(window_seconds=60.0, threshold=5)
    delays: deque[float] = deque()

    async def fake_sleep(duration: float) -> None:
        delays.append(duration)

    jitter_range = (5, 25)
    call_count = 0

    def fake_next_slot(
        ts: float, clash: bool, jitter_range_arg: tuple[int, int] = (60, 180)
    ) -> float:
        nonlocal call_count
        call_count += 1
        assert jitter_range_arg == jitter_range
        if call_count == 1:
            assert not clash
            return ts
        assert clash
        if expected_delay == float(jitter_range[0]):
            return ts + float(jitter_range[0])
        return ts + float(jitter_range[1])

    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", fake_next_slot)

    scheduler = Scheduler(
        tz="UTC",
        sender=sender,
        queue=queue,
        jitter_enabled=True,
        jitter_range=jitter_range,
        sleep=fake_sleep,
    )

    base = 2000.0
    ready_ts = base - queue.window_seconds
    queue.push("first", priority=5, job="daily", created_at=ready_ts)
    await scheduler.dispatch_ready_batches(base)

    queue.push("second", priority=5, job="daily", created_at=ready_ts)
    await scheduler.dispatch_ready_batches(base)

    assert call_count == 2
    assert list(delays) == [0.0, expected_delay]
    assert sender.sent == ["first", "second"]
    assert scheduler._last_dispatch_ts is not None
    assert scheduler._last_dispatch_ts - base == expected_delay
    assert expected_delay <= queue.window_seconds
