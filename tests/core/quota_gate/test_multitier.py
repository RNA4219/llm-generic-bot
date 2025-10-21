from __future__ import annotations

import logging

import pytest

from llm_generic_bot.core.arbiter import (
    PermitGate,
    PermitGateConfig,
    PermitQuotaLevel,
)

from ._fixtures import DummyMetrics, _FakeQuotaConfig, _FakeQuotaTier


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

    name, tags = metrics.calls[-1]
    assert name == "quota_denied"
    assert tags["platform"] == "discord"
    assert tags["channel"] == "tiered"
    assert tags["code"] == expected_code
    assert tags["reevaluation"] == expected_reevaluation
    assert tags["level"] == "per_channel"
    assert tags["retryable"] == ("true" if expected_retryable else "false")


def test_quota_multilayer_tiers_respect_windows_and_retryable() -> None:
    metrics = DummyMetrics()
    current = [0.0]

    def time_fn() -> float:
        return current[0]

    channel_tiers = (
        _FakeQuotaTier(
            code="channel_burst",
            limit=1,
            window_minutes=1,
            message="channel burst reached",
            retryable=True,
            reevaluation="channel",
        ),
    )
    platform_tiers = (
        _FakeQuotaTier(
            code="platform_daily",
            limit=2,
            window_minutes=3,
            message="platform limit reached",
            retryable=False,
            reevaluation="platform",
        ),
    )

    gate = PermitGate(
        per_channel=_FakeQuotaConfig(tiers=channel_tiers),
        metrics=metrics.increment,
        logger=logging.getLogger("quota"),
        time_fn=time_fn,
        config=PermitGateConfig(
            levels=(
                PermitQuotaLevel(name="per_channel", quota=_FakeQuotaConfig(tiers=channel_tiers)),
                PermitQuotaLevel(name="per_platform", quota=_FakeQuotaConfig(tiers=platform_tiers)),
            )
        ),
    )

    first = gate.permit("discord", "ml")
    assert first.allowed is True

    current[0] += 10.0
    channel_denial = gate.permit("discord", "ml")
    assert channel_denial.allowed is False
    assert channel_denial.reason == "channel burst reached"
    assert channel_denial.retryable is True
    assert channel_denial.retry_after == pytest.approx(50.0)

    current[0] += 55.0
    second = gate.permit("discord", "ml")
    assert second.allowed is True

    current[0] += 61.0
    third_denial = gate.permit("discord", "ml")
    assert third_denial.allowed is False
    assert third_denial.reason == "platform limit reached"
    assert third_denial.retryable is False
    assert third_denial.retry_after == pytest.approx(54.0)


def test_quota_multilayer_tier_progression_requires_sequential_waits() -> None:
    metrics = DummyMetrics()
    current = [0.0]

    def time_fn() -> float:
        return current[0]

    channel_tiers = (
        _FakeQuotaTier(
            code="channel_burst",
            limit=1,
            window_minutes=1,
            message="channel burst reached",
            retryable=True,
            reevaluation="channel",
        ),
    )
    platform_tiers = (
        _FakeQuotaTier(
            code="platform_daily",
            limit=1,
            window_minutes=5,
            message="platform limit reached",
            retryable=False,
            reevaluation="platform",
        ),
    )

    gate = PermitGate(
        per_channel=_FakeQuotaConfig(tiers=channel_tiers),
        metrics=metrics.increment,
        logger=logging.getLogger("quota"),
        time_fn=time_fn,
        config=PermitGateConfig(
            levels=(
                PermitQuotaLevel(name="per_channel", quota=_FakeQuotaConfig(tiers=channel_tiers)),
                PermitQuotaLevel(name="per_platform", quota=_FakeQuotaConfig(tiers=platform_tiers)),
            )
        ),
    )

    assert gate.permit("discord", "multitier").allowed is True

    current[0] += 10.0
    channel_denial = gate.permit("discord", "multitier")
    assert channel_denial.allowed is False
    assert channel_denial.level == "per_channel"
    assert channel_denial.retryable is True
    assert channel_denial.retry_after == pytest.approx(50.0)
    assert channel_denial.reason == "channel burst reached"
    assert metrics.calls[-1][1]["level"] == "per_channel"

    current[0] += 61.0
    platform_denial = gate.permit("discord", "multitier")
    assert platform_denial.allowed is False
    assert platform_denial.level == "per_platform"
    assert platform_denial.retryable is False
    assert platform_denial.retry_after == pytest.approx(229.0)
    assert platform_denial.reason == "platform limit reached"
    assert metrics.calls[-1][1]["level"] == "per_platform"

    current[0] += 240.0
    final_permit = gate.permit("discord", "multitier")
    assert final_permit.allowed is True

    assert metrics.calls[-1][1]["code"] == "platform_daily"
    assert metrics.calls[-1][1]["level"] == "per_platform"
