import json
from pathlib import Path


def test_cooldown_jobs_keys():
    settings_path = Path("config/settings.example.json")
    with settings_path.open("r", encoding="utf-8") as f:
        settings = json.load(f)

    cooldown_jobs = settings["cooldown"]["jobs"]
    assert set(cooldown_jobs) == {"weather", "news", "omikuji", "dm_digest"}
