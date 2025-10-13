from __future__ import annotations

from llm_generic_bot.runtime.config_diff import compute_diff


def test_compute_diff_detects_nested_changes() -> None:
    previous = {
        "weather": {"enabled": True},
        "news": {"priority": 5},
    }
    current = {
        "weather": {"enabled": False, "schedule": "09:00"},
        "omikuji": {"enabled": True},
    }

    diff = compute_diff(previous, current)

    assert diff == {
        "added": {"omikuji": {"enabled": True}},
        "removed": {"news": {"priority": 5}},
        "changed": {
            "weather": {
                "added": {"schedule": "09:00"},
                "changed": {"enabled": {"old": True, "new": False}},
            }
        },
    }
