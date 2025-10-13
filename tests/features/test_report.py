"""Sprint 3: 週次サマリ機能の期待仕様."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

import pytest

from llm_generic_bot.features.report import ReportPayload, generate_weekly_summary


@dataclass(frozen=True)
class FakeWeeklyMetricsSnapshot:
    period_start: date
    period_end: date
    totals: Mapping[str, int]
    breakdowns: Mapping[str, Mapping[str, int]]
    metadata: Mapping[str, object]


def test_weekly_report_happy_path() -> None:
    snapshot = FakeWeeklyMetricsSnapshot(
        period_start=date(2024, 4, 1),
        period_end=date(2024, 4, 7),
        totals={
            "jobs_processed": 120,
            "jobs_succeeded": 114,
            "jobs_failed": 6,
        },
        breakdowns={
            "channels": {"#ops": 72, "#alerts": 48},
            "failure_tags": {"timeout": 4, "quota": 2},
        },
        metadata={
            "preferred_channel": "#ops",
            "failure_rate_alert": 0.25,
        },
    )

    payload = generate_weekly_summary(snapshot, locale="ja", fallback="fallback")

    assert isinstance(payload, ReportPayload)
    assert payload.channel == "#ops"
    assert "2024-04-01" in payload.body
    assert "114" in payload.body and "6" in payload.body
    assert "timeout" in payload.body and "quota" in payload.body
    assert payload.tags["severity"] == "normal"
    assert payload.tags["locale"] == "ja"
    assert payload.tags["period"] == "2024-04-01/2024-04-07"


@pytest.mark.parametrize(
    "totals",
    [
        {},
        {"jobs_processed": 10, "jobs_succeeded": 2, "jobs_failed": 8},
    ],
)
def test_weekly_report_handles_missing_metrics(totals: Mapping[str, int]) -> None:
    snapshot = FakeWeeklyMetricsSnapshot(
        period_start=date(2024, 4, 8),
        period_end=date(2024, 4, 14),
        totals=totals,
        breakdowns={"channels": {}, "failure_tags": {}},
        metadata={"preferred_channel": "#ops", "failure_rate_alert": 0.3},
    )

    payload = generate_weekly_summary(snapshot, locale="ja", fallback="fallback body")

    assert payload.body == "fallback body"
    assert payload.channel == "#ops"
    assert payload.tags["severity"] in {"degraded", "high"}
    assert payload.tags["locale"] == "ja"


def test_weekly_report_uses_top_channel_when_preference_missing() -> None:
    snapshot = FakeWeeklyMetricsSnapshot(
        period_start=date(2024, 4, 15),
        period_end=date(2024, 4, 21),
        totals={
            "jobs_processed": 90,
            "jobs_succeeded": 84,
            "jobs_failed": 6,
        },
        breakdowns={
            "channels": {"#alerts": 50, "#ops": 40},
            "failure_tags": {"timeout": 3},
        },
        metadata={"failure_rate_alert": 0.3},
    )

    payload = generate_weekly_summary(snapshot, locale="ja", fallback="fallback")

    assert payload.channel == "#alerts"
    assert payload.tags["top_channel"] == "#alerts"
