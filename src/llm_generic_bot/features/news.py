from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class NewsFeedItem:
    title: str
    link: str
    summary: str | None = None


class FeedProvider(Protocol):
    async def fetch(self, url: str, *, limit: int | None = None) -> Iterable[NewsFeedItem]:
        ...


class SummaryProvider(Protocol):
    async def summarize(self, item: NewsFeedItem, *, language: str = "ja") -> str:
        ...


class PermitHook(Protocol):
    def __call__(self, *, job: str, suppress_cooldown: bool) -> None:
        ...


class CooldownChecker(Protocol):
    async def __call__(
        self,
        *,
        job: str,
        platform: str | None,
        channel: str | None,
    ) -> bool:
        ...


class SummaryError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


async def build_news_post(
    cfg: Mapping[str, object],
    *,
    feed_provider: FeedProvider,
    summary_provider: SummaryProvider,
    permit: PermitHook | None = None,
    cooldown: CooldownChecker | None = None,
    logger: logging.Logger | None = None,
) -> str:
    logger = logger or logging.getLogger(__name__)
    job = str(cfg.get("job", "news"))
    feed_url_obj = cfg.get("feed_url")
    if not isinstance(feed_url_obj, str) or not feed_url_obj:
        raise ValueError("feed_url is required")
    feed_url = feed_url_obj
    limit_obj = cfg.get("max_items", 3)
    if isinstance(limit_obj, bool):
        limit = 1 if limit_obj else 0
    elif isinstance(limit_obj, (int, float)):
        limit = max(int(limit_obj), 0)
    else:
        limit = 3
    template_cfg = cfg.get("template", {})
    if isinstance(template_cfg, Mapping):
        header = str(template_cfg.get("header", "ニュースまとめ"))
        item_fmt = str(template_cfg.get("item", "・{title}: {summary} ({link})"))
        footer_raw = template_cfg.get("footer")
        footer = str(footer_raw) if isinstance(footer_raw, str) else None
    else:
        header, item_fmt, footer = "ニュースまとめ", "・{title}: {summary} ({link})", None
    suppress_cooldown = bool(cfg.get("suppress_cooldown", False))
    language_obj = cfg.get("language", "ja")
    language = str(language_obj) if isinstance(language_obj, str) else "ja"
    platform_obj = cfg.get("platform")
    platform = str(platform_obj) if isinstance(platform_obj, str) else None
    channel_obj = cfg.get("channel")
    channel = str(channel_obj) if isinstance(channel_obj, str) else None

    if cooldown is not None:
        cooldown_active = bool(
            await cooldown(job=job, platform=platform, channel=channel)
        )
        if cooldown_active:
            suppress_cooldown = True

    raw_items = await feed_provider.fetch(feed_url, limit=limit)
    items: Sequence[NewsFeedItem] = list(raw_items)[:limit]
    summaries: list[str] = []

    summary_retry_obj = cfg.get("summary_retry", 2)
    if isinstance(summary_retry_obj, (int, float)):
        max_attempts = max(int(summary_retry_obj), 1)
    else:
        max_attempts = 2

    def _fallback(item: NewsFeedItem) -> str:
        if item.summary:
            return item.summary
        return item.title

    for item in items:
        if suppress_cooldown:
            summaries.append(_fallback(item))
            continue

        attempt = 0
        while True:
            attempt += 1
            try:
                summary_text = await summary_provider.summarize(item, language=language)
                summaries.append(summary_text)
                break
            except SummaryError as exc:
                should_retry = exc.retryable and attempt < max_attempts
                if should_retry:
                    logger.warning(
                        "news_summary_retry",
                        extra={"title": item.title, "attempt": attempt},
                    )
                    continue
                fallback = _fallback(item)
                logger.warning(
                    "news_summary_fallback",
                    extra={"title": item.title, "reason": str(exc)},
                )
                summaries.append(fallback)
                break
    lines = [header]
    for item, summary_text in zip(items, summaries, strict=False):
        lines.append(
            item_fmt.format(
                title=item.title,
                summary=summary_text,
                link=item.link,
            )
        )
    if footer:
        lines.append(footer)

    (permit or (lambda *, job, suppress_cooldown: None))(
        job=job, suppress_cooldown=suppress_cooldown
    )
    if suppress_cooldown:
        logger.info(
            "news_summary_skip_cooldown",
            extra={
                "items": len(items),
                "job": job,
                "platform": platform,
                "channel": channel,
            },
        )
    else:
        logger.info(
            "news_summary_ready",
            extra={
                "items": len(items),
                "suppress_cooldown": suppress_cooldown,
                "job": job,
                "platform": platform,
                "channel": channel,
            },
        )
    return "\n".join(lines)
