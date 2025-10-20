from __future__ import annotations

import logging

from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter import PermitDecision, PermitGate

from ._fixtures import DummyMetrics


def test_quota_permit_allows_within_limits() -> None:
    metrics = DummyMetrics()
    now = [0.0]

    def time_fn() -> float:
        return now[0]

    gate = PermitGate(
        per_channel=PerChannelQuotaConfig(day=5, window_minutes=1, burst_limit=3),
        metrics=metrics.increment,
        logger=logging.getLogger("test"),
        time_fn=time_fn,
    )

    decision = gate.permit("discord", "general")
    assert isinstance(decision, PermitDecision)
    assert decision.allowed is True
    assert decision.reason is None
    assert decision.retryable is True
    assert decision.reevaluation is None
    assert metrics.calls == []
