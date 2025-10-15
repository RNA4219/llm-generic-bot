import pytest

from llm_generic_bot.core.orchestrator_metrics import (
    MetricsBoundary,
    NullMetricsRecorder as BoundaryNullRecorder,
)
from llm_generic_bot.infra import metrics as metrics_module


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
    aggregator = metrics_module._AGGREGATOR
    original_backend = aggregator.backend
    original_configured = aggregator.backend_configured
    return recorder, original_backend, original_configured


def test_suppress_backend_restores_state_when_including_self_backend() -> None:
    recorder, original_backend, original_configured = _configure_stub_backend()
    aggregator = metrics_module._AGGREGATOR
    boundary = MetricsBoundary(recorder=recorder, service=None)

    with boundary.suppress_backend(include_self_backend=True):
        assert aggregator.backend is not original_backend
        assert isinstance(aggregator.backend, metrics_module.NullMetricsRecorder)
        assert aggregator.backend_configured == original_configured

    assert aggregator.backend is original_backend
    assert aggregator.backend_configured == original_configured


def test_suppress_backend_preserves_backend_when_excluding_self_recorder() -> None:
    recorder, original_backend, original_configured = _configure_stub_backend()
    aggregator = metrics_module._AGGREGATOR
    boundary = MetricsBoundary(recorder=recorder, service=None)

    with boundary.suppress_backend(include_self_backend=False):
        assert aggregator.backend is original_backend
        assert aggregator.backend_configured == original_configured

    assert aggregator.backend is original_backend
    assert aggregator.backend_configured == original_configured


def test_suppress_backend_restores_backend_for_null_recorder() -> None:
    _, original_backend, original_configured = _configure_stub_backend()
    aggregator = metrics_module._AGGREGATOR
    boundary = MetricsBoundary(recorder=BoundaryNullRecorder(), service=None)

    with boundary.suppress_backend(include_self_backend=False):
        assert aggregator.backend is not original_backend
        assert isinstance(aggregator.backend, metrics_module.NullMetricsRecorder)
        assert aggregator.backend_configured == original_configured

    assert aggregator.backend is original_backend
    assert aggregator.backend_configured == original_configured


def test_suppress_backend_keeps_new_backend_when_reconfigured() -> None:
    recorder, _, _ = _configure_stub_backend()
    aggregator = metrics_module._AGGREGATOR
    replacement = RecorderStub()
    boundary = MetricsBoundary(recorder=recorder, service=None)

    with boundary.suppress_backend(include_self_backend=True):
        metrics_module.configure_backend(replacement)
        assert aggregator.backend is replacement

    assert aggregator.backend is replacement
    assert aggregator.backend_configured is True
