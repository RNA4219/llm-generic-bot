from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, MutableMapping

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import MetricsRecorder

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class StubCooldown(CooldownGate):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []

    def note_post(self, platform: str, channel: str | None, job: str) -> None:  # type: ignore[override]
        self.calls.append((platform, channel, job))


class StubDedupe(NearDuplicateFilter):
    def __init__(self) -> None:
        super().__init__(k=5, threshold=0.5)

    def permit(self, text: str) -> bool:  # type: ignore[override]
        return True


class RejectingDedupe(NearDuplicateFilter):
    def __init__(self) -> None:
        super().__init__(k=5, threshold=0.5)

    def permit(self, text: str) -> bool:  # type: ignore[override]
        return False


class StubSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None]] = []

    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        await asyncio.sleep(0)
        self.sent.append((text, channel))


class RecordingSender(StubSender):
    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[str] = []

    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        await super().send(text, channel, job=job)
        self.jobs.append(job)


class FailingSender(StubSender):
    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        await super().send(text, channel, job=job)
        raise RuntimeError("boom")


@dataclass
class MetricsStub(MetricsRecorder):
    counts: MutableMapping[str, Counter[tuple[tuple[str, str], ...]]]

    def __init__(self) -> None:
        self.counts = {}
        self.last_tags: dict[str, Mapping[str, str] | None] = {}

    @staticmethod
    def _normalize(tags: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
        if not tags:
            return ()
        return tuple(sorted(tags.items()))

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        counter = self.counts.setdefault(name, Counter())
        counter[self._normalize(tags)] += 1
        self.last_tags[name] = dict(tags) if tags else None

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        counter = self.counts.setdefault(name, Counter())
        counter[self._normalize(tags)] += 1
        self.last_tags[name] = dict(tags) if tags else None

    def get_count(self, name: str, **tags: str) -> int:
        counter = self.counts.get(name)
        if counter is None:
            return 0
        if not tags:
            return sum(counter.values())
        expected = tuple(sorted(tags.items()))
        total = 0
        for recorded_tags, count in counter.items():
            recorded_dict = dict(recorded_tags)
            if all(recorded_dict.get(key) == value for key, value in expected):
                total += count
        return total


@pytest.fixture
def stub_sender() -> StubSender:
    return StubSender()


@pytest.fixture
def recording_sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def failing_sender() -> FailingSender:
    return FailingSender()


@pytest.fixture
def metrics_stub() -> MetricsStub:
    return MetricsStub()


@pytest.fixture
def stub_cooldown() -> StubCooldown:
    return StubCooldown()


@pytest.fixture
def stub_dedupe() -> StubDedupe:
    return StubDedupe()


@pytest.fixture
def rejecting_dedupe() -> RejectingDedupe:
    return RejectingDedupe()
