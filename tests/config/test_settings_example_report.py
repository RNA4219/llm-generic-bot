"""settings.example.json の週次サマリテンプレート検証."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from llm_generic_bot.features.report import generate_weekly_summary
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot


def _tags(**items: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(items.items()))


def test_settings_example_report_template_supports_label_placeholder() -> None:
    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.example.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    report_cfg = settings.get("report")
    assert isinstance(report_cfg, dict)
    template_cfg = report_cfg.get("template") if isinstance(report_cfg, dict) else None
    assert isinstance(template_cfg, dict)
    assert template_cfg.get("line") == "・{label}: {value}"

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
        templates={"ja": template_cfg},
    )

    lines = payload.body.splitlines()
    assert lines[0] == "📊 運用サマリ (2024-04-01〜2024-04-07)"
    assert lines[1].startswith("・総ジョブ: 118件 (成功 114件 / 失敗 4件")
    assert payload.tags["severity"] == "normal"
    assert payload.tags["locale"] == "ja"
