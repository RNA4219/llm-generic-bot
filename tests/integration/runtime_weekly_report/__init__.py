"""Runtime weekly report integration tests.

Categories
~~~~~~~~~~
- スケジューラ連携: ``test_scheduler`` でスケジュールやディスパッチ設定を検証。
- テンプレート整形: ``test_templates`` でテンプレート変換とコンテキスト展開を検証。
- fallback/失敗率: ``test_fallbacks`` で成功率集計のフォールバック条件を検証。

Shared fixtures/mocks
~~~~~~~~~~~~~~~~~~~~~
- ``anyio_backend``: ``asyncio`` イベントループを提供。
- ``fake_summary``: ``ReportPayload`` を返す集計モック。呼び出し回数は ``calls`` で参照。
- ``weekly_snapshot``: ``WeeklyMetricsSnapshot`` を生成する非同期モックファクトリ。
"""

from ._shared import __all__ as _shared_all
from ._shared import *  # noqa: F401,F403
from .test_fallbacks import test_weekly_report_skips_self_success_rate
from .test_scheduler import (
    test_weekly_report_permit_override_applies_to_dispatch,
    test_weekly_report_respects_weekday_schedule,
)
from .test_templates import (
    test_weekly_report_config_template_regression,
    test_weekly_report_template_line_context,
)

__all__ = [
    *_shared_all,
    "test_weekly_report_config_template_regression",
    "test_weekly_report_permit_override_applies_to_dispatch",
    "test_weekly_report_respects_weekday_schedule",
    "test_weekly_report_skips_self_success_rate",
    "test_weekly_report_template_line_context",
]
