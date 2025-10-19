import logging
from dataclasses import dataclass

import pytest

from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter import (
    PermitDecision,
    PermitGate,
    PermitGateConfig,
    PermitGateHooks,
    PermitQuotaLevel,
    PermitReevaluationOutcome,
    PermitRejectionContext,
)


class DummyMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def increment(self, name: str, tags: dict[str, str]) -> None:
        self.calls.append((name, tags))


@dataclass(frozen=True)
class _FakeQuotaTier:
    code: str
    limit: int
    window_minutes: int
    message: str
    retryable: bool
    reevaluation: str

    @property
    def window_seconds(self) -> int:
        return self.window_minutes * 60


@dataclass(frozen=True)
class _FakeQuotaConfig:
    tiers: tuple[_FakeQuotaTier, ...]

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
            {
                "platform": "discord",
                "channel": "ch",
                "code": "daily_limit",
                "level": "per_channel",
                "reeval_reason": "daily limit reached",
            },
        )
    ]
    assert "daily limit" in caplog.text
    assert "per_channel" in caplog.text


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


@pytest.mark.parametrize(
    (
        "attempt_times",
        "expected_reason",
        "expected_code",
        "expected_retryable",
        "expected_reevaluation",
    ),
    (
        (
            (0.0, 10.0, 20.0),
            "first tier reached",
            "burst_tier1",
            True,
            "tier1",
        ),
        (
            (0.0, 61.0, 122.0, 183.0),
            "second tier reached",
            "burst_tier2",
            False,
            "tier2",
        ),
    ),
)
def test_quota_hierarchical_denials_record_metrics(
    attempt_times: tuple[float, ...],
    expected_reason: str,
    expected_code: str,
    expected_retryable: bool,
    expected_reevaluation: str,
) -> None:
    metrics = DummyMetrics()
    current = [0.0]

    def time_fn() -> float:
        return current[0]

    tiers = (
        _FakeQuotaTier(
            code="burst_tier1",
            limit=2,
            window_minutes=1,
            message="first tier reached",
            retryable=True,
            reevaluation="tier1",
        ),
        _FakeQuotaTier(
            code="burst_tier2",
            limit=3,
            window_minutes=5,
            message="second tier reached",
            retryable=False,
            reevaluation="tier2",
        ),
    )
    gate = PermitGate(
        per_channel=_FakeQuotaConfig(tiers=tiers),
        metrics=metrics.increment,
        logger=logging.getLogger("quota"),
        time_fn=time_fn,
    )

    for ts in attempt_times[:-1]:
        current[0] = ts
        decision = gate.permit("discord", "tiered")
        assert decision.allowed is True

    current[0] = attempt_times[-1]
    denial = gate.permit("discord", "tiered")
    assert denial.allowed is False
    assert denial.reason == expected_reason
    assert denial.retryable is expected_retryable

    assert metrics.calls[-1] == (
        "quota_denied",
        {
            "platform": "discord",
            "channel": "tiered",
            "code": expected_code,
            "level": "per_channel",
            "reeval_reason": expected_reason,
            "reevaluation": expected_reevaluation,
        },
    )


@pytest.mark.parametrize(
    ("outcome_kwargs", "expected_allowed", "expected_retryable", "expected_reason"),
    (
        ({"reason": "retry soon", "retry_after": 30.0}, False, True, "burst limit reached"),
        ({"reason": "manual override", "allowed": True}, True, True, None),
    ),
)
def test_quota_reevaluation_callbacks_apply_outcome(
    outcome_kwargs: dict[str, object],
    expected_allowed: bool,
    expected_retryable: bool,
    expected_reason: str | None,
) -> None:
    metrics = DummyMetrics()
    now = [0.0]

    def time_fn() -> float:
        return now[0]

    contexts: list[PermitRejectionContext] = []

    def channel_key(platform: str, channel: str | None, job: str | None) -> tuple[str, str]:
        return (platform or "-", channel or "-")

    def platform_key(platform: str, channel: str | None, job: str | None) -> tuple[str, str]:
        del channel, job
        return (platform or "-", "-")

    base_quota = PerChannelQuotaConfig(day=5, window_minutes=1, burst_limit=5)
    strict_quota = PerChannelQuotaConfig(day=1, window_minutes=1, burst_limit=1)

    outcome = PermitReevaluationOutcome(level="per_platform", **outcome_kwargs)

    def hook(context: PermitRejectionContext) -> PermitReevaluationOutcome:
        contexts.append(context)
        return outcome

    gate = PermitGate(
        per_channel=strict_quota,
        metrics=metrics.increment,
        logger=logging.getLogger("quota"),
        time_fn=time_fn,
        config=PermitGateConfig(
            levels=(
                PermitQuotaLevel(name="per_channel", quota=base_quota, key_fn=channel_key),
                PermitQuotaLevel(name="per_platform", quota=strict_quota, key_fn=platform_key),
            ),
            hooks=PermitGateHooks(on_rejection=hook),
        ),
    )

    assert gate.permit("discord", "general").allowed is True
    now[0] += 1
    decision = gate.permit("discord", "general")

    assert decision.allowed is expected_allowed
    assert decision.reason == expected_reason
    assert decision.reevaluation == outcome
    assert decision.retryable is expected_retryable

    assert contexts == [
        PermitRejectionContext(
            platform="discord",
            channel="general",
            job=None,
            level="per_platform",
            code="burst_limit",
            message="burst limit reached",
        )
    ]
    assert metrics.calls[-1] == (
        "quota_denied",
        {
            "platform": "discord",
            "channel": "general",
            "code": "burst_limit",
            "level": "per_platform",
            "reeval_reason": "burst limit reached",
        },
    )
