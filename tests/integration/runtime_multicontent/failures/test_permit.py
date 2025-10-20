from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.orchestrator import PermitDecision
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features.news import NewsFeedItem
from llm_generic_bot.infra.metrics import aggregator_state

if TYPE_CHECKING:
    from tests.integration import test_runtime_multicontent_failures as legacy_module


pytestmark = pytest.mark.anyio("asyncio")


async def test_permit_denied_records_metrics(caplog: pytest.LogCaptureFixture) -> None:
    from tests.integration import test_runtime_multicontent_failures as legacy_module

    aggregator_state.reset_for_test()
    settings = legacy_module._settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = legacy_module._providers([NewsFeedItem("t", "https://example.com")], _summarize)
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    caplog.set_level("INFO", logger="llm_generic_bot.core.orchestrator.runtime")
    caplog.set_level("INFO", logger="llm_generic_bot.core.orchestrator")
    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    def _deny(_platform: str, _channel: str | None, job: str) -> PermitDecision:
        return PermitDecision(allowed=False, reason="quota", retryable=False, job=f"{job}-denied")

    orchestrator._permit = _deny  # type: ignore[assignment]

    text = await jobs["news"]()
    assert text
    legacy_module._run_dispatch(scheduler, text, created_at=0.0)
    await scheduler.dispatch_ready_batches()
    await orchestrator.flush()

    denied = [record for record in caplog.records if record.message == "permit_denied"]
    assert denied and denied[0].job == "news-denied"
    assert aggregator_state.weekly_snapshot()["permit_denials"] == [
        {"job": "news-denied", "platform": "discord", "channel": "discord-news", "reason": "quota", "retryable": "false"}
    ]
    await orchestrator.close()
