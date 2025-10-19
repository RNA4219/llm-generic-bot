"""settings.example.json の Permit/スケジューラ設定検証テスト。"""

from __future__ import annotations

import json
from pathlib import Path


def test_scheduler_jitter_range_and_permit_tiers_are_defined() -> None:
    settings_path = Path("config/settings.example.json")
    with settings_path.open(encoding="utf-8") as fp:
        settings = json.load(fp)

    scheduler = settings["scheduler"]
    assert scheduler["jitter_range_seconds"] == [3, 15]

    permit = settings["permit"]
    tiers = permit["tiers"]
    assert [tier["name"] for tier in tiers] == ["default", "elevated"]
