from __future__ import annotations

import datetime as dt
import sys
import zoneinfo
from types import ModuleType, SimpleNamespace

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features.dm_digest import DigestLogEntry
from llm_generic_bot.features.news import NewsFeedItem


pytestmark = pytest.mark.anyio("asyncio")


async def test_setup_runtime_resolves_string_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    module_name = "tests.integration.fake_providers"
    provider_module = ModuleType(module_name)

    fetch_calls: list[dict[str, object]] = []

    async def fetch(url: str, *, limit: int | None = None) -> list[NewsFeedItem]:
        fetch_calls.append({"url": url, "limit": limit})
        return [NewsFeedItem(title="t", link="https://example.com", summary=None)]

    summary_calls: list[dict[str, object]] = []

    async def summarize(item: NewsFeedItem, *, language: str = "ja") -> str:
        summary_calls.append({"title": item.title, "language": language})
        return "summary"

    log_calls: list[dict[str, object]] = []

    async def collect(channel: str, *, limit: int) -> list[DigestLogEntry]:
        log_calls.append({"channel": channel, "limit": limit})
        return [
            DigestLogEntry(
                timestamp=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
                level="INFO",
                message="log",
            )
        ]

    digest_summary_calls: list[dict[str, object]] = []

    async def digest_summarize(
        text: str,
        *,
        max_events: int | None = None,
        **_: object,
    ) -> str:
        digest_summary_calls.append({"text": text, "max_events": max_events})
        return "digest"

    sender_calls: list[dict[str, object]] = []

    async def digest_send(
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
        recipient_id: str | None = None,
    ) -> None:
        sender_calls.append(
            {
                "text": text,
                "channel": channel,
                "job": job,
                "recipient_id": recipient_id,
                "correlation_id": correlation_id,
            }
        )

    provider_module.news_feed = SimpleNamespace(fetch=fetch)  # type: ignore[attr-defined]
    provider_module.news_summary = SimpleNamespace(summarize=summarize)  # type: ignore[attr-defined]
    provider_module.dm_logs = SimpleNamespace(collect=collect)  # type: ignore[attr-defined]
    provider_module.dm_summary = SimpleNamespace(summarize=digest_summarize)  # type: ignore[attr-defined]
    provider_module.dm_sender = SimpleNamespace(send=digest_send)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, provider_module)

    settings: dict[str, object] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"enabled": False},
        "omikuji": {"enabled": False},
        "news": {
            "schedule": "06:00",
            "feed_provider": f"{module_name}:news_feed",
            "summary_provider": f"{module_name}:news_summary",
            "feed_url": "https://example.com/rss",
        },
        "dm_digest": {
            "schedule": "08:00",
            "source_channel": "dm-source",
            "recipient_id": "recipient-1",
            "log_provider": f"{module_name}:dm_logs",
            "summary_provider": f"{module_name}:dm_summary",
            "sender": f"{module_name}:dm_sender",
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    async def no_sleep(_delay: float) -> None:
        return None

    scheduler._sleep = no_sleep  # type: ignore[assignment]

    enqueue_calls: list[dict[str, object]] = []

    async def fake_enqueue(
        text: str,
        *,
        job: str,
        platform: str,
        channel: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        enqueue_calls.append(
            {
                "text": text,
                "job": job,
                "platform": platform,
                "channel": channel,
                "correlation_id": correlation_id,
            }
        )
        return "corr"

    monkeypatch.setattr(orchestrator, "enqueue", fake_enqueue)

    tz = zoneinfo.ZoneInfo("UTC")

    await scheduler._run_due_jobs(dt.datetime(2024, 1, 1, 6, 0, tzinfo=tz))
    await scheduler.dispatch_ready_batches(dt.datetime(2024, 1, 1, 6, 0, tzinfo=tz).timestamp())

    await scheduler._run_due_jobs(dt.datetime(2024, 1, 1, 8, 0, tzinfo=tz))

    assert "news" in jobs and "dm_digest" in jobs
    assert fetch_calls and summary_calls
    assert log_calls and digest_summary_calls and sender_calls
    assert enqueue_calls and enqueue_calls[-1]["job"] == "news"
    assert sender_calls[-1]["recipient_id"] == "recipient-1"

    await orchestrator.close()
