from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision

from .conftest import StubSender

if TYPE_CHECKING:
    from .conftest import MetricsStub, StubCooldown, StubDedupe


pytestmark = pytest.mark.anyio


async def test_orchestrator_logs_permit_denial(
    caplog: pytest.LogCaptureFixture,
    stub_sender: StubSender,
    stub_cooldown: StubCooldown,
    stub_dedupe: StubDedupe,
    metrics_stub: MetricsStub,
) -> None:
    def permit(_: str, __: str | None, job: str) -> PermitDecision:
        return PermitDecision(allowed=False, reason="quota_exceeded", job=job)

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
        "Permit拒否を確認",
        job="weather",
        platform="discord",
        channel="general",
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert stub_sender.sent == []
    assert stub_cooldown.calls == []

    denial_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_permit_denied"
    )
    assert denial_record.correlation_id == correlation_id
    assert denial_record.reason == "quota_exceeded"
    assert metrics_stub.get_count("send.denied", job="weather") == 1
