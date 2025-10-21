from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import ContextManager, TYPE_CHECKING, Iterator, Mapping, Protocol, cast

from ..infra import MetricsBackend, make_metrics_recorder
from ..infra import metrics as metrics_module
from ..infra.metrics.aggregator_state import _AGGREGATOR as state_aggregator

if TYPE_CHECKING:
    from ..infra.metrics.aggregator_state import _GlobalMetricsAggregator as AggregatorT
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


def _context_manager_from_lock(lock: object | None) -> ContextManager[object]:
    if lock is not None and hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        return cast(ContextManager[object], lock)
    return cast(ContextManager[object], nullcontext())


@dataclass(slots=True)
class MetricsBoundary:
    recorder: MetricsRecorder
    service: MetricsBackend | None

    def is_enabled(self) -> bool:
        if isinstance(self.recorder, NullMetricsRecorder):
            return False
        if self.service is not None:
            return True
        aggregator = self._resolve_aggregator()
        if aggregator is None:
            return False
        return bool(getattr(aggregator, "backend_configured", False))

    @contextmanager
    def suppress_backend(self, include_self_backend: bool) -> Iterator[None]:
        aggregator = self._resolve_aggregator()
        lock = getattr(aggregator, "lock", None) if aggregator is not None else None
        original_backend: MetricsRecorder | None = None
        placeholder: MetricsRecorder | None = None
        replaced = False
        if aggregator is not None:
            with _context_manager_from_lock(lock):
                original_backend = getattr(aggregator, "backend", None)
                if original_backend is not None:
                    should_replace = isinstance(
                        self.recorder, NullMetricsRecorder
                    ) or (
                        include_self_backend and original_backend is self.recorder
                    )
                    if should_replace:
                        placeholder = metrics_module.NullMetricsRecorder()
                        setattr(aggregator, "backend", placeholder)
                        replaced = True
        try:
            yield
        finally:
            if replaced and aggregator is not None:
                with _context_manager_from_lock(lock):
                    if getattr(aggregator, "backend", None) is placeholder:
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
        return cast(AggregatorT, state_aggregator)


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
    metrics_module.configure_backend(recorder)
    return MetricsBoundary(recorder or NullMetricsRecorder(), service)


def build_retry_base_tags(
    *, retryable: bool, metadata: Mapping[str, str] | None = None
) -> dict[str, str]:
    tags: dict[str, str] = {"retryable": "true" if retryable else "false"}
    if metadata:
        for key, value in metadata.items():
            if key == "permit_level":
                tags.setdefault("level", value)
            else:
                tags[key] = value
    return tags


def build_retry_permit_tags(
    *,
    metadata: Mapping[str, str] | None,
    reason: str | None,
    level: str | None,
) -> dict[str, str]:
    tags: dict[str, str] = {}
    if metadata:
        source = metadata.get("retry_source")
        if source:
            tags["retry_source"] = source
        permit_level = metadata.get("permit_level")
        if permit_level:
            tags.setdefault("level", permit_level)
        retry_reason = metadata.get("retry_reason")
        if retry_reason:
            tags.setdefault("reevaluation_reason", retry_reason)
    if reason:
        tags.setdefault("reevaluation_reason", reason)
    if level is not None:
        tags.setdefault("level", str(level))
    return tags


def format_metric_value(value: float) -> str:
    formatted = f"{value:.3f}"
    trimmed = formatted.rstrip("0").rstrip(".")
    return trimmed or "0"
