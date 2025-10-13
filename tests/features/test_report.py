"""Sprint 3: 週次サマリ機能の期待仕様."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from llm_generic_bot.features.report import (
    ReportPayload,
    WeeklyReportSettings,
    WeeklyReportTemplate,
    generate_weekly_summary,
)
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot


def _tags(**items: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(items.items()))


SETTINGS = WeeklyReportSettings(
    templates={
        "ja": WeeklyReportTemplate(
            title="📊 運用サマリ {week_range}",
            line="・{metric}: {value}",
            footer="詳細は運用ダッシュボードへ",
        )
    },
    fallback="fallback",
    failure_threshold=0.3,
)


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

    payload = generate_weekly_summary(snapshot, locale="ja", settings=SETTINGS)

    assert isinstance(payload, ReportPayload)
    assert payload.channel == "#alerts"
    assert payload.body.splitlines()[0] == "📊 運用サマリ 2024-04-01〜2024-04-07"
    assert "・jobs_processed: 118" in payload.body
    assert "timeout (3)" in payload.body and "quota (1)" in payload.body
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
        settings=replace(SETTINGS, failure_threshold=failure_threshold, fallback="fallback body"),
    )

    assert payload.body == "fallback body"
    assert payload.channel == "#ops"
    assert payload.tags["severity"] in {"degraded", "high"}
    assert payload.tags["locale"] == "ja"


def test_weekly_report_prefers_configured_template_locale() -> None:
    templates = {
        "en": WeeklyReportTemplate(
            title="Weekly summary {week_range}",
            line="- {metric}: {value}",
            footer="Thanks",
        ),
        "ja": SETTINGS.templates["ja"],
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
        settings=WeeklyReportSettings(
            templates=templates,
            fallback="fallback",
            failure_threshold=0.2,
        ),
    )

    assert payload.channel == "#alerts"
    assert payload.tags["top_channel"] == "#alerts"
    assert payload.tags["locale"] == "en"
    assert payload.body.startswith("Weekly summary 2024-04-15〜2024-04-21")


def test_weekly_report_handles_unconvertible_snapshot() -> None:
    snapshot = WeeklyMetricsSnapshot(
        start=datetime(2024, 4, 22, tzinfo=timezone.utc),
        end=datetime(2024, 4, 28, tzinfo=timezone.utc),
        counters={
            "send.success": {
                "invalid": CounterSnapshot(count=5),
            }
        },
        observations={
            "latency": {
                ("job", "weekly"): "oops",  # type: ignore[dict-item]
            }
        },
    )

    payload = generate_weekly_summary(snapshot, locale="ja", settings=SETTINGS)

    assert payload.body == SETTINGS.fallback
    assert payload.tags["severity"] == "degraded"
    assert payload.channel == "-"
