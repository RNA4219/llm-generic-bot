from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Mapping, MutableMapping, Optional

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

import llm_generic_bot.core.orchestrator as orchestrator_module
from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import (
    MetricsRecorder,
    Orchestrator,
    PermitDecision,
    _SendRequest,
)

metrics_module = orchestrator_module.metrics_module

pytestmark = pytest.mark.anyio("asyncio")


class DummyCooldown(CooldownGate):
    def __init__(self) -> None:
        self.calls: list[tuple[str, Optional[str], str]] = []

    def note_post(self, platform: str, channel: Optional[str], job: str) -> None:  # type: ignore[override]
        self.calls.append((platform, channel, job))


class DummyDedupe(NearDuplicateFilter):
    def __init__(self, *, allowed: bool = True) -> None:
        super().__init__(k=5, threshold=0.5)
        self.allowed = allowed
        self.checked: list[str] = []

    def permit(self, text: str) -> bool:  # type: ignore[override]
        self.checked.append(text)
        return self.allowed


class DummySender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Optional[str], str]] = []

    async def send(self, text: str, channel: Optional[str] = None, *, job: Optional[str] = None) -> None:
        await asyncio.sleep(0)
        self.sent.append((text, channel, job or ""))


class RecordingMetrics(MetricsRecorder):
    def __init__(self) -> None:
        self.counts: MutableMapping[str, Counter[tuple[tuple[str, str], ...]]] = {}
        self.observations: dict[str, list[tuple[Mapping[str, str] | None, float]]] = {}

    @staticmethod
    def _normalize(tags: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
        if not tags:
            return ()
        return tuple(sorted(tags.items()))

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        counter = self.counts.setdefault(name, Counter())
        counter[self._normalize(tags)] += 1

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        bucket = self.observations.setdefault(name, [])
        bucket.append((dict(tags) if tags else None, value))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def make_orchestrator() -> Callable[..., Orchestrator]:
    created: list[Orchestrator] = []

    async def _factory(**kwargs: object) -> Orchestrator:
        orchestrator = Orchestrator(**kwargs)
        created.append(orchestrator)
        return orchestrator

    yield _factory

    for orchestrator in created:
        await orchestrator.close()


def _capture_events() -> tuple[list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]], Callable[..., None]]:
    recorded: list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]] = []

    def _recorder(
        name: str,
        tags: Mapping[str, str],
        *,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, object] | None = None,
        force: bool = False,
    ) -> None:
        recorded.append(
            (
                name,
                dict(tags),
                dict(measurements) if measurements else None,
                dict(metadata) if metadata else None,
                force,
            )
        )

    return recorded, _recorder


async def test_process_success_records(monkeypatch: pytest.MonkeyPatch, make_orchestrator: Callable[..., Orchestrator]) -> None:
    sender = DummySender()
    cooldown = DummyCooldown()
    dedupe = DummyDedupe()
    metrics = RecordingMetrics()
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
    events, recorder = _capture_events()
    monkeypatch.setattr(orchestrator, "_record_event", recorder)

    request = _SendRequest(
        text="晴れです",
        job="weather",
        platform="discord",
        channel="general",
        correlation_id="corr-success",
        engagement_score=0.42,
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
    assert payload["permit_tags"] == {"engagement_score": "0.42"}
    assert events[0][0] == "send.success"
    assert events[0][3] == {"correlation_id": "corr-success", "engagement_score": 0.42}


async def test_process_denied(monkeypatch: pytest.MonkeyPatch, make_orchestrator: Callable[..., Orchestrator]) -> None:
    sender = DummySender()
    cooldown = DummyCooldown()
    dedupe = DummyDedupe()
    metrics = RecordingMetrics()
    denied: list[dict[str, object]] = []

    def fake_report_permit_denied(
        *,
        job: str,
        platform: str,
        channel: Optional[str],
        reason: str,
        permit_tags: Mapping[str, str] | None,
    ) -> None:
        denied.append(
            {
                "job": job,
                "platform": platform,
                "channel": channel,
                "reason": reason,
                "permit_tags": dict(permit_tags) if permit_tags else None,
            }
        )

    monkeypatch.setattr(metrics_module, "report_permit_denied", fake_report_permit_denied)

    orchestrator = await make_orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=lambda *_: PermitDecision(False, "blocked", False, "job-denied"),
        metrics=metrics,
        platform="discord",
    )
    events, recorder = _capture_events()
    monkeypatch.setattr(orchestrator, "_record_event", recorder)

    await orchestrator._process(
        _SendRequest(
            text="hello",
            job="weather",
            platform="discord",
            channel="general",
            correlation_id="corr-denied",
        )
    )

    assert not sender.sent
    assert not cooldown.calls
    assert not dedupe.checked
    assert denied == [
        {
            "job": "job-denied",
            "platform": "discord",
            "channel": "general",
            "reason": "blocked",
            "permit_tags": {"retryable": "false"},
        }
    ]
    assert events == [
        (
            "send.denied",
            {
                "job": "job-denied",
                "platform": "discord",
                "channel": "general",
                "retryable": "false",
            },
            None,
            {
                "correlation_id": "corr-denied",
                "reason": "blocked",
                "retryable": False,
            },
            False,
        )
    ]


async def test_process_duplicate(monkeypatch: pytest.MonkeyPatch, make_orchestrator: Callable[..., Orchestrator]) -> None:
    sender = DummySender()
    cooldown = DummyCooldown()
    dedupe = DummyDedupe(allowed=False)
    metrics = RecordingMetrics()

    orchestrator = await make_orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=lambda *_: PermitDecision.allow(),
        metrics=metrics,
        platform="discord",
    )
    events, recorder = _capture_events()
    monkeypatch.setattr(orchestrator, "_record_event", recorder)

    await orchestrator._process(
        _SendRequest(
            text="hello",
            job="weather",
            platform="discord",
            channel="general",
            correlation_id="corr-dup",
        )
    )

    assert sender.sent == []
    assert cooldown.calls == []
    assert dedupe.checked == ["hello"]
    assert metrics.counts == {
        "send.duplicate": Counter(
            {
                (
                    ("channel", "general"),
                    ("job", "weather"),
                    ("platform", "discord"),
                    ("retryable", "false"),
                    ("status", "duplicate"),
                ): 1
            }
        )
    }
    assert events == [
        (
            "send.duplicate",
            {
                "job": "weather",
                "platform": "discord",
                "channel": "general",
                "status": "duplicate",
                "retryable": "false",
            },
            None,
            {
                "correlation_id": "corr-dup",
                "status": "duplicate",
                "retryable": False,
            },
            False,
        )
    ]
