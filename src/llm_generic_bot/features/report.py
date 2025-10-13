from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Protocol

try:  # pragma: no cover - optional依存
    from llm_generic_bot.infra.metrics import WeeklyMetricsSnapshot  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - until infra.metrics 実装
    class _WeeklyMetricsSnapshot(Protocol):
        period_start: Any
        period_end: Any
        totals: Mapping[str, Any]
        breakdowns: Mapping[str, Any]
        metadata: Mapping[str, Any]

    WeeklyMetricsSnapshot = _WeeklyMetricsSnapshot


@dataclass(frozen=True)
class ReportPayload:
    """週次サマリ通知の本文とメタデータを保持する."""

    body: str
    channel: str
    tags: Mapping[str, str]


_TEMPLATES: Mapping[str, Mapping[str, str]] = {
    "ja": {
        "header": "📊 運用サマリ {start}〜{end}",
        "summary": "総ジョブ: {total}件 / 成功: {success}件 / 失敗: {failure}件 (成功率 {success_rate:.1f}%)",
        "channels": "活発チャンネル: {channels}",
        "failures": "主要エラー: {failures}",
    }
}


def generate_weekly_summary(
    metrics: WeeklyMetricsSnapshot,
    *,
    locale: str,
    fallback: str,
) -> ReportPayload:
    """週次メトリクスをテンプレートへ整形し通知ペイロードを生成する."""

    totals = _as_mapping(getattr(metrics, "totals", {}))
    processed, succeeded, failed = (
        _as_int(totals.get(name)) for name in ("jobs_processed", "jobs_succeeded", "jobs_failed")
    )
    metadata = _as_mapping(getattr(metrics, "metadata", {}))
    channel = _resolve_channel(metadata)
    tags: dict[str, str] = {"locale": locale}
    start = _format_date(getattr(metrics, "period_start", None))
    end = _format_date(getattr(metrics, "period_end", None))
    if start and end:
        tags["period"] = f"{start}/{end}"
    if processed is None or succeeded is None or failed is None or processed <= 0:
        tags["severity"] = "degraded"
        return ReportPayload(fallback, channel, tags)
    failure_rate = failed / processed
    threshold = _as_float(metadata.get("failure_rate_alert")) or 0.3
    if failure_rate >= threshold:
        tags["severity"] = "high"
        tags["failure_rate"] = f"{failure_rate * 100.0:.1f}%"
        return ReportPayload(fallback, channel, tags)
    template = _TEMPLATES.get(locale) or _TEMPLATES.get("ja")
    if not template:
        tags["severity"] = "degraded"
        return ReportPayload(fallback, channel, tags)
    header = template["header"].format(start=start or "-", end=end or "-")
    summary = template["summary"].format(
        total=processed,
        success=succeeded,
        failure=failed,
        success_rate=(succeeded / processed * 100.0) if processed else 0.0,
    )
    lines = [header, summary]
    breakdowns = _as_mapping(getattr(metrics, "breakdowns", {}))
    channels_line = _format_top_items(_as_mapping(breakdowns.get("channels", {})))
    if channels_line:
        lines.append(template["channels"].format(channels=channels_line))
        tags["top_channel"] = channels_line.split(",", 1)[0].split()[0]
    failure_line = _format_top_items(_as_mapping(breakdowns.get("failure_tags", {})))
    if failure_line:
        lines.append(template["failures"].format(failures=failure_line))
    tags["severity"] = "normal"
    tags["failure_rate"] = f"{failure_rate * 100.0:.1f}%"
    return ReportPayload("\n".join(lines), channel, tags)


def _as_mapping(value: object) -> Mapping[str, Any]: return value if isinstance(value, Mapping) else {}


def _as_int(value: object) -> int | None: return int(value) if isinstance(value, (int, float, bool)) else None


def _as_float(value: object) -> float | None: return float(value) if isinstance(value, (int, float, bool)) else None


def _format_date(value: object) -> str | None: return value.isoformat() if isinstance(value, date) else None


def _resolve_channel(metadata: Mapping[str, Any]) -> str:
    channel = metadata.get("preferred_channel")
    return channel if isinstance(channel, str) and channel else "-"


def _format_top_items(items: Mapping[str, Any], limit: int = 3) -> str:
    pairs: Iterable[tuple[str, int]] = ((k, _as_int(v) or 0) for k, v in items.items() if isinstance(k, str))
    ordered = sorted(pairs, key=lambda item: (-item[1], item[0]))[:limit]
    return ", ".join(f"{name} ({count})" for name, count in ordered if count > 0)


__all__ = ["ReportPayload", "generate_weekly_summary"]
