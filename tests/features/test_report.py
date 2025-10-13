"""週次サマリ機能の単体テスト."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from llm_generic_bot.features.report import generate_weekly_summary


def test_weekly_report_happy_path() -> None:
    """主要メトリクスが閾値を超えた場合の警告文生成を検証する."""

    snapshot = SimpleNamespace(
        start=datetime(2024, 4, 1, tzinfo=timezone.utc),
        end=datetime(2024, 4, 8, tzinfo=timezone.utc),
        counters={
            "ops.incidents": {(): SimpleNamespace(count=3)},
            "ops.escalations": {(): SimpleNamespace(count=2)},
        },
        observations={
            "ops.ack_seconds": {
                (): SimpleNamespace(
                    count=7,
                    minimum=42.0,
                    maximum=180.0,
                    total=735.0,
                    average=105.0,
                )
            }
        },
    )

    summary = generate_weekly_summary(snapshot)

    assert summary.channel == "ops-weekly"
    assert summary.tags == {"job": "weekly_report", "severity": "warning"}
    assert summary.body == "\n".join(
        [
            "📊 運用サマリ (2024-04-01〜2024-04-08)",
            "・インシデント: 3件 ⚠️インシデント多発",
            "・エスカレーション: 2件 ⚠️要振り返り",
            "・平均初動時間: 105.0秒 ⚠️SLA超過",
            "詳細は運用ダッシュボードを参照",
        ]
    )


def test_weekly_report_handles_missing_metrics() -> None:
    """メトリクス欠損時にフォールバック文言を組み立てる."""

    snapshot = SimpleNamespace(
        start=datetime(2024, 4, 8, tzinfo=timezone.utc),
        end=datetime(2024, 4, 15, tzinfo=timezone.utc),
        counters={"ops.incidents": {(): SimpleNamespace(count=0)}},
        observations={},
    )

    summary = generate_weekly_summary(snapshot)

    assert summary.channel == "ops-weekly"
    assert summary.tags == {"job": "weekly_report", "severity": "info"}
    assert summary.body == "\n".join(
        [
            "📊 運用サマリ (2024-04-08〜2024-04-15)",
            "・インシデント: 0件",
            "・エスカレーション: データ欠損",
            "・平均初動時間: データ欠損",
            "詳細は運用ダッシュボードを参照",
        ]
    )
