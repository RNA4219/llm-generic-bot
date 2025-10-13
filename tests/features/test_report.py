"""Sprint 3: 週次サマリ機能の期待仕様."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from llm_generic_bot.features.report import (
    ReportPayload,
    WeeklyReportTemplate,
    generate_weekly_summary,
)
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot


def _tags(**items: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(items.items()))


TEMPLATES = {
    "ja": WeeklyReportTemplate(
        title="📊 運用サマリ {week_range}",
        line="・{label}: {value}",
        footer="Powered by Ops",
    )
}


def test_weekly_report_uses_template_schema_directly() -> None:
    snapshot = WeeklyMetricsSnapshot(
        start=datetime(2024, 4, 1, tzinfo=timezone.utc),
        end=datetime(2024, 4, 7, tzinfo=timezone.utc),
        counters={
            "send.success": {
                _tags(job="weather", platform="slack", channel="#alerts"): CounterSnapshot(count=72),
                _tags(job="alert", platform="slack", channel="#ops"): CounterSnapshot(count=42),
            },
            "send.failure": {
                _tags(job="alert", platform="slack", channel="#alerts", error="timeout"): CounterSnapshot(count=3),
                _tags(job="alert", platform="slack", channel="#alerts", error="quota"): CounterSnapshot(count=1),
            },
        },
        observations={},
    )

    template_cfg = {
        "title": "📊 運用サマリ {week_range}",
        "line": "・{metric}: {value}",
        "footer": "Powered by Ops",
    }

    payload = generate_weekly_summary(
        snapshot,
        locale="ja",
        fallback="fallback",
        failure_threshold=0.3,
        templates={"ja": template_cfg},
    )

    expected = (
        "📊 運用サマリ 2024-04-01〜2024-04-07\n"
        "・総ジョブ: 118件 (成功 114件 / 失敗 4件, 成功率 96.6%)\n"
        "・活発チャンネル: #alerts (76), #ops (42)\n"
        "・主要エラー: timeout (3), quota (1)\n"
        "Powered by Ops"
    )

    assert payload.body == expected
    assert payload.channel == "#alerts"
    assert payload.tags["severity"] == "normal"
    assert payload.tags["failure_rate"] == "3.4%"
    assert payload.tags["period"] == "2024-04-01/2024-04-07"


def test_weekly_report_formats_real_snapshot() -> None:
    snapshot = WeeklyMetricsSnapshot(
        start=datetime(2024, 4, 1, tzinfo=timezone.utc),
        end=datetime(2024, 4, 7, tzinfo=timezone.utc),
        counters={
            "send.success": {
                _tags(job="weather", platform="slack", channel="#alerts"): CounterSnapshot(count=72),
                _tags(job="alert", platform="slack", channel="#ops"): CounterSnapshot(count=42),
            },
            "send.failure": {
                _tags(job="alert", platform="slack", channel="#alerts", error="timeout"): CounterSnapshot(count=3),
                _tags(job="alert", platform="slack", channel="#alerts", error="quota"): CounterSnapshot(count=1),
            },
        },
        observations={},
    )

    payload = generate_weekly_summary(
        snapshot,
        locale="ja",
        fallback="fallback",
        failure_threshold=0.3,
        templates=TEMPLATES,
    )

    expected = (
        "📊 運用サマリ 2024-04-01〜2024-04-07\n"
        "・総ジョブ: 118件 (成功 114件 / 失敗 4件, 成功率 96.6%)\n"
        "・活発チャンネル: #alerts (76), #ops (42)\n"
        "・主要エラー: timeout (3), quota (1)\n"
        "Powered by Ops"
    )

    assert isinstance(payload, ReportPayload)
    assert payload.channel == "#alerts"
    assert payload.body == expected
    assert payload.tags["severity"] == "normal"
    assert payload.tags["locale"] == "ja"
    assert payload.tags["period"] == "2024-04-01/2024-04-07"
    assert payload.tags["failure_rate"] == "3.4%"


@pytest.mark.parametrize("failure_threshold", [0.1, 0.5])
def test_weekly_report_handles_threshold_and_fallback(failure_threshold: float) -> None:
    snapshot = WeeklyMetricsSnapshot(
        start=datetime(2024, 4, 8, tzinfo=timezone.utc),
        end=datetime(2024, 4, 14, tzinfo=timezone.utc),
        counters={
            "send.failure": {
                _tags(job="weather", platform="slack", channel="#ops", error="timeout"): CounterSnapshot(count=5),
            }
        },
        observations={},
    )

    payload = generate_weekly_summary(
        snapshot,
        locale="ja",
        fallback="fallback body",
        failure_threshold=failure_threshold,
        templates=TEMPLATES,
    )

    assert payload.body == "fallback body"
    assert payload.channel == "#ops"
    assert payload.tags["severity"] in {"degraded", "high"}
    assert payload.tags["locale"] == "ja"


def test_weekly_report_prefers_configured_template_locale() -> None:
    templates = {
        "en": WeeklyReportTemplate(
            title="Weekly summary {week_range}",
            line="* {label}: {value}",
            footer=None,
        ),
        "ja": WeeklyReportTemplate(
            title="📈 サマリ {week_range}",
            line="・{label}: {value}",
            footer=None,
        ),
    }
    snapshot = WeeklyMetricsSnapshot(
        start=datetime(2024, 4, 15, tzinfo=timezone.utc),
        end=datetime(2024, 4, 21, tzinfo=timezone.utc),
        counters={
            "send.success": {
                _tags(job="weather", platform="slack", channel="#alerts"): CounterSnapshot(count=50),
            },
            "send.failure": {
                _tags(job="weather", platform="slack", channel="#ops", error="timeout"): CounterSnapshot(count=5),
            },
        },
        observations={},
    )

    payload = generate_weekly_summary(
        snapshot,
        locale="en",
        fallback="fallback",
        failure_threshold=0.2,
        templates=templates,
    )

    assert payload.channel == "#alerts"
    assert payload.tags["top_channel"] == "#alerts"
    assert payload.tags["locale"] == "en"
    assert payload.body.splitlines()[0] == "Weekly summary 2024-04-15〜2024-04-21"
