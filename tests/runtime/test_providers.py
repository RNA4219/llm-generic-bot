from __future__ import annotations

import pytest

from llm_generic_bot.runtime import providers
from llm_generic_bot.runtime.setup import setup_runtime
from llm_generic_bot.features.news import NewsFeedItem


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_sample_providers_return_expected_values() -> None:
    items = list(await providers.SAMPLE_NEWS_FEED.fetch("https://example.com/feed", limit=3))
    assert items == [
        NewsFeedItem(
            title="サンプルニュース",
            link="https://example.com/news",
            summary="サンプルサマリー",
        )
    ]

    summary = await providers.SAMPLE_NEWS_SUMMARY.summarize(items[0], language="ja")
    assert summary == "これはサンプルのニュース要約です"

    logs = list(await providers.SAMPLE_DM_LOG.collect("general", limit=5))
    assert [entry.message for entry in logs] == ["sample dm log entry"]

    digest_summary = await providers.SAMPLE_DM_SUMMARY.summarize("dummy", max_events=5)
    assert digest_summary == "これはサンプルのDM要約です"

    providers.SAMPLE_DM_SENDER.deliveries.clear()
    result = await providers.SAMPLE_DM_SENDER.send(
        "hello", "dm-channel", job="dm_digest", recipient_id="recipient"
    )
    assert result is None
    assert providers.SAMPLE_DM_SENDER.deliveries[-1] == {
        "text": "hello",
        "channel": "dm-channel",
        "job": "dm_digest",
        "recipient_id": "recipient",
    }


@pytest.mark.anyio("asyncio")
async def test_setup_runtime_accepts_sample_providers() -> None:
    class _StubSender:
        async def send(self, text: str, channel: str | None = None, *, job: str | None = None) -> None:
            return None

    stub_sender = _StubSender()

    providers.SAMPLE_DM_SENDER.deliveries.clear()

    news_settings = {
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "news": {
            "enabled": True,
            "feed_provider": providers.SAMPLE_NEWS_FEED,
            "summary_provider": providers.SAMPLE_NEWS_SUMMARY,
            "feed_url": "https://example.com/feed",
        },
    }

    _news_scheduler, news_orchestrator, news_jobs = setup_runtime(news_settings, sender=stub_sender)

    try:
        news_body = await news_jobs["news"]()
        assert "サンプルニュース" in news_body
        assert "これはサンプルのニュース要約です" in news_body
    finally:
        await news_orchestrator.close()

    providers.SAMPLE_DM_SENDER.deliveries.clear()

    dm_settings = {
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "dm_digest": {
            "enabled": True,
            "log_provider": providers.SAMPLE_DM_LOG,
            "summary_provider": providers.SAMPLE_DM_SUMMARY,
            "sender": providers.SAMPLE_DM_SENDER,
            "source_channel": "general",
            "recipient_id": "recipient",
        },
    }

    _dm_scheduler, dm_orchestrator, dm_jobs = setup_runtime(dm_settings, sender=stub_sender)

    try:
        dm_result = await dm_jobs["dm_digest"]()
        assert dm_result is None
        assert providers.SAMPLE_DM_SENDER.deliveries
        assert providers.SAMPLE_DM_SENDER.deliveries[-1]["job"] == "dm_digest"
    finally:
        await dm_orchestrator.close()
