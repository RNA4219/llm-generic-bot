from __future__ import annotations

import asyncio

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


def test_setup_runtime_disables_discord_via_string_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": "false"},
            "misskey": {"enabled": True, "channel": "general"},
        }
    }

    _, orchestrator, _ = setup_runtime(settings)

    assert getattr(orchestrator, "_default_platform") == "misskey"
    asyncio.run(orchestrator.close())


def test_setup_runtime_disables_misskey_via_string_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": "false"},
        }
    }

    _, orchestrator, _ = setup_runtime(settings)

    assert getattr(orchestrator, "_default_platform") == "discord"
    asyncio.run(orchestrator.close())


def test_setup_runtime_raises_when_profiles_disabled_via_string_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": "false"},
            "misskey": {"enabled": "false"},
        }
    }

    with pytest.raises(ValueError):
        setup_runtime(settings)
