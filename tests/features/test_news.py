from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable

import pytest

from llm_generic_bot.features.news import NewsFeedItem, SummaryError, build_news_post

pytestmark = pytest.mark.anyio("asyncio")


@dataclass
class SummaryStub:
    outputs: deque[str | Exception]
    calls: list[dict[str, Any]]

    @classmethod
    def from_iterable(cls, values: Iterable[str | Exception]) -> "SummaryStub":
        return cls(outputs=deque(values), calls=[])

    async def summarize(self, item: NewsFeedItem, *, language: str = "ja") -> str:
        self.calls.append({"title": item.title, "language": language})
        if not self.outputs:
            raise AssertionError("unexpected summarize call")
        result = self.outputs.popleft()
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_build_news_post_success(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    items = [
        NewsFeedItem(title="記事A", link="https://example.com/a", summary="A要約"),
        NewsFeedItem(title="記事B", link="https://example.com/b", summary="B要約"),
    ]
    feed_calls: list[tuple[str, int | None]] = []

    async def fetch(url: str, *, limit: int | None = None) -> Iterable[NewsFeedItem]:
        feed_calls.append((url, limit))
        return items[: limit or len(items)]

    summary = SummaryStub.from_iterable(["短いA", "短いB"])
    permit_calls: list[dict[str, Any]] = []
    cooldown_calls: list[dict[str, Any]] = []

    async def cooldown(**kwargs: Any) -> bool:
        cooldown_calls.append(kwargs)
        return False

    result = await build_news_post(
        {
            "feed_url": "https://example.com/rss",
            "job": "morning-news",
            "max_items": 2,
            "template": {"header": "ヘッドライン", "item": "・{title}: {summary}"},
        },
        feed_provider=SimpleNamespace(fetch=fetch),
        summary_provider=summary,
        permit=lambda *, job, suppress_cooldown: permit_calls.append(
            {"job": job, "suppress_cooldown": suppress_cooldown}
        ),
        cooldown=cooldown,
    )

    assert result == "ヘッドライン\n・記事A: 短いA\n・記事B: 短いB"
    assert feed_calls == [("https://example.com/rss", 2)]
    assert summary.calls == [
        {"title": "記事A", "language": "ja"},
        {"title": "記事B", "language": "ja"},
    ]
    assert permit_calls == [{"job": "morning-news", "suppress_cooldown": False}]
    assert cooldown_calls == [
        {"job": "morning-news", "platform": None, "channel": None}
    ]
    ready_logs = [
        record
        for record in caplog.records
        if record.message == "news_summary_ready"
    ]
    assert ready_logs
    assert all(getattr(record, "event", None) == "news_summary_ready" for record in ready_logs)


async def test_build_news_post_summary_retry_and_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    items = [
        NewsFeedItem(title="記事C", link="https://example.com/c", summary="既存要約"),
    ]

    async def fetch(url: str, *, limit: int | None = None) -> Iterable[NewsFeedItem]:
        return items

    summary = SummaryStub.from_iterable(
        [
            SummaryError("temporary", retryable=True),
            SummaryError("fatal", retryable=False),
        ]
    )
    permit_calls: list[dict[str, Any]] = []

    result = await build_news_post(
        {
            "feed_url": "https://example.com/rss",
            "job": "evening-news",
            "template": {"header": "ニュース", "item": "- {title}: {summary}"},
        },
        feed_provider=SimpleNamespace(fetch=fetch),
        summary_provider=summary,
        permit=lambda *, job, suppress_cooldown: permit_calls.append(
            {"job": job, "suppress_cooldown": suppress_cooldown}
        ),
    )

    assert result == "ニュース\n- 記事C: 既存要約"
    assert summary.calls == [
        {"title": "記事C", "language": "ja"},
        {"title": "記事C", "language": "ja"},
    ]
    assert permit_calls == [{"job": "evening-news", "suppress_cooldown": False}]
    fallback_logs = [
        record
        for record in caplog.records
        if record.message == "news_summary_fallback"
    ]
    assert fallback_logs
    assert all(
        getattr(record, "event", None) == "news_summary_fallback"
        for record in fallback_logs
    )
    retry_logs = [
        record for record in caplog.records if record.message == "news_summary_retry"
    ]
    assert len(retry_logs) == 1
    assert getattr(retry_logs[0], "event", None) == "news_summary_retry"


async def test_build_news_post_suppressed_by_cooldown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    items = [
        NewsFeedItem(title="記事D", link="https://example.com/d", summary="長文要約"),
    ]

    feed_calls: list[tuple[str, int | None]] = []

    async def fetch(url: str, *, limit: int | None = None) -> Iterable[NewsFeedItem]:
        feed_calls.append((url, limit))
        return items

    summary = SummaryStub.from_iterable(["unused"])
    permit_calls: list[dict[str, Any]] = []
    cooldown_calls: list[dict[str, Any]] = []

    async def cooldown(**kwargs: Any) -> bool:
        cooldown_calls.append(kwargs)
        return True

    result = await build_news_post(
        {
            "feed_url": "https://example.com/rss",
            "job": "breaking-news",
            "template": {"header": "速報", "item": "* {title}: {summary}"},
        },
        feed_provider=SimpleNamespace(fetch=fetch),
        summary_provider=summary,
        permit=lambda *, job, suppress_cooldown: permit_calls.append(
            {"job": job, "suppress_cooldown": suppress_cooldown}
        ),
        cooldown=cooldown,
    )

    assert result is None
    assert feed_calls == []
    assert summary.calls == []
    assert permit_calls == []
    assert cooldown_calls == [
        {"job": "breaking-news", "platform": None, "channel": None}
    ]
    skip_logs = [
        record
        for record in caplog.records
        if record.message == "news_summary_skip_cooldown"
    ]
    assert skip_logs
    assert all(
        getattr(record, "event", None) == "news_summary_skip_cooldown"
        for record in skip_logs
    )
