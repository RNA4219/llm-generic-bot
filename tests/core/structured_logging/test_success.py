from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision

if TYPE_CHECKING:
    from .conftest import (
        MetricsStub,
        RecordingSender,
        StubCooldown,
        StubDedupe,
        StubSender,
    )


pytestmark = pytest.mark.anyio


async def test_orchestrator_logs_success_with_correlation_id(
    caplog: pytest.LogCaptureFixture,
    stub_sender: StubSender,
    stub_cooldown: StubCooldown,
    stub_dedupe: StubDedupe,
    metrics_stub: MetricsStub,
) -> None:
    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=stub_sender,
        cooldown=stub_cooldown,
        dedupe=stub_dedupe,
        permit=permit,
        metrics=metrics_stub,
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

    assert stub_sender.sent == [("晴れの予報です", "general")]
    assert stub_cooldown.calls == [("discord", "general", "weather")]

    success_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_success"
    )
    assert success_record.correlation_id == correlation_id
    assert success_record.job == "weather"
    assert metrics_stub.get_count("send.success", job="weather") == 1


async def test_orchestrator_processes_multiple_queue_items(
    stub_sender: StubSender,
    stub_cooldown: StubCooldown,
    stub_dedupe: StubDedupe,
    metrics_stub: MetricsStub,
) -> None:
    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=stub_sender,
        cooldown=stub_cooldown,
        dedupe=stub_dedupe,
        permit=permit,
        metrics=metrics_stub,
        platform="discord",
    )

    await orchestrator.enqueue("first", job="weather", platform="discord", channel="general")
    await orchestrator.enqueue("second", job="weather", platform="discord", channel="general")

    await orchestrator.flush()
    await orchestrator.close()

    assert stub_sender.sent == [("first", "general"), ("second", "general")]
    assert stub_cooldown.calls[-1] == ("discord", "general", "weather")


async def test_orchestrator_uses_permit_job_override(
    recording_sender: RecordingSender,
    stub_cooldown: StubCooldown,
    stub_dedupe: StubDedupe,
    metrics_stub: MetricsStub,
) -> None:

    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow(job="override")

    orchestrator = Orchestrator(
        sender=recording_sender,
        cooldown=stub_cooldown,
        dedupe=stub_dedupe,
        permit=permit,
        metrics=metrics_stub,
        platform="discord",
    )

    await orchestrator.enqueue("content", job="weather", platform="discord", channel="general")

    await orchestrator.flush()
    await orchestrator.close()

    assert recording_sender.jobs == ["override"]
    assert stub_cooldown.calls == [("discord", "general", "override")]
