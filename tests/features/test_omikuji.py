from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pytest

from llm_generic_bot.features import omikuji


def _run(cfg: Dict[str, Any], **kwargs: Any) -> str | None:
    return asyncio.run(omikuji.build_omikuji_post(cfg, **kwargs))


@pytest.mark.parametrize(
    ("user_id", "expected"),
    (
        ("alice", "中吉"),
        ("bob", "吉"),
    ),
)
def test_user_seed_consistency(tmp_path: Path, user_id: str, expected: str) -> None:
    cfg: Dict[str, Any] = {
        "omikuji": {
            "templates": [
                {"id": "only", "text": "{fortune}"},
            ],
            "fortunes": ["大吉", "中吉", "吉"],
            "state_path": tmp_path / "state.json",
        }
    }

    result = _run(cfg, user_id=user_id, today=date(2024, 1, 1))
    assert result == expected


def test_template_rotation_without_reuse(tmp_path: Path) -> None:
    cfg: Dict[str, Any] = {
        "omikuji": {
            "templates": [
                {"id": "alpha", "text": "alpha"},
                {"id": "beta", "text": "beta"},
                {"id": "gamma", "text": "gamma"},
            ],
            "fortunes": ["末吉"],
            "state_path": tmp_path / "state.json",
        }
    }

    expectations = ["alpha", "beta", "gamma", None]
    results = [
        _run(cfg, user_id="user", today=date(2024, 1, 1))
        for _ in expectations
    ]

    assert results == expectations


def test_template_fallback_from_locale(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    cfg: Dict[str, Any] = {
        "omikuji": {
            "templates": [
                {"id": "fallback", "fallback_key": "omikuji.templates.fallback"}
            ],
            "fortunes": ["小吉"],
            "state_path": state_path,
        }
    }

    result = _run(cfg, user_id="tester", today=date(2024, 1, 5))
    assert result == "testerの今日の運勢は小吉です"
