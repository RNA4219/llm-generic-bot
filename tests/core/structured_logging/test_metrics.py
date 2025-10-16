from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision

if TYPE_CHECKING:
    from .conftest import FailingSender, MetricsStub, StubCooldown, StubDedupe


pytestmark = pytest.mark.anyio


async def test_failure_records_duration_metrics(
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
        platform="discord",
    )

    await orchestrator.enqueue("observe", job="weather", platform="discord", channel="general")

    try:
        await orchestrator.flush()
    finally:
        await orchestrator.close()

    assert metrics_stub.get_count("send.failure", job="weather") == 1
    assert metrics_stub.get_count("send.duration", job="weather", unit="seconds") == 1
    duration_tags = metrics_stub.last_tags["send.duration"]
    assert duration_tags is not None
    assert duration_tags["unit"] == "seconds"
