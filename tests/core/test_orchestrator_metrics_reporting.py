from __future__ import annotations

import asyncio

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision
from llm_generic_bot.infra import metrics
from llm_generic_bot.infra.metrics import MetricsService


class _InstrumentedSender:
    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        if job == "failure-job":
            raise RuntimeError("boom")
        return None


def _permit(_: str, __: str | None, job: str) -> PermitDecision:
    if job == "denied-job":
        return PermitDecision(False, reason="policy", retryable=False, job=job)
    return PermitDecision.allowed(job)


def test_orchestrator_reports_metrics_via_global_aggregator() -> None:
    metrics.reset_for_test()
    service = MetricsService()

    async def run() -> None:
        orchestrator = Orchestrator(
            sender=_InstrumentedSender(),
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
            metrics=service,
            platform="slack",
        )
        try:
            await orchestrator.enqueue(
                "success", job="success-job", platform="slack", channel="general"
            )
            await orchestrator.enqueue(
                "failure", job="failure-job", platform="slack", channel="general"
            )
            await orchestrator.enqueue(
                "denied", job="denied-job", platform="slack", channel="general"
            )
            await orchestrator.flush()
        finally:
            await orchestrator.close()

    asyncio.run(run())

    snapshot = metrics.weekly_snapshot()

    success_job = snapshot["success_rate"]["success-job"]
    assert success_job["success"] == 1
    assert success_job["failure"] == 0

    failure_job = snapshot["success_rate"]["failure-job"]
    assert failure_job["failure"] == 1
    assert failure_job["success"] == 0

    assert any(
        denial["job"] == "denied-job" and denial["reason"] == "policy"
        for denial in snapshot["permit_denials"]
    )


def test_orchestrator_records_single_send_duration_series() -> None:
    metrics.reset_for_test()
    service = MetricsService()

    async def run() -> None:
        orchestrator = Orchestrator(
            sender=_InstrumentedSender(),
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
            metrics=service,
            platform="slack",
        )
        try:
            await orchestrator.enqueue(
                "success", job="success-job", platform="slack", channel="general"
            )
            await orchestrator.flush()
            snapshot = await orchestrator.weekly_snapshot()
        finally:
            await orchestrator.close()
        send_observations = snapshot.observations.get("send.duration", {})
        assert len(send_observations) == 1
        (tags, observation), = send_observations.items()
        assert dict(tags)["unit"] == "seconds"
        assert observation.count == 1

    asyncio.run(run())


def test_orchestrator_disables_metrics_backend_when_metrics_none() -> None:
    metrics.reset_for_test()
    service = MetricsService()

    async def run() -> None:
        orchestrator_with_metrics = Orchestrator(
            sender=_InstrumentedSender(),
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
            metrics=service,
            platform="slack",
        )
        try:
            await orchestrator_with_metrics.enqueue(
                "success-1", job="success-job", platform="slack", channel="general"
            )
            await orchestrator_with_metrics.flush()
        finally:
            await orchestrator_with_metrics.close()

        orchestrator_without_metrics = Orchestrator(
            sender=_InstrumentedSender(),
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
            metrics=None,
            platform="slack",
        )
        try:
            await orchestrator_without_metrics.enqueue(
                "success-2", job="success-job", platform="slack", channel="general"
            )
            await orchestrator_without_metrics.flush()
        finally:
            await orchestrator_without_metrics.close()

    asyncio.run(run())

    snapshot = metrics.weekly_snapshot()
    success_job = snapshot["success_rate"]["success-job"]
    assert success_job["success"] == 1
    assert not metrics._AGGREGATOR.backend_configured
