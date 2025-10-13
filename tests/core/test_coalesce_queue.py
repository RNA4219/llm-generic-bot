import pytest

from llm_generic_bot.core.queue import CoalesceQueue


def test_coalesce_queue_merges_close_messages() -> None:
    queue = CoalesceQueue(window_seconds=60.0, threshold=3)
    base = 1000.0
    queue.push("first", priority=5, job="weather", created_at=base)
    queue.push("second", priority=2, job="weather", created_at=base + 30.0)

    ready = queue.pop_ready(base + 61.0)

    assert len(ready) == 1
    batch = ready[0]
    assert batch.priority == 2
    assert batch.text == "first\nsecond"
    assert batch.job == "weather"


def test_coalesce_queue_flushes_on_threshold() -> None:
    queue = CoalesceQueue(window_seconds=120.0, threshold=2)
    base = 2000.0
    queue.push("first", priority=5, job="alerts", created_at=base)
    queue.push("second", priority=4, job="alerts", created_at=base + 10.0)

    ready = queue.pop_ready(base + 10.0)

    assert len(ready) == 1
    batch = ready[0]
    assert batch.priority == 4
    assert batch.text == "first\nsecond"


def test_coalesce_queue_single_message_batches() -> None:
    queue = CoalesceQueue(window_seconds=45.0, threshold=3)
    base = 3000.0
    queue.push("solo", priority=7, job="solo", created_at=base)

    ready = queue.pop_ready(base + 46.0)

    assert len(ready) == 1
    batch = ready[0]
    assert batch.priority == 7
    assert batch.text == "solo"


@pytest.mark.parametrize(
    "first_kwargs, second_kwargs",
    [
        (
            {"priority": 2, "job": "alerts", "channel": "alpha"},
            {"priority": 3, "job": "alerts", "channel": "beta"},
        ),
        (
            {"priority": 4, "job": "weather", "channel": "general"},
            {"priority": 5, "job": "traffic", "channel": "general"},
        ),
        (
            {"priority": 1, "job": "status", "channel": "ops"},
            {"priority": 7, "job": "status", "channel": "ops"},
        ),
    ],
    ids=["channel-isolation", "job-isolation", "priority-isolation"],
)
def test_coalesce_queue_separates_incompatible_batches(
    first_kwargs: dict[str, object], second_kwargs: dict[str, object]
) -> None:
    queue = CoalesceQueue(window_seconds=90.0, threshold=5)
    base = 4000.0
    queue.push("first", created_at=base, **first_kwargs)
    queue.push("second", created_at=base + 10.0, **second_kwargs)

    ready = queue.pop_ready(base + 120.0)

    assert len(ready) == 2
    messages = {batch.text: batch for batch in ready}
    assert "first" in messages
    assert "second" in messages
    first_batch = messages["first"]
    second_batch = messages["second"]
    assert first_batch.job == first_kwargs["job"]
    assert first_batch.channel == first_kwargs["channel"]
    assert first_batch.priority == first_kwargs["priority"]
    assert second_batch.job == second_kwargs["job"]
    assert second_batch.channel == second_kwargs["channel"]
    assert second_batch.priority == second_kwargs["priority"]
