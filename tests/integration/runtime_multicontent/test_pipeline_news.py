from __future__ import annotations

import datetime as dt
import zoneinfo
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from llm_generic_bot import main as main_module

from ._helpers import (
    create_queue,
    freeze_scheduler,
    record_orchestrator_enqueue,
    record_queue_push,
)


pytestmark = pytest.mark.anyio("asyncio")


async def test_news_job_registers_and_enqueues_when_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = create_queue()

    async def dummy_fetch(_url: str, *, limit: int | None = None) -> list[str]:  # noqa: ARG001
        return []

    async def dummy_summarize(*_: Any, **__: Any) -> str:
        return "summary"

    news_calls: List[Dict[str, Any]] = []

    async def fake_news(cfg: Dict[str, Any], **kwargs: Any) -> str:
        news_calls.append({"cfg": cfg, **kwargs})
        return "news-post"

    monkeypatch.setattr(main_module, "build_news_post", fake_news)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "news": {
            "schedule": "06:00",
            "feed_provider": SimpleNamespace(fetch=dummy_fetch),
            "summary_provider": SimpleNamespace(summarize=dummy_summarize),
            "channel": "news-channel",
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    freeze_scheduler(monkeypatch, scheduler)

    enqueue_calls = record_orchestrator_enqueue(monkeypatch, orchestrator)
    pushed_jobs = record_queue_push(monkeypatch, scheduler)

    tz = zoneinfo.ZoneInfo("UTC")
    now = dt.datetime(2024, 1, 1, 6, 0, tzinfo=tz)
    await scheduler._run_due_jobs(now)
    await scheduler.dispatch_ready_batches(now.timestamp())

    try:
        assert "news" in jobs
        assert news_calls
        assert [call.job for call in pushed_jobs] == ["news"]
        assert enqueue_calls and enqueue_calls[-1].job == "news"
        assert enqueue_calls[-1].channel == "news-channel"
    finally:
        await orchestrator.close()
