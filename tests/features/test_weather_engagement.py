"""Legacy shim for relocated weather engagement tests."""

# LEGACY_WEATHER_ENGAGEMENT_TEST_CHECKLIST
# - [ ] 新ディレクトリ tests/features/weather_engagement/ 配下のテストを確認すること
# - [ ] レガシーシムを削除して新構成へ一本化すること

from .weather_engagement.test_cooldown import *  # noqa: F401,F403
from .weather_engagement.test_history_filter import *  # noqa: F401,F403
from .weather_engagement.test_resume_conditions import *  # noqa: F401,F403
from .weather_engagement.test_scoring import *  # noqa: F401,F403
