from __future__ import annotations

import asyncio

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision
from llm_generic_bot.infra.metrics import MetricsService, WeeklyMetricsSnapshot


class _DummySender:
    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        return None


def _permit(_: str, __: str | None, ___: str) -> PermitDecision:
    return PermitDecision.allowed()


def test_weekly_snapshot_returns_snapshot() -> None:
    metrics_service = MetricsService()

    async def run() -> WeeklyMetricsSnapshot:
        orchestrator = Orchestrator(
            sender=_DummySender(),
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
            return await orchestrator.weekly_snapshot()
        finally:
            await orchestrator.close()

    snapshot = asyncio.run(run())

    assert isinstance(snapshot, WeeklyMetricsSnapshot)
