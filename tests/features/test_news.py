from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable, Iterator

import pytest

from llm_generic_bot.features.news import NewsFeedItem, SummaryError, build_news_post

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True)
class Case:
    name: str
    cfg: dict[str, Any]
    items: list[NewsFeedItem]
    outputs: list[str | Exception]
    expected: str
    suppress: bool
    summary_calls: list[str]
    retry_log: bool


CASES = (
    Case("feed_success", {"feed_url": "https://example.com/rss", "max_items": 2, "template": {"header": "最新ニュース", "item": "・{title}: {summary} ({link})"}}, [NewsFeedItem("記事A", "https://example.com/a", "long a"), NewsFeedItem("記事B", "https://example.com/b", "long b")], ["要約A", "要約B"], "最新ニュース\n・記事A: 要約A (https://example.com/a)\n・記事B: 要約B (https://example.com/b)", False, ["記事A", "記事B"], False),
    Case("summary_retry", {"feed_url": "https://example.com/rss", "max_items": 1, "template": {"header": "ニュース", "item": "- {title}: {summary}"}}, [NewsFeedItem("記事C", "https://example.com/c", "long c")], [SummaryError("temporary", retryable=True), "短い要約"], "ニュース\n- 記事C: 短い要約", False, ["記事C", "記事C"], True),
    Case("suppress_cooldown", {"feed_url": "https://example.com/rss", "max_items": 1, "template": {"header": "速報", "item": "{title} - {summary}"}, "suppress_cooldown": True}, [NewsFeedItem("記事D", "https://example.com/d", "long d")], ["要約D"], "速報\n記事D - 要約D", True, ["記事D"], False),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_build_news_post_table_driven(case: Case, caplog: pytest.LogCaptureFixture) -> None:
    feed_calls: list[tuple[str, int | None]] = []

    async def fetch(url: str, *, limit: int | None = None) -> Iterable[NewsFeedItem]:
        feed_calls.append((url, limit))
        return list(case.items[: limit or len(case.items)])

    outputs: Iterator[str | Exception] = iter(case.outputs)
    summary_calls: list[str] = []

    async def summarize(item: NewsFeedItem, *, language: str = "ja") -> str:
        summary_calls.append(item.title)
        try:
            result = next(outputs)
        except StopIteration as exc:  # pragma: no cover
            raise AssertionError("unexpected summarize call") from exc
        if isinstance(result, Exception):
            raise result
        return result

    permit_calls: list[dict[str, Any]] = []

    caplog.set_level(logging.INFO)
    logger = logging.getLogger(f"test.news.{case.name}")
    result = await build_news_post(
        case.cfg,
        feed_provider=SimpleNamespace(fetch=fetch),
        summary_provider=SimpleNamespace(summarize=summarize),
        permit=lambda *, job, suppress_cooldown: permit_calls.append({"job": job, "suppress_cooldown": suppress_cooldown}),
        logger=logger,
    )

    assert result == case.expected
    assert feed_calls == [(case.cfg["feed_url"], case.cfg.get("max_items"))]
    assert summary_calls == case.summary_calls
    assert permit_calls == [{"job": case.cfg.get("job", "news"), "suppress_cooldown": case.suppress}]
    assert any(record.message == "news_summary_retry" for record in caplog.records) is case.retry_log
