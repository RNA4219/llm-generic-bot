from __future__ import annotations

import pytest

from llm_generic_bot.runtime.setup import setup_runtime


def test_setup_runtime_raises_when_no_profiles_enabled() -> None:
    settings = {
        "profiles": {
            "discord": {"enabled": False},
            "misskey": {"enabled": False},
        }
    }

    with pytest.raises(ValueError):
        setup_runtime(settings)
