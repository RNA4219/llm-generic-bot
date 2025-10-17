from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from llm_generic_bot.runtime.setup import setup_runtime


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_setup_runtime_disables_dedupe_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "dedupe": {"enable": False},
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": False},
        },
    }

    _, orchestrator, _ = setup_runtime(settings)

    assert orchestrator._dedupe.permit("text") is True
    assert orchestrator._dedupe.permit("text") is True
    assert orchestrator._dedupe.permit("text") is True

    asyncio.run(orchestrator.close())


def test_settings_example_uses_enabled_key_for_dedupe() -> None:
    config_path = Path("config/settings.example.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    dedupe_block = config.get("dedupe")
    assert isinstance(dedupe_block, dict)

    assert "enabled" in dedupe_block
    assert "enable" not in dedupe_block
