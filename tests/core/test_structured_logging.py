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


class StubSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None]] = []

    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        await asyncio.sleep(0)
        self.sent.append((text, channel))


class FailingSender(StubSender):
    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        await asyncio.sleep(0)
        raise RuntimeError("boom")


@dataclass
class MetricsStub(MetricsRecorder):
    counts: MutableMapping[str, Counter[str]]
    observations: MutableMapping[str, list[tuple[str, float]]]

    def __init__(self) -> None:
        self.counts = {}
        self.observations = {}

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        label = tags.get("job") if tags else "-"
        counter = self.counts.setdefault(name, Counter())
        counter[label] += 1

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        label = tags.get("job") if tags else "-"
        self.observations.setdefault(name, []).append((label, value))


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
    assert metrics.counts["send.success"]["weather"] == 1


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
    assert metrics.counts["send.failure"]["weather"] == 1


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
    assert metrics.counts["send.denied"]["weather"] == 1


async def test_orchestrator_logs_duplicate_skip(caplog: pytest.LogCaptureFixture) -> None:
    sender = StubSender()
    cooldown = StubCooldown()

    class RejectingDedupe(NearDuplicateFilter):
        def __init__(self) -> None:
            super().__init__(k=5, threshold=0.5)

        def permit(self, text: str) -> bool:  # type: ignore[override]
            return False

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
        "重複メッセージをスキップ",
        job="weather",
        platform="discord",
        channel="general",
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == []
    assert cooldown.calls == []

    duplicate_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_duplicate_skip"
    )
    assert duplicate_record.correlation_id == correlation_id
    assert duplicate_record.job == "weather"
    assert metrics.counts["send.duplicate"]["weather"] == 1


async def test_send_duration_metric_units(caplog: pytest.LogCaptureFixture) -> None:
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
    await orchestrator.enqueue(
        "durationを検証",
        job="weather",
        platform="discord",
        channel="general",
    )

    await orchestrator.flush()
    await orchestrator.close()

    success_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_success"
    )
    assert isinstance(success_record.duration_sec, float)
    assert success_record.duration_sec > 0

    duration_observations = metrics.observations.get("send.duration")
    assert duration_observations is not None
    label, observed_value = duration_observations[0]
    assert label == "weather"
    assert observed_value == success_record.duration_sec
