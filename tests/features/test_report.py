"""Sprint 3: 週次サマリ機能のテストスケルトン."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="OPS-02 未実装: 週次サマリ生成と通知の正常系")
def test_weekly_report_happy_path() -> None:
    """Report Feature が週次メトリクスを集約し通知を構成できることを検証予定."""


@pytest.mark.skip(reason="OPS-02 未実装: 欠損データ時のフォールバック検証")
def test_weekly_report_handles_missing_metrics() -> None:
    """不足メトリクスがあってもフォールバックする挙動を検証予定."""
