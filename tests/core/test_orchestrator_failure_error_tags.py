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


async def test_weekly_snapshot_includes_error_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_service = MetricsService()
    async def _noop_report_send_failure(**_: object) -> None:
        return None

    monkeypatch.setattr(
        "llm_generic_bot.infra.metrics.report_send_failure",
        _noop_report_send_failure,
    )
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

    tags_with_error = {
        key: entry
        for key, entry in failure_metrics.items()
        if dict(key).get("error") == "RuntimeError"
    }
    assert tags_with_error, "missing error tag on send.failure"
