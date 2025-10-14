from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.arbiter import PermitDecision
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features.dm_digest import DigestLogEntry
from llm_generic_bot.features.news import NewsFeedItem, SummaryError

pytestmark = pytest.mark.anyio("asyncio")


class StubPermitGate:
    def __init__(self) -> None:
        self.allowed = False
        self.calls: list[tuple[str, str | None, str | None]] = []

    def permit(self, platform: str, channel: str | None, job: str | None = None) -> PermitDecision:
        job_name = job or "job"
        self.calls.append((platform, channel, job_name))
        if job_name == "dm_digest" and not self.allowed:
            return PermitDecision(allowed=False, reason="denied", retryable=True, job=job_name)
        return PermitDecision(allowed=True, reason=None, retryable=True, job=job_name)


class FlakyNewsSummary:
    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, item: NewsFeedItem, *, language: str = "ja") -> str:
        del language
        self.calls += 1
        if self.calls == 1:
            raise SummaryError("temporary", retryable=True)
        if self.calls == 2:
            raise SummaryError("fallback", retryable=False)
        return f"summary:{item.title}"


class StaticLogProvider:
    def __init__(self, entries: list[DigestLogEntry]) -> None:
        self.entries = entries
        self.calls = 0

    async def collect(self, channel: str, *, limit: int) -> list[DigestLogEntry]:
        del channel
        self.calls += 1
        assert limit >= len(self.entries)
        return self.entries


class EchoSummary:
    async def summarize(self, text: str, *, max_events: int | None = None) -> str:
        del max_events
        return f"digest:{len(text.splitlines())}"


class FlakySender:
    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []
        self.fail_next = True

    async def send(
        self,
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
        recipient_id: str | None = None,
    ) -> None:
        self.attempts.append(
            {
                "text": text,
                "channel": channel,
                "correlation_id": correlation_id,
                "job": job,
                "recipient": recipient_id,
            }
        )
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("temporary failure")


def _load_settings() -> dict[str, Any]:
    data = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    data["weather"]["enabled"] = False
    data["omikuji"]["enabled"] = False
    return data


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.usefixtures("anyio_backend")
async def test_runtime_handles_permit_cooldown_and_provider_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    settings = _load_settings()
    news_summary = FlakyNewsSummary()
    flaky_sender = FlakySender()
    log_provider = StaticLogProvider(
        [
            DigestLogEntry(datetime(2024, 1, 1, tzinfo=timezone.utc), "INFO", "start"),
            DigestLogEntry(datetime(2024, 1, 1, 1, tzinfo=timezone.utc), "WARN", "warned"),
        ]
    )

    async def fake_feed(_url: str, *, limit: int | None = None) -> list[NewsFeedItem]:
        del limit
        return [NewsFeedItem(title="headline", link="https://example.com", summary="prefill")]

    settings["news"].update(
        {
            "max_items": 1,
            "feed_provider": SimpleNamespace(fetch=fake_feed),
            "summary_provider": SimpleNamespace(summarize=news_summary.summarize),
            "suppress_cooldown": False,
        }
    )
    settings["dm_digest"].update(
        {
            "log_provider": log_provider,
            "summary_provider": EchoSummary(),
            "sender": flaky_sender,
            "max_attempts": 2,
        }
    )

    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    gate = StubPermitGate()
    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        queue=queue,
        permit_gate=gate,
    )
    del scheduler

    news_job = jobs["news"]
    platform = orchestrator._default_platform  # type: ignore[attr-defined]
    channel = settings["news"].get("channel")
    job_name = settings["news"].get("job", "news")
    orchestrator._cooldown.note_post(platform, channel, job_name)

    result_blocked = await news_job()
    assert result_blocked is None
    assert news_summary.calls == 0

    key = (platform or "-", channel or "-", job_name or "-")
    history = orchestrator._cooldown.history.setdefault(key, deque())
    history.clear()

    result_ready = await news_job()
    assert result_ready is not None
    assert "prefill" in result_ready
    assert news_summary.calls == 2

    dm_job = jobs["dm_digest"]
    gate.allowed = False
    await dm_job()
    assert not flaky_sender.attempts

    gate.allowed = True
    flaky_sender.fail_next = True
    await dm_job()
    assert len(flaky_sender.attempts) == 2
    assert {attempt["job"] for attempt in flaky_sender.attempts} == {
        settings["dm_digest"].get("job", "dm_digest")
    }
