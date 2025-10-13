from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..features.dm_digest import DigestLogEntry
from ..features.news import NewsFeedItem

_NEWS_ITEM = NewsFeedItem(
    title="サンプルニュース",
    link="https://example.com/news",
    summary="サンプルサマリー",
)
_DM_LOG_ENTRY = DigestLogEntry(
    timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
    level="INFO",
    message="sample dm log entry",
)


class _SampleNewsFeed:
    async def fetch(self, url: str, *, limit: int | None = None):
        return [_NEWS_ITEM]


class _SampleNewsSummary:
    async def summarize(self, item: NewsFeedItem, *, language: str = "ja") -> str:
        return "これはサンプルのニュース要約です"


class _SampleDMLog:
    async def collect(self, channel: str, *, limit: int):
        return [_DM_LOG_ENTRY]


class _SampleDMSummary:
    async def summarize(self, text: str, *, max_events: int | None = None) -> str:
        return "これはサンプルのDM要約です"


class _SampleDMSender:
    def __init__(self) -> None:
        self.deliveries: list[dict[str, Any]] = []

    async def send(
        self,
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
        recipient_id: str | None = None,
    ) -> None:
        self.deliveries.append(
            {
                "text": text,
                "channel": channel,
                "job": job,
                "recipient_id": recipient_id,
            }
        )


SAMPLE_NEWS_FEED = _SampleNewsFeed()
SAMPLE_NEWS_SUMMARY = _SampleNewsSummary()
SAMPLE_DM_LOG = _SampleDMLog()
SAMPLE_DM_SUMMARY = _SampleDMSummary()
SAMPLE_DM_SENDER = _SampleDMSender()

__all__ = [
    "SAMPLE_NEWS_FEED",
    "SAMPLE_NEWS_SUMMARY",
    "SAMPLE_DM_LOG",
    "SAMPLE_DM_SUMMARY",
    "SAMPLE_DM_SENDER",
]
