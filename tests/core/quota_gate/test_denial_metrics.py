from __future__ import annotations

import logging

import pytest

from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter import PermitGate

from ._fixtures import DummyMetrics


def test_quota_denial_records_metrics_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    metrics = DummyMetrics()
    current = [0.0]

    def time_fn() -> float:
        return current[0]

    gate = PermitGate(
        per_channel=PerChannelQuotaConfig(day=2, window_minutes=10, burst_limit=5),
        metrics=metrics.increment,
        logger=logging.getLogger("quota"),
        time_fn=time_fn,
    )

    caplog.set_level(logging.WARNING)

    assert gate.permit("discord", "ch").allowed is True
    current[0] += 1
    assert gate.permit("discord", "ch").allowed is True
    current[0] += 1

    decision = gate.permit("discord", "ch")
    assert decision.allowed is False
    assert decision.retryable is False
    assert decision.reason is not None and "daily" in decision.reason

    assert len(metrics.calls) == 1
    name, tags = metrics.calls[0]
    assert name == "quota_denied"
    assert tags["platform"] == "discord"
    assert tags["channel"] == "ch"
    assert tags["code"] == "daily_limit"
    assert tags["level"] == "per_channel"
    assert tags["retryable"] == "false"
    assert tags["window_sec"] == str(86400)
    assert tags["reeval_reason"] == "daily limit reached"
    assert "daily limit" in caplog.text
    assert "per_channel" in caplog.text
