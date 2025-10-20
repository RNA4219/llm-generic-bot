from __future__ import annotations

from typing import Optional, cast

import pytest

from llm_generic_bot.core.orchestrator import (
    Orchestrator,
    PermitDecision,
    PermitEvaluator,
)
from llm_generic_bot.features import weather

from ._helpers import (
    _CooldownRecorder,
    _DedupeStub,
    _MetricsStub,
    _SenderStub,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_send_success_log_contains_engagement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = _SenderStub()
    cooldown = _CooldownRecorder()
    dedupe = _DedupeStub()
    metrics = _MetricsStub()

    def _permit(_: str, __: Optional[str], ___: str) -> PermitDecision:
        return PermitDecision.allow()

    permit_fn = cast(PermitEvaluator, _permit)

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit_fn,
        metrics=metrics,
        platform="discord",
    )

    caplog.set_level("INFO")

    post = weather.WeatherPost("fine", engagement_score=0.6)
    await orchestrator.enqueue(post, job="weather", platform="discord", channel="town-square")
    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == ["fine"]
    record = next(r for r in caplog.records if getattr(r, "event", "") == "send_success")
    engagement_value = getattr(record, "engagement_score", None)
    assert isinstance(engagement_value, float)
    assert engagement_value == pytest.approx(0.6)

    tags = metrics.increments.get("send.success")
    assert tags is not None and tags[0]["engagement_score"] == "0.6"

    assert cooldown.recorded == [("discord", "town-square", "weather")]
