from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision

if TYPE_CHECKING:
    from .conftest import MetricsStub, RejectingDedupe, StubCooldown, StubSender


pytestmark = pytest.mark.anyio


async def test_orchestrator_logs_duplicate_skip(
    caplog: pytest.LogCaptureFixture,
    stub_sender: StubSender,
    stub_cooldown: StubCooldown,
    rejecting_dedupe: RejectingDedupe,
    metrics_stub: MetricsStub,
) -> None:
    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=stub_sender,
        cooldown=stub_cooldown,
        dedupe=rejecting_dedupe,
        permit=permit,
        metrics=metrics_stub,
        logger=logging.getLogger("test.orchestrator"),
        platform="discord",
    )

    caplog.set_level(logging.INFO)
    correlation_id = await orchestrator.enqueue(
        "duplicate", job="weather", platform="discord", channel="general"
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert stub_sender.sent == []
    duplicate_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_duplicate_skip"
    )
    assert duplicate_record.correlation_id == correlation_id
    assert duplicate_record.status == "duplicate"
    assert duplicate_record.retryable is False
    duplicate_tags = metrics_stub.last_tags["send.duplicate"]
    assert duplicate_tags is not None
    assert duplicate_tags["job"] == "weather"
    assert duplicate_tags["status"] == "duplicate"
    assert duplicate_tags["retryable"] == "false"
