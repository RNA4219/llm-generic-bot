from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Mapping, Protocol, cast

from ..infra import MetricsBackend, make_metrics_recorder
from ..infra import metrics as metrics_module

if TYPE_CHECKING:
    from ..infra.metrics.reporting import _GlobalMetricsAggregator as AggregatorT
else:  # pragma: no cover - typing alias
    AggregatorT = object


class MetricsRecorder(Protocol):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        ...

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        ...


class NullMetricsRecorder(MetricsRecorder):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        return None

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        return None


@dataclass(slots=True)
class MetricsBoundary:
    recorder: MetricsRecorder
    service: MetricsBackend | None

    def is_enabled(self) -> bool:
        if isinstance(self.recorder, NullMetricsRecorder):
            return False
        if self.service is None:
            return False
        return True

    @contextmanager
    def suppress_backend(self, include_self_backend: bool) -> Iterator[None]:
        aggregator = self._resolve_aggregator()
        original_backend = None
        replaced = False
        if aggregator is not None:
            original_backend = getattr(aggregator, "backend", None)
            if original_backend is not None:
                if isinstance(self.recorder, NullMetricsRecorder):
                    aggregator.backend = metrics_module.NullMetricsRecorder()
                    replaced = True
                elif include_self_backend and original_backend is self.recorder:
                    aggregator.backend = metrics_module.NullMetricsRecorder()
                    replaced = True
        try:
            yield
        finally:
            if replaced and aggregator is not None:
                setattr(aggregator, "backend", original_backend)

    def record_event(
        self,
        name: str,
        tags: Mapping[str, str],
        *,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, object] | None = None,
        force: bool = False,
    ) -> None:
        if self.service is None or not measurements:
            return
        if not force:
            aggregator = self._resolve_aggregator()
            if aggregator is not None:
                backend = getattr(aggregator, "backend", None)
                if backend is self.recorder:
                    return
        self.service.record_event(name, tags=tags, measurements=measurements, metadata=metadata)

    @staticmethod
    def _resolve_aggregator() -> AggregatorT | None:
        return cast(
            AggregatorT | None, getattr(metrics_module, "_AGGREGATOR", None)
        )


def resolve_metrics_boundary(
    metrics: MetricsBackend | MetricsRecorder | None,
) -> MetricsBoundary:
    service: MetricsBackend | None
    recorder: MetricsRecorder | None
    if isinstance(metrics, MetricsBackend):
        service = metrics
        recorder = make_metrics_recorder(metrics)
    else:
        service = None
        recorder = metrics
    if recorder is not None:
        metrics_module.configure_backend(recorder)
    return MetricsBoundary(recorder or NullMetricsRecorder(), service)


def format_metric_value(value: float) -> str:
    formatted = f"{value:.3f}"
    trimmed = formatted.rstrip("0").rstrip(".")
    return trimmed or "0"
