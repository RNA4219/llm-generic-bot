from llm_generic_bot.core.queue import CoalesceQueue


def test_coalesce_queue_merges_close_messages() -> None:
    queue = CoalesceQueue(window_seconds=60.0, threshold=3)
    base = 1000.0
    queue.push("first", priority=5, created_at=base)
    queue.push("second", priority=2, created_at=base + 30.0)

    ready = queue.pop_ready(base + 61.0)

    assert len(ready) == 1
    batch = ready[0]
    assert batch.priority == 2
    assert batch.text == "first\nsecond"


def test_coalesce_queue_flushes_on_threshold() -> None:
    queue = CoalesceQueue(window_seconds=120.0, threshold=2)
    base = 2000.0
    queue.push("first", priority=5, created_at=base)
    queue.push("second", priority=4, created_at=base + 10.0)

    ready = queue.pop_ready(base + 10.0)

    assert len(ready) == 1
    batch = ready[0]
    assert batch.priority == 4
    assert batch.text == "first\nsecond"


def test_coalesce_queue_single_message_batches() -> None:
    queue = CoalesceQueue(window_seconds=45.0, threshold=3)
    base = 3000.0
    queue.push("solo", priority=7, created_at=base)

    ready = queue.pop_ready(base + 46.0)

    assert len(ready) == 1
    batch = ready[0]
    assert batch.priority == 7
    assert batch.text == "solo"
