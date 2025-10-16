from __future__ import annotations

from collections import Counter
from typing import Callable, Mapping, Optional

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator

from .conftest import (
    DummyCooldown,
    DummyDedupe,
    PermitDecision,
    RecordingMetrics,
    _SendRequest,
    metrics_module,
)

pytestmark = pytest.mark.anyio("asyncio")


class BoomError(RuntimeError):
    pass


async def test_process_exception(
    monkeypatch: pytest.MonkeyPatch,
    make_orchestrator: Callable[..., Orchestrator],
    dummy_cooldown: DummyCooldown,
    dummy_dedupe: DummyDedupe,
    recording_metrics: RecordingMetrics,
    capture_events: tuple[
        list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]],
        Callable[..., None],
    ],
) -> None:
    failure_reports: list[dict[str, object]] = []

    async def fake_report_send_failure(
        *,
        job: str,
        platform: str,
        channel: Optional[str],
        duration_seconds: float,
        error_type: str,
    ) -> None:
        failure_reports.append(
            {
                "job": job,
                "platform": platform,
                "channel": channel,
                "duration": duration_seconds,
                "error_type": error_type,
            }
        )

    monkeypatch.setattr(metrics_module, "report_send_failure", fake_report_send_failure)

    class FailingSender:
        def __init__(self) -> None:
            self.sent: list[tuple[str, Optional[str], Optional[str]]] = []

        async def send(
            self,
            text: str,
            channel: Optional[str] = None,
            *,
            job: Optional[str] = None,
        ) -> None:
            self.sent.append((text, channel, job))
            raise BoomError("network down")

    sender = FailingSender()
    cooldown = dummy_cooldown
    dedupe = dummy_dedupe
    metrics = recording_metrics

    orchestrator = await make_orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=lambda *_: PermitDecision.allow(),
        metrics=metrics,
        platform="discord",
    )
    events, recorder = capture_events
    monkeypatch.setattr(orchestrator, "_record_event", recorder)

    await orchestrator._process(
        _SendRequest(
            text="storm",
            job="weather",
            platform="discord",
            channel="general",
            correlation_id="corr-error",
        )
    )

    assert sender.sent == [("storm", "general", "weather")]
    assert cooldown.calls == []
    assert dedupe.checked == ["storm"]
    assert len(failure_reports) == 1
    failure_payload = failure_reports[0]
    assert failure_payload["job"] == "weather"
    assert failure_payload["platform"] == "discord"
    assert failure_payload["channel"] == "general"
    assert failure_payload["error_type"] == "BoomError"
    assert isinstance(failure_payload["duration"], float)
    assert metrics.counts == {
        "send.failure": Counter(
            {
                (
                    ("channel", "general"),
                    ("error", "BoomError"),
                    ("job", "weather"),
                    ("platform", "discord"),
                ): 1
            }
        )
    }
    duration_entries = metrics.observations["send.duration"]
    assert len(duration_entries) == 1
    observation_tags, value = duration_entries[0]
    assert observation_tags == {
        "channel": "general",
        "job": "weather",
        "platform": "discord",
        "unit": "seconds",
    }
    assert isinstance(value, float)
    assert events[0][0] == "send.failure"
    assert events[0][1]["error"] == "BoomError"
    assert events[0][2] == {"duration_sec": pytest.approx(value)}
    assert events[0][3]["correlation_id"] == "corr-error"
    assert events[0][3]["error_type"] == "BoomError"
    assert events[0][4] is True
