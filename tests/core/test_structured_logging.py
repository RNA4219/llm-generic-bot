from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping
import sys

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import MetricsRecorder, Orchestrator, PermitDecision

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
        await asyncio.sleep(0)
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


async def test_orchestrator_logs_success_with_correlation_id(caplog: pytest.LogCaptureFixture) -> None:
    sender = StubSender()
    cooldown = StubCooldown()
    dedupe = StubDedupe()
    metrics = MetricsStub()

    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        logger=logging.getLogger("test.orchestrator"),
        platform="discord",
    )

    caplog.set_level(logging.INFO)
    correlation_id = await orchestrator.enqueue(
        "晴れの予報です",
        job="weather",
        platform="discord",
        channel="general",
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == [("晴れの予報です", "general")]
    assert cooldown.calls == [("discord", "general", "weather")]

    success_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_success"
    )
    assert success_record.correlation_id == correlation_id
    assert success_record.job == "weather"
    assert metrics.get_count("send.success", job="weather") == 1


async def test_orchestrator_logs_failure_and_metrics(caplog: pytest.LogCaptureFixture) -> None:
    sender = FailingSender()
    cooldown = StubCooldown()
    dedupe = StubDedupe()
    metrics = MetricsStub()

    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        logger=logging.getLogger("test.orchestrator"),
        platform="discord",
    )

    caplog.set_level(logging.ERROR)
    correlation_id = await orchestrator.enqueue(
        "送信に失敗します",
        job="weather",
        platform="discord",
        channel="general",
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert cooldown.calls == []
    failure_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_failure"
    )
    assert failure_record.correlation_id == correlation_id
    assert failure_record.error_type == "RuntimeError"
    assert metrics.get_count("send.failure", job="weather") == 1
    assert metrics.get_count("send.duration", job="weather", unit="seconds") == 1
    duration_tags = metrics.last_tags["send.duration"]
    assert duration_tags is not None
    assert duration_tags["unit"] == "seconds"


async def test_orchestrator_logs_permit_denial(caplog: pytest.LogCaptureFixture) -> None:
    sender = StubSender()
    cooldown = StubCooldown()
    dedupe = StubDedupe()
    metrics = MetricsStub()

    def permit(_: str, __: str | None, job: str) -> PermitDecision:
        return PermitDecision(allowed=False, reason="quota_exceeded", job=job)

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        logger=logging.getLogger("test.orchestrator"),
        platform="discord",
    )

    caplog.set_level(logging.INFO)
    correlation_id = await orchestrator.enqueue(
        "Permit拒否を確認",
        job="weather",
        platform="discord",
        channel="general",
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == []
    assert cooldown.calls == []

    denial_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_permit_denied"
    )
    assert denial_record.correlation_id == correlation_id
    assert denial_record.reason == "quota_exceeded"
    assert metrics.get_count("send.denied", job="weather") == 1


async def test_orchestrator_logs_duplicate_skip(caplog: pytest.LogCaptureFixture) -> None:
    sender = StubSender()
    cooldown = StubCooldown()
    dedupe = RejectingDedupe()
    metrics = MetricsStub()

    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        logger=logging.getLogger("test.orchestrator"),
        platform="discord",
    )

    caplog.set_level(logging.INFO)
    correlation_id = await orchestrator.enqueue(
        "duplicate", job="weather", platform="discord", channel="general"
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == []
    duplicate_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_duplicate_skip"
    )
    assert duplicate_record.correlation_id == correlation_id
    assert duplicate_record.status == "duplicate"
    assert duplicate_record.retryable is False
    duplicate_tags = metrics.last_tags["send.duplicate"]
    assert duplicate_tags is not None
    assert duplicate_tags["job"] == "weather"
    assert duplicate_tags["status"] == "duplicate"
    assert duplicate_tags["retryable"] == "false"


async def test_orchestrator_processes_multiple_queue_items() -> None:
    sender = StubSender()
    cooldown = StubCooldown()
    dedupe = StubDedupe()
    metrics = MetricsStub()

    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        platform="discord",
    )

    await orchestrator.enqueue("first", job="weather", platform="discord", channel="general")
    await orchestrator.enqueue("second", job="weather", platform="discord", channel="general")

    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == [("first", "general"), ("second", "general")]
    assert cooldown.calls[-1] == ("discord", "general", "weather")


async def test_orchestrator_uses_permit_job_override() -> None:
    sender = RecordingSender()
    cooldown = StubCooldown()
    dedupe = StubDedupe()
    metrics = MetricsStub()

    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow(job="override")

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        platform="discord",
    )

    await orchestrator.enqueue("content", job="weather", platform="discord", channel="general")

    await orchestrator.flush()
    await orchestrator.close()

    assert sender.jobs == ["override"]
    assert cooldown.calls == [("discord", "general", "override")]
