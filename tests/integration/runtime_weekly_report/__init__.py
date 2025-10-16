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

__all__ = [*_shared_all]
