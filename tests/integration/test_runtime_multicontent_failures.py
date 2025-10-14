from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.orchestrator import PermitDecision
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features.news import NewsFeedItem, SummaryError
from llm_generic_bot.infra import metrics

pytestmark = pytest.mark.anyio("asyncio")


def _settings() -> Dict[str, Any]:
    settings: Dict[str, Any] = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    for key in ("weather", "omikuji", "dm_digest", "report"):
        cfg = settings.get(key)
        if isinstance(cfg, dict):
            cfg["enabled"] = False
    news = settings["news"]
    news["schedule"] = "00:00"
    news["priority"] = 5
    settings["cooldown"]["window_sec"] = 60
    settings["profiles"]["discord"]["channel"] = "discord-news"
    return settings


def _run_dispatch(scheduler: Any, text: str, *, created_at: float) -> None:
    job = scheduler._jobs[0]
    scheduler.queue.push(text, priority=job.priority, job=job.name, created_at=created_at, channel=job.channel)


def _providers(items: Iterable[NewsFeedItem], summarize: Any) -> tuple[Any, Any]:
    async def _fetch(_url: str, *, limit: int | None = None) -> Iterable[NewsFeedItem]:
        del _url, limit
        return list(items)

    return SimpleNamespace(fetch=_fetch), SimpleNamespace(summarize=summarize)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_permit_denied_records_metrics(caplog: pytest.LogCaptureFixture) -> None:
    metrics.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers([NewsFeedItem("t", "https://example.com")], _summarize)
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    class _Deny:
        def permit(self, platform: str, channel: str | None, job: str) -> PermitDecision:
            del platform, channel
            return PermitDecision(allowed=False, reason="quota", retryable=False, job=f"{job}-denied")

    caplog.set_level("INFO", logger="llm_generic_bot.core.orchestrator")
    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue, permit_gate=_Deny())
    scheduler.jitter_enabled = False

    text = await jobs["news"]()
    assert text
    _run_dispatch(scheduler, text, created_at=0.0)
    await scheduler.dispatch_ready_batches()
    await orchestrator.flush()

    denied = [record for record in caplog.records if record.message == "permit_denied"]
    assert denied and denied[0].job == "news-denied"
    assert metrics._AGGREGATOR.weekly_snapshot()["permit_denials"] == [
        {"job": "news-denied", "platform": "discord", "channel": "discord-news", "reason": "quota", "retryable": "false"}
    ]
    await orchestrator.close()


async def test_cooldown_resume_allows_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    current = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: current)

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        return f"summary-{language}"

    fetcher, summarizer = _providers([NewsFeedItem("title", "https://example.com", None)], _summarize)
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False
    orchestrator._cooldown.note_post("discord", "discord-news", "news")

    assert await jobs["news"]() is None
    current += settings["cooldown"]["window_sec"] + 1
    text = await jobs["news"]()
    assert text
    _run_dispatch(scheduler, text, created_at=current)
    await scheduler.dispatch_ready_batches(current)
    await orchestrator.flush()

    snapshot = metrics._AGGREGATOR.weekly_snapshot()
    assert snapshot["success_rate"]["news"]["success"] == 1
    await orchestrator.close()


async def test_summary_provider_retry_and_fallback(caplog: pytest.LogCaptureFixture) -> None:
    metrics.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    attempts = {"value": 0}

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del language
        attempts["value"] += 1
        if attempts["value"] == 1:
            raise SummaryError("temporary", retryable=True)
        raise SummaryError("fatal", retryable=False)

    fetcher, summarizer = _providers([NewsFeedItem("fallback", "https://example.com", None)], _summarize)
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer
    caplog.set_level("WARNING", logger="llm_generic_bot.features.news")

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    text = await jobs["news"]()
    assert text
    _run_dispatch(scheduler, text, created_at=0.0)
    await scheduler.dispatch_ready_batches()
    await orchestrator.flush()

    retry = [r for r in caplog.records if r.message == "news_summary_retry"]
    fallback = [r for r in caplog.records if r.message == "news_summary_fallback"]
    assert len(retry) == 1 and retry[0].attempt == 1
    assert len(fallback) == 1 and fallback[0].reason == "fatal"
    assert metrics._AGGREGATOR.weekly_snapshot()["success_rate"]["news"]["success"] == 1
    await orchestrator.close()
