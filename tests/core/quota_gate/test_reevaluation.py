from __future__ import annotations

import logging

from llm_generic_bot.core.arbiter import PermitGate

from ._fixtures import DummyMetrics, _FakeQuotaConfig, _FakeQuotaTier


def test_quota_permit_deny_sets_reevaluation_on_repeated_calls() -> None:
    metrics = DummyMetrics()
    current = [0.0]

    def time_fn() -> float:
        return current[0]

    tiers = (
        _FakeQuotaTier(
            code="burst_once",
            limit=1,
            window_minutes=10,
            message="burst limit reached",
            retryable=True,
            reevaluation="burst_reeval",
        ),
    )

    gate = PermitGate(
        per_channel=_FakeQuotaConfig(tiers=tiers),
        metrics=metrics.increment,
        logger=logging.getLogger("quota"),
        time_fn=time_fn,
    )

    first = gate.permit("discord", "permits")
    assert first.allowed is True
    assert first.reevaluation is None

    current[0] += 1
    denial = gate.permit("discord", "permits")
    assert denial.allowed is False
    assert denial.reevaluation == "burst_reeval"

    current[0] += 1
    repeat_denial = gate.permit("discord", "permits")
    assert repeat_denial.allowed is False
    assert repeat_denial.reevaluation == "burst_reeval"
