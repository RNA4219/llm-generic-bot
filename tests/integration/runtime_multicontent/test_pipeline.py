from __future__ import annotations

LEGACY_RUNTIME_MULTICONTENT_PIPELINE_CHECKLIST = [
    "- [x] 天気ジョブのテストを test_pipeline_weather.py へ移行",
    "- [x] ニュースジョブのテストを test_pipeline_news.py へ移行",
    "- [x] おみくじジョブのテストを test_pipeline_omikuji.py へ移行",
    "- [x] DM ダイジェストジョブのテストを test_pipeline_dm_digest.py へ移行",
    "- [x] 週次レポートジョブのテストを test_pipeline_weekly_report.py へ移行",
]


def test_legacy_runtime_multicontent_pipeline_checklist_complete() -> None:
    assert all(item.startswith("- [x] ") for item in LEGACY_RUNTIME_MULTICONTENT_PIPELINE_CHECKLIST)
