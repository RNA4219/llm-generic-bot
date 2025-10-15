import pytest

from llm_generic_bot.core.orchestrator_metrics import format_metric_value


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.0, "0"),
        (0.0001, "0"),
        (1.2304, "1.23"),
        (3.0, "3"),
        (12.3456, "12.346"),
        (-0.0, "-0"),
        (-2.5, "-2.5"),
        (-3.0004, "-3"),
    ],
)
def test_format_metric_value(value: float, expected: str) -> None:
    assert format_metric_value(value) == expected
