import datetime as dt
from collections import deque
from typing import Deque, Dict, List, Mapping, Optional

import zoneinfo

import pytest

from llm_generic_bot.core.arbiter import PermitDecision as QuotaPermitDecision
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot import main as main_module


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class StubSender:
    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send(self, text: str, channel: Optional[str] = None) -> None:
        self.sent.append(text if channel is None else f"{channel}:{text}")


class StubPermitGate:
    def __init__(self, decisions: Deque[QuotaPermitDecision]) -> None:
        self.decisions = decisions
        self.calls: List[Dict[str, Optional[str]]] = []

    def permit(
        self, platform: str, channel: Optional[str], job: Optional[str] = None
    ) -> QuotaPermitDecision:
        self.calls.append({"platform": platform, "channel": channel, "job": job})
        return self.decisions.popleft()


class SequencedWeather:
    def __init__(self, values: Deque[str]) -> None:
        self.values = values

    async def __call__(self, _: Mapping[str, object]) -> str:
        return self.values.popleft()


async def test_daily_pipeline_uses_permit_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    settings: Dict[str, object] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"schedule": "00:00"},
    }

    queue = CoalesceQueue(window_seconds=0.0, threshold=2)
    sender = StubSender()
    decisions = deque(
        [
            QuotaPermitDecision(allowed=True, reason=None, retryable=True),
            QuotaPermitDecision(allowed=False, reason="quota", retryable=True),
        ]
    )
    permit_gate = StubPermitGate(decisions)

    weather_values = deque(["one", "two", "three", "four"])
    monkeypatch.setattr(
        main_module,
        "build_weather_post",
        SequencedWeather(weather_values),
    )

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        sender=sender,
        queue=queue,
        permit_gate=permit_gate,
    )
    scheduler.jitter_enabled = False

    assert "weather" in jobs

    now = dt.datetime(2024, 1, 1, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
    now_ts = now.timestamp()

    await scheduler._run_due_jobs(now)
    await scheduler._run_due_jobs(now)
    await scheduler.dispatch_ready_batches(now_ts)
    await orchestrator.flush()

    assert sender.sent == ["general:one\ntwo"]
    assert len(permit_gate.calls) == 1

    await scheduler._run_due_jobs(now)
    await scheduler._run_due_jobs(now)
    await scheduler.dispatch_ready_batches(now_ts)
    await orchestrator.flush()

    assert sender.sent == ["general:one\ntwo"]
    assert len(permit_gate.calls) == 2
    await orchestrator.close()
