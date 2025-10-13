from __future__ import annotations

import json
import os
import time
from pathlib import Path

from llm_generic_bot.config.loader import Settings


def test_settings_reload_logs_diff(tmp_path, caplog) -> None:
    path = Path(tmp_path / "settings.json")
    initial = {"weather": {"enabled": True}}
    path.write_text(json.dumps(initial), encoding="utf-8")
    settings = Settings(str(path))

    caplog.set_level("INFO", logger="llm_generic_bot.config.loader")

    new_data = {"weather": {"enabled": False}}
    path.write_text(json.dumps(new_data), encoding="utf-8")
    os.utime(path, (time.time(), time.time() + 1))

    _ = settings.data

    records = [
        record
        for record in caplog.records
        if record.name == "llm_generic_bot.config.loader" and record.msg == "settings_reload"
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "event", None) == "settings_reload"
    assert getattr(record, "path", None) == str(path)
    assert getattr(record, "diff", None) == {
        "changed": {"weather": {"changed": {"enabled": {"new": False, "old": True}}}}
    }
