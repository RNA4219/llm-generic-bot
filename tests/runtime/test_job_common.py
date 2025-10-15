from __future__ import annotations

import pytest

from llm_generic_bot.runtime.jobs.common import collect_schedules


@pytest.mark.parametrize(
    ("config", "default", "expected"),
    [
        ({"schedule": "07:30"}, "09:00", ("07:30",)),
        ({"schedules": ["08:00", "12:00"]}, "09:00", ("08:00", "12:00")),
        ({}, "09:00", ("09:00",)),
    ],
)
def test_collect_schedules_variants(
    config: dict[str, object], default: str, expected: tuple[str, ...]
) -> None:
    assert collect_schedules(config, default=default) == expected


def test_collect_schedules_preserves_order_and_filters_invalid_entries() -> None:
    config = {
        "schedule": "06:00",
        "schedules": ["", "07:00", None, "08:00", 42, "09:00"],
    }

    result = collect_schedules(config, default="21:00")

    assert result == ("06:00", "07:00", "08:00", "09:00")
