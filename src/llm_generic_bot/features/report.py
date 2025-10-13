"""週次メトリクスの通知本文を生成するユーティリティ."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Final, Mapping, TypedDict

from llm_generic_bot.infra.metrics import WeeklyMetricsSnapshot


@dataclass(frozen=True)
class WeeklySummary:
    """週次サマリ通知の内容を表現する値オブジェクト."""

    body: str
    channel: str
    tags: Mapping[str, str]


class ReportTemplate(TypedDict):
    title: str
    line: str
    line_missing: str
    line_threshold: str
    footer: str


TEMPLATE: Final[ReportTemplate] = {
    "title": "📊 運用サマリ ({week_range})",
    "line": "・{label}: {value}",
    "line_missing": "・{label}: データ欠損",
    "line_threshold": "・{label}: {value} ⚠️{note}",
    "footer": "詳細は運用ダッシュボードを参照",
}


@dataclass(frozen=True)
class MetricRule:
    label: str
    extractor: Callable[[WeeklyMetricsSnapshot], float | None]
    formatter: Callable[[float], str]
    threshold: float | None = None
    note: str | None = None


def generate_weekly_summary(snapshot: WeeklyMetricsSnapshot) -> WeeklySummary:
    """週次メトリクススナップショットから通知本文を構築する."""

    rules: Final[tuple[MetricRule, ...]] = (
        MetricRule(
            label="インシデント",
            extractor=lambda snap: _counter_value(snap, "ops.incidents"),
            formatter=_format_count,
            threshold=3.0,
            note="インシデント多発",
        ),
        MetricRule(
            label="エスカレーション",
            extractor=lambda snap: _counter_value(snap, "ops.escalations"),
            formatter=_format_count,
            threshold=1.0,
            note="要振り返り",
        ),
        MetricRule(
            label="平均初動時間",
            extractor=lambda snap: _observation_average(snap, "ops.ack_seconds"),
            formatter=_format_seconds,
            threshold=90.0,
            note="SLA超過",
        ),
    )

    week_range = _format_range(snapshot.start, snapshot.end)
    lines = []
    threshold_triggered = False
    for rule in rules:
        value = rule.extractor(snapshot)
        if value is None:
            lines.append(TEMPLATE["line_missing"].format(label=rule.label))
            continue
        formatted = rule.formatter(value)
        if rule.threshold is not None and rule.note is not None and value >= rule.threshold:
            lines.append(
                TEMPLATE["line_threshold"].format(
                    label=rule.label,
                    value=formatted,
                    note=rule.note,
                )
            )
            threshold_triggered = True
        else:
            lines.append(TEMPLATE["line"].format(label=rule.label, value=formatted))

    severity = "warning" if threshold_triggered else "info"
    body = "\n".join(
        [
            TEMPLATE["title"].format(week_range=week_range),
            *lines,
            TEMPLATE["footer"],
        ]
    )
    return WeeklySummary(body=body, channel="ops-weekly", tags={"job": "weekly_report", "severity": severity})


def _format_range(start: datetime, end: datetime) -> str:
    return f"{start.date():%Y-%m-%d}〜{end.date():%Y-%m-%d}"


def _counter_value(snapshot: WeeklyMetricsSnapshot, name: str) -> float | None:
    metric = snapshot.counters.get(name)
    if not metric:
        return None
    return float(sum(counter.count for counter in metric.values()))


def _observation_average(snapshot: WeeklyMetricsSnapshot, name: str) -> float | None:
    metric = snapshot.observations.get(name)
    if not metric:
        return None
    total = sum(obs.total for obs in metric.values())
    count = sum(obs.count for obs in metric.values())
    if count <= 0:
        return None
    return total / count


def _format_count(value: float) -> str:
    return f"{int(value)}件"


def _format_seconds(value: float) -> str:
    return f"{value:.1f}秒"
