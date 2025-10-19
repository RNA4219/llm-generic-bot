"""settings.example.json の scheduler / permit セクション検証テスト。"""

from __future__ import annotations

import json
from pathlib import Path


def test_scheduler_and_permit_sections_present() -> None:
    settings_path = Path("config/settings.example.json")
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    scheduler = settings["scheduler"]
    assert scheduler["_usage"].startswith("スケジューラの")
    assert scheduler["jitter_range_seconds"] == [60, 180]

    batch = scheduler["batch"]
    assert batch["_usage"].startswith("CoalesceQueue")
    assert batch["threshold"] == 3
    assert batch["window_seconds"] == 180

    permit = settings["permit"]
    assert permit["_usage"].startswith("PermitGate")

    tiers = permit["tiers"]
    assert "news" in tiers
    assert tiers["news"] == {"day": 12, "window_min": 20, "burst_limit": 3}
