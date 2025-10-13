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
        header="📊 運用サマリ {start}〜{end}",
        summary="総ジョブ: {total}件 / 成功: {success}件 / 失敗: {failure}件 (成功率 {success_rate:.1f}%)",
        channels="活発チャンネル: {channels}",
        failures="主要エラー: {failures}",
    )
}


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

    assert isinstance(payload, ReportPayload)
    assert payload.channel == "#alerts"
    assert "📊 運用サマリ" in payload.body
    assert "114" in payload.body and "4" in payload.body
    assert "timeout" in payload.body and "quota" in payload.body
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
            header="Weekly summary {start} to {end}",
            summary="Processed {total} / Success {success} / Failure {failure} ({success_rate:.1f}%)",
            channels="Channels: {channels}",
            failures="Failures: {failures}",
        ),
        "ja": WeeklyReportTemplate(
            header="📈 サマリ {start}〜{end}",
            summary="処理数 {total} 成功 {success} 失敗 {failure} (成功率 {success_rate:.1f}%)",
            channels="活発チャンネル: {channels}",
            failures="主要エラー: {failures}",
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
    assert payload.body.startswith("Weekly summary")
