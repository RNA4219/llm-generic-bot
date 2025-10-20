from __future__ import annotations

from typing import Callable, Mapping, Optional

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator

from .conftest import (
    DummyCooldown,
    DummyDedupe,
    DummySender,
    PermitDecision,
    RecordingMetrics,
    _SendRequest,
    metrics_module,
)

pytestmark = pytest.mark.anyio("asyncio")


async def test_process_success_records(
    monkeypatch: pytest.MonkeyPatch,
    make_orchestrator: Callable[..., Orchestrator],
    dummy_sender: DummySender,
    dummy_cooldown: DummyCooldown,
    dummy_dedupe: DummyDedupe,
    recording_metrics: RecordingMetrics,
    capture_events: tuple[
        list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]],
        Callable[..., None],
    ],
) -> None:
    sender = dummy_sender
    cooldown = dummy_cooldown
    dedupe = dummy_dedupe
    metrics = recording_metrics
    calls: list[dict[str, object]] = []

    async def fake_report_send_success(
        *,
        job: str,
        platform: str,
        channel: Optional[str],
        duration_seconds: float,
        permit_tags: Mapping[str, str] | None,
    ) -> None:
        calls.append(
            {
                "job": job,
                "platform": platform,
                "channel": channel,
                "duration": duration_seconds,
                "permit_tags": dict(permit_tags) if permit_tags else None,
            }
        )

    monkeypatch.setattr(metrics_module, "report_send_success", fake_report_send_success)

    orchestrator = await make_orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=lambda *_: PermitDecision.allow(job="overridden"),
        metrics=metrics,
        platform="discord",
    )
    events, recorder = capture_events
    monkeypatch.setattr(orchestrator, "_record_event", recorder)

    request = _SendRequest(
        text="晴れです",
        job="weather",
        platform="discord",
        channel="general",
        correlation_id="corr-success",
        engagement_score=0.42,
        engagement_long_term=0.75,
        engagement_permit_quota=0.5,
    )

    await orchestrator._process(request)

    assert sender.sent == [("晴れです", "general", "overridden")]
    assert cooldown.calls == [("discord", "general", "overridden")]
    assert dedupe.checked == ["晴れです"]
    assert len(calls) == 1
    payload = calls[0]
    assert payload["job"] == "overridden"
    assert payload["platform"] == "discord"
    assert payload["channel"] == "general"
    assert isinstance(payload["duration"], float)
    assert payload["permit_tags"] == {
        "engagement_score": "0.42",
        "engagement_trend": "0.75",
        "permit_quota": "0.5",
    }
    assert events[0][0] == "send.success"
    assert events[0][3] == {
        "correlation_id": "corr-success",
        "engagement_score": 0.42,
        "engagement_long_term": 0.75,
        "permit_quota": 0.5,
    }
