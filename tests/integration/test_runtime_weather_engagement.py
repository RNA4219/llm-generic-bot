"""Temporary shim for relocated weather engagement integration tests."""

from __future__ import annotations

import pytest

from .weather_engagement.test_cache_control import *  # noqa: F401,F403
from .weather_engagement.test_cooldown_coordination import *  # noqa: F401,F403
from .weather_engagement.test_engagement_calculation import *  # noqa: F401,F403

pytestmark = pytest.mark.anyio("asyncio")


LEGACY_WEATHER_ENGAGEMENT_SPLIT_CHECKLIST = [
    "- [x] キャッシュ制御: tests/integration/weather_engagement/test_cache_control.py",
    "- [x] クールダウンとの協調: tests/integration/weather_engagement/test_cooldown_coordination.py",
    "- [x] エンゲージメント計算: tests/integration/weather_engagement/test_engagement_calculation.py",
    "完了後に本ファイルを削除する。",
]

__all__ = [
    "LEGACY_WEATHER_ENGAGEMENT_SPLIT_CHECKLIST",
]
