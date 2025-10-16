import logging

import pytest

from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter import PermitDecision, PermitGate


class DummyMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def increment(self, name: str, tags: dict[str, str]) -> None:
        self.calls.append((name, tags))


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
    assert metrics.calls == []


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

    assert metrics.calls == [
        (
            "quota_denied",
            {"platform": "discord", "channel": "ch", "code": "daily_limit"},
        )
    ]
    assert "daily limit" in caplog.text


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

    current[0] += 61
    allowed_again = gate.permit("discord", "reset")
    assert allowed_again.allowed is True
    assert allowed_again.reason is None
    assert allowed_again.retryable is True

    assert len(metrics.calls) == 1
    assert metrics.calls[0][1]["code"] == "burst_limit"
