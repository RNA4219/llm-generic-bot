"""Legacy import shim for runtime weekly report tests."""

from __future__ import annotations

from tests.integration.runtime_weekly_report import (
    test_fallbacks as _fallbacks,
    test_scheduler as _scheduler,
    test_templates as _templates,
)
from tests.integration.runtime_weekly_report._shared import (
    FakeSummary,
    anyio_backend,
    fake_summary,
    pytestmark,
    weekly_snapshot,
)

LEGACY_RUNTIME_WEEKLY_REPORT_SPLIT_CHECKLIST = """
- [ ] tests.integration.runtime_weekly_report.* から直接 import するよう参照箇所を更新する。
- [ ] このシムの __all__ から対応するテスト関数エイリアスを削除する。
- [ ] 本ファイルを削除後に pytest / mypy / ruff を再実行しグリーンを確認する。
"""

__all__ = [
    "FakeSummary",
    "LEGACY_RUNTIME_WEEKLY_REPORT_SPLIT_CHECKLIST",
    "anyio_backend",
    "fake_summary",
    "pytestmark",
    "weekly_snapshot",
    "test_weekly_report_config_template_regression",
    "test_weekly_report_permit_override_applies_to_dispatch",
    "test_weekly_report_respects_weekday_schedule",
    "test_weekly_report_skips_self_success_rate",
    "test_weekly_report_template_line_context",
]

# Re-export test callables while preventing duplicate collection.
test_weekly_report_respects_weekday_schedule = (
    _scheduler.test_weekly_report_respects_weekday_schedule
)
test_weekly_report_respects_weekday_schedule.__test__ = False

test_weekly_report_permit_override_applies_to_dispatch = (
    _scheduler.test_weekly_report_permit_override_applies_to_dispatch
)
test_weekly_report_permit_override_applies_to_dispatch.__test__ = False

test_weekly_report_config_template_regression = (
    _templates.test_weekly_report_config_template_regression
)
test_weekly_report_config_template_regression.__test__ = False

test_weekly_report_template_line_context = (
    _templates.test_weekly_report_template_line_context
)
test_weekly_report_template_line_context.__test__ = False

test_weekly_report_skips_self_success_rate = (
    _fallbacks.test_weekly_report_skips_self_success_rate
)
test_weekly_report_skips_self_success_rate.__test__ = False
