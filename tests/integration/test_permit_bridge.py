from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

import pytest

from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter import PermitGate
from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import Orchestrator


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _StubSender:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str, channel: Optional[str] = None) -> None:
        self.sent.append(text if channel is None else f"{channel}:{text}")


class _StubMetrics:
    def __init__(self) -> None:
        self.increment_calls: list[tuple[str, Mapping[str, str]]] = []
        self.observe_calls: list[tuple[str, float, Mapping[str, str]]] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self.increment_calls.append((name, dict(tags or {})))

    def observe(
        self, name: str, value: float, tags: Mapping[str, str] | None = None
    ) -> None:
        self.observe_calls.append((name, value, dict(tags or {})))


@dataclass
class _TimeController:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, delta: float) -> None:
        self.value += delta


async def test_orchestrator_accepts_permit_gate_with_retryable() -> None:
    sender = _StubSender()
    metrics = _StubMetrics()
    cooldown = CooldownGate(window_sec=1, mult_min=1.0, mult_max=1.0, k_rate=0.0, k_time=0.0, k_eng=0.0)
    dedupe = NearDuplicateFilter(k=4, threshold=0.99)
    clock = _TimeController()
    gate = PermitGate(
        per_channel=PerChannelQuotaConfig(day=1, window_minutes=1, burst_limit=1),
        time_fn=clock,
    )
    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=gate.permit,
        metrics=metrics,
    )

    try:
        await orchestrator.enqueue(
            "first",
            job="weather",
            platform="discord",
            channel="general",
        )
        await orchestrator.flush()
        assert sender.sent == ["general:first"]
        assert ("send.success", {"job": "weather", "platform": "discord", "channel": "general"}) in metrics.increment_calls

        await orchestrator.enqueue(
            "second",
            job="weather",
            platform="discord",
            channel="general",
        )
        await orchestrator.flush()
        assert sender.sent == ["general:first"]
        denied_burst = metrics.increment_calls[-1]
        assert denied_burst[0] == "send.denied"
        assert denied_burst[1]["retryable"] == "true"

        clock.advance(120.0)
        await orchestrator.enqueue(
            "third",
            job="weather",
            platform="discord",
            channel="general",
        )
        await orchestrator.flush()
        assert sender.sent == ["general:first"]
        denied_daily = metrics.increment_calls[-1]
        assert denied_daily[1]["retryable"] == "false"
    finally:
        await orchestrator.close()
