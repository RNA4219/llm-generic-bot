from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision

if TYPE_CHECKING:
    from .conftest import FailingSender, MetricsStub, StubCooldown, StubDedupe


pytestmark = pytest.mark.anyio


async def test_orchestrator_logs_failure_and_metrics(
    caplog: pytest.LogCaptureFixture,
    failing_sender: FailingSender,
    stub_cooldown: StubCooldown,
    stub_dedupe: StubDedupe,
    metrics_stub: MetricsStub,
) -> None:
    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=failing_sender,
        cooldown=stub_cooldown,
        dedupe=stub_dedupe,
        permit=permit,
        metrics=metrics_stub,
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

    assert stub_cooldown.calls == []
    failure_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_failure"
    )
    assert failure_record.correlation_id == correlation_id
    assert failure_record.error_type == "RuntimeError"
