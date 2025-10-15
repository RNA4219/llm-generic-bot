import pytest

from llm_generic_bot.core.orchestrator_metrics import (
    MetricsBoundary,
    NullMetricsRecorder as BoundaryNullRecorder,
)
from llm_generic_bot.infra import metrics as metrics_module
from llm_generic_bot.infra.metrics import aggregator_state


class RecorderStub:
    def increment(self, name: str, tags: dict[str, str] | None = None) -> None:
        return None

    def observe(
        self, name: str, value: float, tags: dict[str, str] | None = None
    ) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_metrics() -> None:
    metrics_module.reset_for_test()
    try:
        yield
    finally:
        metrics_module.reset_for_test()


def _configure_stub_backend() -> tuple[RecorderStub, object, bool]:
    recorder = RecorderStub()
    metrics_module.configure_backend(recorder)
    aggregator = aggregator_state._AGGREGATOR
    original_backend = aggregator.backend
    original_configured = aggregator.backend_configured
    return recorder, original_backend, original_configured


def _snapshot_aggregator_state(
    *,
    aggregator: object,
    recorder: object,
    original_backend: object,
) -> dict[str, object]:
    backend = getattr(aggregator, "backend", None)
    return {
        "backend_is_original": backend is original_backend,
        "backend_is_recorder": backend is recorder,
        "backend_is_null_recorder": isinstance(
            backend, metrics_module.NullMetricsRecorder
        ),
        "backend_configured": getattr(aggregator, "backend_configured", None),
    }


def test_suppress_backend_restores_state_when_including_self_backend() -> None:
    recorder, original_backend, original_configured = _configure_stub_backend()
    aggregator = aggregator_state._AGGREGATOR
    boundary = MetricsBoundary(recorder=recorder, service=None)

    with boundary.suppress_backend(include_self_backend=True):
        assert _snapshot_aggregator_state(
            aggregator=aggregator,
            recorder=recorder,
            original_backend=original_backend,
        ) == {
            "backend_is_original": False,
            "backend_is_recorder": False,
            "backend_is_null_recorder": True,
            "backend_configured": original_configured,
        }

    assert _snapshot_aggregator_state(
        aggregator=aggregator,
        recorder=recorder,
        original_backend=original_backend,
    ) == {
        "backend_is_original": True,
        "backend_is_recorder": True,
        "backend_is_null_recorder": False,
        "backend_configured": original_configured,
    }


def test_suppress_backend_preserves_backend_when_excluding_self_recorder() -> None:
    recorder, original_backend, original_configured = _configure_stub_backend()
    aggregator = aggregator_state._AGGREGATOR
    boundary = MetricsBoundary(recorder=recorder, service=None)

    expected_snapshot = {
        "backend_is_original": True,
        "backend_is_recorder": True,
        "backend_is_null_recorder": False,
        "backend_configured": original_configured,
    }

    with boundary.suppress_backend(include_self_backend=False):
        assert _snapshot_aggregator_state(
            aggregator=aggregator,
            recorder=recorder,
            original_backend=original_backend,
        ) == expected_snapshot

    assert _snapshot_aggregator_state(
        aggregator=aggregator,
        recorder=recorder,
        original_backend=original_backend,
    ) == expected_snapshot


def test_suppress_backend_restores_backend_for_null_recorder() -> None:
    _, original_backend, original_configured = _configure_stub_backend()
    aggregator = aggregator_state._AGGREGATOR
    boundary = MetricsBoundary(recorder=BoundaryNullRecorder(), service=None)

    with boundary.suppress_backend(include_self_backend=False):
        assert _snapshot_aggregator_state(
            aggregator=aggregator,
            recorder=BoundaryNullRecorder(),
            original_backend=original_backend,
        ) == {
            "backend_is_original": False,
            "backend_is_recorder": False,
            "backend_is_null_recorder": True,
            "backend_configured": original_configured,
        }

    assert _snapshot_aggregator_state(
        aggregator=aggregator,
        recorder=BoundaryNullRecorder(),
        original_backend=original_backend,
    ) == {
        "backend_is_original": True,
        "backend_is_recorder": False,
        "backend_is_null_recorder": False,
        "backend_configured": original_configured,
    }


def test_suppress_backend_keeps_new_backend_when_reconfigured() -> None:
    recorder, _, _ = _configure_stub_backend()
    aggregator = aggregator_state._AGGREGATOR
    replacement = RecorderStub()
    boundary = MetricsBoundary(recorder=recorder, service=None)

    with boundary.suppress_backend(include_self_backend=True):
        metrics_module.configure_backend(replacement)
        assert _snapshot_aggregator_state(
            aggregator=aggregator,
            recorder=recorder,
            original_backend=replacement,
        ) == {
            "backend_is_original": True,
            "backend_is_recorder": False,
            "backend_is_null_recorder": False,
            "backend_configured": True,
        }

    assert _snapshot_aggregator_state(
        aggregator=aggregator,
        recorder=replacement,
        original_backend=replacement,
    ) == {
        "backend_is_original": True,
        "backend_is_recorder": True,
        "backend_is_null_recorder": False,
        "backend_configured": True,
    }
