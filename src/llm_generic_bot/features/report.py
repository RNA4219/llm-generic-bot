from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from ..infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot


@dataclass(frozen=True)
class ReportPayload:
    """週次サマリ通知の本文とメタデータを保持する."""

    body: str
    channel: str
    tags: Mapping[str, str]


@dataclass(frozen=True)
class WeeklyReportTemplate:
    """各ロケールのメッセージテンプレート."""

    header: str
    summary: str
    channels: str
    failures: str


def generate_weekly_summary(
    snapshot: WeeklyMetricsSnapshot,
    *,
    locale: str,
    fallback: str,
    failure_threshold: float,
    templates: Mapping[str, WeeklyReportTemplate],
) -> ReportPayload:
    """週次メトリクスをテンプレートへ整形し通知ペイロードを生成する.

    Args:
        snapshot: 7日間のメトリクススナップショット。
        locale: 使用するテンプレートのロケール識別子。
        fallback: 集計不能時に返す本文。
        failure_threshold: 失敗率しきい値 (0.0-1.0)。
        templates: ロケールごとの本文テンプレート集合。
    """

    tags: dict[str, str] = {"locale": locale}
    start = _format_date(snapshot.start)
    end = _format_date(snapshot.end)
    if start and end:
        tags["period"] = f"{start}/{end}"
    succeeded, failed = _totals(snapshot)
    processed = succeeded + failed
    channel_counts = _aggregate_channel_counts(snapshot)
    failure_tags = _aggregate_failure_tags(snapshot)
    top_channel = _top_ranked_item(channel_counts)
    channel = top_channel[0] if top_channel else "-"
    if top_channel:
        tags["top_channel"] = top_channel[0]
    if processed <= 0:
        tags["severity"] = "degraded"
        return ReportPayload(fallback, channel, tags)
    failure_rate = failed / processed if processed else 0.0
    if failure_rate >= failure_threshold:
        tags["severity"] = "high"
        tags["failure_rate"] = f"{failure_rate * 100.0:.1f}%"
        return ReportPayload(fallback, channel, tags)
    template = templates.get(locale)
    if template is None:
        tags["severity"] = "degraded"
        return ReportPayload(fallback, channel, tags)
    header = template.header.format(start=start or "-", end=end or "-")
    summary = template.summary.format(
        total=processed,
        success=succeeded,
        failure=failed,
        success_rate=(succeeded / processed * 100.0) if processed else 0.0,
    )
    lines = [header, summary]
    channels_line = _format_top_items(channel_counts)
    if channels_line:
        lines.append(template.channels.format(channels=channels_line))
    failure_line = _format_top_items(failure_tags)
    if failure_line:
        lines.append(template.failures.format(failures=failure_line))
    tags["severity"] = "normal"
    tags["failure_rate"] = f"{failure_rate * 100.0:.1f}%"
    return ReportPayload("\n".join(lines), channel, tags)


def _format_date(value: datetime) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None


def _totals(snapshot: WeeklyMetricsSnapshot) -> tuple[int, int]:
    success_total = _sum_counters(snapshot.counters.get("send.success", {}))
    failure_total = _sum_counters(snapshot.counters.get("send.failure", {}))
    return success_total, failure_total


def _sum_counters(counters: Mapping[tuple[tuple[str, str], ...], CounterSnapshot]) -> int:
    return sum(snapshot.count for snapshot in counters.values())


def _aggregate_channel_counts(
    snapshot: WeeklyMetricsSnapshot,
) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for metric in ("send.success", "send.failure"):
        for tags_key, counter in snapshot.counters.get(metric, {}).items():
            channel = _lookup_tag(tags_key, "channel")
            if channel:
                counts[channel] = counts.get(channel, 0) + counter.count
    return counts


def _aggregate_failure_tags(snapshot: WeeklyMetricsSnapshot) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for tags_key, counter in snapshot.counters.get("send.failure", {}).items():
        label = _lookup_tag(tags_key, "error") or "unknown"
        counts[label] = counts.get(label, 0) + counter.count
    return counts


def _format_top_items(items: Mapping[str, Any], limit: int = 3) -> str:
    ordered = _top_ranked_items(items, limit)
    return ", ".join(f"{name} ({count})" for name, count in ordered)


def _top_ranked_items(items: Mapping[str, Any], limit: int) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for name, raw in items.items():
        if not isinstance(name, str):
            continue
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            count = int(raw)
        else:
            continue
        if count <= 0:
            continue
        pairs.append((name, count))
    return sorted(pairs, key=lambda item: (-item[1], item[0]))[:limit]


def _top_ranked_item(items: Mapping[str, Any]) -> tuple[str, int] | None:
    ordered = _top_ranked_items(items, 1)
    return ordered[0] if ordered else None


def _lookup_tag(tags: Iterable[tuple[str, str]], key: str) -> str | None:
    for name, value in tags:
        if name == key and value:
            return value
    return None


__all__ = ["ReportPayload", "WeeklyReportTemplate", "generate_weekly_summary"]
