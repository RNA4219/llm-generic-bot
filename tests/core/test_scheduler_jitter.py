from collections import deque
from typing import Deque, List

import pytest

from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.core.scheduler import Scheduler


pytestmark = pytest.mark.anyio("asyncio")


class StubSender:
    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send(self, text: str, channel: str | None = None) -> None:
        self.sent.append(text if channel is None else f"{channel}:{text}")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_scheduler_applies_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = StubSender()
    queue = CoalesceQueue(window_seconds=0.0, threshold=5)
    delays: Deque[float] = deque()

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
    queue.push("first", priority=5, created_at=base)
    await scheduler.dispatch_ready_batches(base)
    assert list(delays) == [0.0]
    assert sender.sent == ["first"]

    queue.push("second", priority=3, created_at=base)
    await scheduler.dispatch_ready_batches(base)
    assert list(delays) == [0.0, 30.0]
    assert sender.sent == ["first", "second"]


async def test_scheduler_immediate_when_jitter_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = StubSender()
    queue = CoalesceQueue(window_seconds=0.0, threshold=5)
    delays: Deque[float] = deque()

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
    queue.push("only", priority=1, created_at=base)
    await scheduler.dispatch_ready_batches(base)

    assert list(delays) == [0.0]
    assert sender.sent == ["only"]
