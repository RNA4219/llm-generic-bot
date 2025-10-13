import json
import os
import time
from pathlib import Path

import pytest

from llm_generic_bot.config.loader import Settings


@pytest.mark.usefixtures("caplog")
def test_settings_preserves_previous_data_when_reload_fails(tmp_path, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    settings = Settings(str(config_path))
    assert settings.data == {"foo": "bar"}

    caplog.clear()
    with caplog.at_level("WARNING"):
        config_path.write_text("{ invalid", encoding="utf-8")
        os.utime(config_path, (time.time() + 1, time.time() + 1))

    assert settings.data == {"foo": "bar"}

    assert any("Failed to reload settings" in message for message in caplog.messages)


def test_settings_example_contains_report_and_metrics_blocks() -> None:
    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.example.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    report = settings.get("report")
    assert isinstance(report, dict)
    assert report.get("_usage", "").startswith("週次サマリ")
    assert report.get("enabled") is False
    assert report.get("schedule") == "Monday 09:00"
    assert report.get("channel") == "ops-weekly"

    permit_cfg = report.get("permit") if isinstance(report, dict) else None
    assert isinstance(permit_cfg, dict)
    assert permit_cfg.get("job") == "weekly_report"
    assert permit_cfg.get("channel") == "ops-weekly"
    assert permit_cfg.get("platform") == "discord"

    metrics_cfg = settings.get("metrics")
    assert isinstance(metrics_cfg, dict)
    assert metrics_cfg.get("_usage", "").startswith("ランタイムメトリクス")
    assert metrics_cfg.get("backend") == "memory"
    assert metrics_cfg.get("retention_days") == 14

    export_cfg = metrics_cfg.get("export") if isinstance(metrics_cfg, dict) else None
    assert isinstance(export_cfg, dict)
    assert export_cfg.get("enabled") is False
    assert export_cfg.get("destination") == "stdout"
