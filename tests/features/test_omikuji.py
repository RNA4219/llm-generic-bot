from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict

from llm_generic_bot.features import omikuji


def _run(cfg: Dict[str, Any], **kwargs: Any) -> str:
    return asyncio.run(omikuji.build_omikuji_post(cfg, **kwargs))


def test_user_seed_consistency() -> None:
    cfg: Dict[str, Any] = {
        "omikuji": {
            "templates": [
                {"id": "first", "text": "{user_id}:{fortune}:first"},
                {"id": "second", "text": "{user_id}:{fortune}:second"},
            ],
            "fortunes": ["大吉", "中吉", "吉"],
        }
    }

    day = date(2024, 1, 1)
    first = _run(cfg, user_id="alice", today=day)
    second = _run(cfg, user_id="alice", today=day)
    assert first == second

    different_user = _run(cfg, user_id="bob", today=day)
    assert different_user != first

    next_day = _run(cfg, user_id="alice", today=day.replace(day=2))
    assert next_day != first


def test_template_rotation_across_days() -> None:
    cfg: Dict[str, Any] = {
        "omikuji": {
            "templates": [
                {"id": "alpha", "text": "alpha:{fortune}"},
                {"id": "beta", "text": "beta:{fortune}"},
                {"id": "gamma", "text": "gamma:{fortune}"},
            ],
            "fortunes": ["末吉", "凶"],
        }
    }

    day_one = _run(cfg, user_id="user", today=date(2024, 1, 1))
    day_two = _run(cfg, user_id="user", today=date(2024, 1, 2))
    day_three = _run(cfg, user_id="user", today=date(2024, 1, 3))

    assert day_one.startswith("alpha:")
    assert day_two.startswith("beta:")
    assert day_three.startswith("gamma:")


def test_template_fallback_from_locale(tmp_path: Path) -> None:
    locale_path = tmp_path / "ja.yml"
    locale_data = {
        "ja": {
            "omikuji": {
                "templates": {
                    "fallback": "{user_id}の今日の運勢は{fortune}です",
                }
            }
        }
    }
    locale_path.write_text(json.dumps(locale_data), encoding="utf-8")

    cfg: Dict[str, Any] = {
        "omikuji": {
            "templates": [
                {"id": "fallback", "fallback_key": "omikuji.templates.fallback"}
            ],
            "fortunes": ["小吉"],
            "locales_path": locale_path,
        }
    }

    result = _run(cfg, user_id="tester", today=date(2024, 1, 5))
    assert result == "testerの今日の運勢は小吉です"
