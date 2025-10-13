import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from llm_generic_bot.config.loader import Settings
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.runtime.reload import log_settings_diff
from llm_generic_bot.runtime.setup import setup_runtime


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_BASE_CONFIG: dict[str, Any] = {
    "timezone": "UTC",
    "profiles": {"discord": {"enabled": True, "channel": "general"}},
}
_LOGGER_NAME = "llm_generic_bot.runtime.reload"
_UPDATED_CONFIG: dict[str, Any] = {
    "timezone": "UTC",
    "profiles": {"discord": {"enabled": True, "channel": "updates"}},
    "news": {"schedule": "07:30"},
}
_EXPECTED_DIFF: list[dict[str, Any]] = [
    {
        "event": "settings_diff",
        "changes": [
            {"path": "news", "type": "added", "value": {"schedule": "07:30"}},
            {
                "path": "profiles.discord.channel",
                "type": "changed",
                "old": "general",
                "new": "updates",
            },
        ],
    }
]


def _write_config(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _load_runtime(path: Path, payload: dict[str, Any]) -> tuple[Settings, Any]:
    _write_config(path, payload)
    settings = Settings(str(path))
    _, orchestrator, _ = setup_runtime(
        settings.data, queue=CoalesceQueue(window_seconds=0.0, threshold=1)
    )
    return settings, orchestrator


@pytest.mark.parametrize(
    ("updated_config", "expected"),
    [(_UPDATED_CONFIG, _EXPECTED_DIFF), (_BASE_CONFIG, [])],
)
async def test_settings_reload_diff_logging(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    updated_config: dict[str, Any],
    expected: list[dict[str, Any]],
) -> None:
    config_path = tmp_path / "settings.json"
    settings, orchestrator = _load_runtime(config_path, _BASE_CONFIG)

    caplog.set_level("INFO", logger=_LOGGER_NAME)
    previous_data = json.loads(json.dumps(settings.data))
    previous_mtime = os.stat(config_path).st_mtime
    _write_config(config_path, updated_config)
    os.utime(config_path, (previous_mtime + 1.0, previous_mtime + 1.0))
    settings.reload()

    await log_settings_diff(
        logging.getLogger(_LOGGER_NAME),
        old_settings=previous_data,
        new_settings=settings.data,
    )

    assert [
        json.loads(record.msg) for record in caplog.records if record.name == _LOGGER_NAME
    ] == expected

    await orchestrator.close()
