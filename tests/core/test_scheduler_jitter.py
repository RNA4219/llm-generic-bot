from collections import deque
from typing import List

import pytest

from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.core.scheduler import Scheduler


pytestmark = pytest.mark.anyio("asyncio")


class StubSender:
    def __init__(self) -> None:
        self.sent: List[str] = []
        self.jobs: List[str] = []

    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        self.sent.append(text if channel is None else f"{channel}:{text}")
        self.jobs.append(job)


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


async def test_scheduler_passes_jitter_range_and_job(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = StubSender()
    queue = CoalesceQueue(window_seconds=0.0, threshold=5)
    delays: deque[float] = deque()

    async def fake_sleep(duration: float) -> None:
        delays.append(duration)

    jitter_calls: List[tuple[int, int]] = []
    clash_flags: deque[bool] = deque()
    jitter_values = deque([0.0, 5.0, 10.0])

    def fake_next_slot(ts: float, clash: bool, *, jitter_range: tuple[int, int]) -> float:
        jitter_calls.append(jitter_range)
        clash_flags.append(clash)
        offset = jitter_values.popleft()
        return ts + offset

    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", fake_next_slot)

    scheduler = Scheduler(
        tz="UTC",
        sender=sender,
        queue=queue,
        jitter_enabled=True,
        jitter_range=(5, 10),
        sleep=fake_sleep,
    )

    base = 2000.0
    queue.push("min", priority=1, job="daily", created_at=base)
    await scheduler.dispatch_ready_batches(base)

    queue.push("first", priority=2, job="job-a", created_at=base, channel="permit")
    await scheduler.dispatch_ready_batches(base)

    queue.push("second", priority=2, job="job-b", created_at=base, channel="permit")
    await scheduler.dispatch_ready_batches(base)

    assert list(delays) == [0.0, 5.0, 10.0]
    assert jitter_calls == [(5, 10), (5, 10), (5, 10)]
    assert list(clash_flags) == [False, True, True]
    assert sender.sent == ["min", "permit:first", "permit:second"]
    assert sender.jobs == ["daily", "job-a", "job-b"]
