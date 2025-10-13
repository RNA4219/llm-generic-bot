from __future__ import annotations

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision
from llm_generic_bot.infra.metrics import MetricsService


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FailingSender:
    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        raise RuntimeError("boom")


def _permit(_: str, __: str | None, ___: str) -> PermitDecision:
    return PermitDecision.allowed()


async def test_weekly_snapshot_counts_single_failure() -> None:
    metrics_service = MetricsService()
    orchestrator = Orchestrator(
        sender=_FailingSender(),
        cooldown=CooldownGate(
            window_sec=1,
            mult_min=1.0,
            mult_max=1.0,
            k_rate=0.0,
            k_time=0.0,
            k_eng=0.0,
        ),
        dedupe=NearDuplicateFilter(),
        permit=_permit,
        metrics=metrics_service,
    )

    try:
        await orchestrator.enqueue(
            "hello",
            job="job",
            platform="test-platform",
            channel="general",
        )
        await orchestrator.flush()

        snapshot = await orchestrator.weekly_snapshot()
    finally:
        await orchestrator.close()

    failure_metrics = snapshot.counters.get("send.failure")
    assert failure_metrics is not None
    total = sum(entry.count for entry in failure_metrics.values())
    assert total == 1
