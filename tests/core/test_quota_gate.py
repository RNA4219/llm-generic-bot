from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from tests.core.quota_gate.test_basic_allow import *  # noqa: F401,F403
from tests.core.quota_gate.test_denial_metrics import *  # noqa: F401,F403
from tests.core.quota_gate.test_multitier import *  # noqa: F401,F403
from tests.core.quota_gate.test_reevaluation import *  # noqa: F401,F403
from tests.core.quota_gate.test_window_reset import *  # noqa: F401,F403

from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter import LEGACY_PERMIT_GATE_REFACTOR_CHECKLIST
from llm_generic_bot.core.arbiter.gate import PermitGate
from llm_generic_bot.core.arbiter.models import (
    PermitDecision,
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

    name, tags = metrics.calls[-1]
    assert name == "quota_denied"
    assert tags["platform"] == "discord"
    assert tags["channel"] == "tiered"
    assert tags["code"] == expected_code
    assert tags["reevaluation"] == expected_reevaluation
    assert tags["level"] == "per_channel"
    assert tags["retryable"] == ("true" if expected_retryable else "false")


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

    assert metrics.calls[-1][1]["code"] == "platform_daily"
    assert metrics.calls[-1][1]["level"] == "per_platform"


def test_legacy_module_reexports_permit_gate_components() -> None:
    from llm_generic_bot.core import arbiter as legacy_arbiter
    from llm_generic_bot.core.arbiter.gate import PermitGate as GatePermitGate
    from llm_generic_bot.core.arbiter.models import (
        PermitDecision as ModelsPermitDecision,
        PermitGateConfig as ModelsPermitGateConfig,
    )

    assert legacy_arbiter.PermitGate is GatePermitGate
    assert legacy_arbiter.PermitDecision is ModelsPermitDecision
    assert legacy_arbiter.PermitGateConfig is ModelsPermitGateConfig
    checklist = LEGACY_PERMIT_GATE_REFACTOR_CHECKLIST
    assert any("呼び出しサイト" in item for item in checklist)
