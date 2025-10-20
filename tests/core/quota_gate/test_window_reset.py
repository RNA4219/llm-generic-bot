from __future__ import annotations

import logging

from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter import PermitGate

from ._fixtures import DummyMetrics


def test_quota_reset_after_window() -> None:
    metrics = DummyMetrics()
    current = [0.0]

    def time_fn() -> float:
        return current[0]

    gate = PermitGate(
        per_channel=PerChannelQuotaConfig(day=10, window_minutes=1, burst_limit=2),
        metrics=metrics.increment,
        logger=logging.getLogger("quota"),
        time_fn=time_fn,
    )

    assert gate.permit("discord", "reset").allowed is True
    current[0] += 1
    assert gate.permit("discord", "reset").allowed is True
    current[0] += 1

    denied = gate.permit("discord", "reset")
    assert denied.allowed is False
    assert denied.retryable is True
    assert denied.reason is not None and "burst" in denied.reason
    assert denied.reevaluation is None

    current[0] += 61
    allowed_again = gate.permit("discord", "reset")
    assert allowed_again.allowed is True
    assert allowed_again.reason is None
    assert allowed_again.retryable is True

    assert len(metrics.calls) == 1
    assert metrics.calls[0][1]["code"] == "burst_limit"
