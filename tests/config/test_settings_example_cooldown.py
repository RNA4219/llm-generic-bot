"""settings.example.json の cooldown.jobs に対する検証テスト。"""

from __future__ import annotations

import json
from pathlib import Path


def test_cooldown_jobs_match_expected_set() -> None:
    settings_path = Path("config/settings.example.json")
    with settings_path.open(encoding="utf-8") as fp:
        settings = json.load(fp)

    cooldown = settings["cooldown"]
    jobs = cooldown["jobs"]
    assert set(jobs) == {"weather", "news", "omikuji", "dm_digest"}
