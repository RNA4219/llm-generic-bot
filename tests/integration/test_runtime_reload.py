from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.config.loader import Settings

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _write_config(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp)


@pytest.fixture(autouse=True)
def stub_weather(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_build_weather_post(*_: Any, **__: Any) -> str:
        return "ok"

    monkeypatch.setattr(main_module, "build_weather_post", fake_build_weather_post)


def _base_config() -> Dict[str, Any]:
    return {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "cooldown": {"window_sec": 60},
        "weather": {"schedule": "00:00"},
        "news": {"enabled": False},
        "omikuji": {"enabled": False},
        "dm_digest": {"enabled": False},
    }


async def test_settings_reload_logs_diff(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = config_dir / "settings.json"
    base_config = _base_config()
    _write_config(config_path, base_config)

    settings = Settings(str(config_path))
    _scheduler, orchestrator, _ = main_module.setup_runtime(settings.data)

    updated = deepcopy(base_config)
    updated["profiles"]["discord"]["channel"] = "alerts"
    _write_config(config_path, updated)
    os.utime(config_path, (time.time() + 1, time.time() + 1))

    caplog.set_level(logging.INFO, logger="llm_generic_bot.config.loader")
    settings.reload()

    records = [record for record in caplog.records if getattr(record, "event", "") == "settings_reload"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.INFO
    assert record.diff == {"profiles.discord.channel": {"old": "general", "new": "alerts"}}

    await orchestrator.close()


async def test_settings_reload_skips_log_when_no_diff(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = config_dir / "settings.json"
    base_config = _base_config()
    _write_config(config_path, base_config)

    settings = Settings(str(config_path))
    _scheduler, orchestrator, _ = main_module.setup_runtime(settings.data)

    _write_config(config_path, base_config)
    os.utime(config_path, (time.time() + 1, time.time() + 1))

    caplog.set_level(logging.INFO, logger="llm_generic_bot.config.loader")
    settings.reload()

    records = [record for record in caplog.records if getattr(record, "event", "") == "settings_reload"]
    assert records == []

    await orchestrator.close()
