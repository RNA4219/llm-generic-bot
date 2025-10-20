from __future__ import annotations

import sys
from typing import Any, Dict

import pytest

from llm_generic_bot import main as main_module


pytestmark = pytest.mark.anyio("asyncio")


async def test_setup_runtime_uses_runtime_orchestrator() -> None:
    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "cooldown": {"window_sec": 60},
        "dedupe": {"enabled": False},
        "weather": {"enabled": False},
        "news": {"enabled": False},
        "omikuji": {"enabled": False},
        "dm_digest": {"enabled": False},
    }

    _scheduler, orchestrator, _jobs = main_module.setup_runtime(settings)

    try:
        assert orchestrator.__class__.__module__ == "llm_generic_bot.core.orchestrator.runtime"
        assert "llm_generic_bot.core.orchestrator.processor" in sys.modules
    finally:
        await orchestrator.close()
