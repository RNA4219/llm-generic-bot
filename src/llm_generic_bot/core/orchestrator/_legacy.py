from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Optional, Protocol

from ..cooldown import CooldownGate
from ..dedupe import NearDuplicateFilter
from ...infra import MetricsBackend, collect_weekly_snapshot
from ...infra import metrics as metrics_module  # noqa: F401 - re-exported for tests
from ..orchestrator_metrics import (
    MetricsRecorder,
    NullMetricsRecorder,
    resolve_metrics_boundary,
)

# LEGACY_ORCHESTRATOR_CHECKLIST: processor delegation registered
_processor_path = Path(__file__).with_name("processor.py")
_processor_spec = spec_from_file_location(
    "llm_generic_bot.core.orchestrator.processor",
    _processor_path,
)
if _processor_spec is None or _processor_spec.loader is None:  # pragma: no cover - import machinery guard
    raise RuntimeError("failed to load orchestrator processor module")
_processor_module = module_from_spec(_processor_spec)
_processor_spec.loader.exec_module(_processor_module)
sys.modules[_processor_spec.name] = _processor_module
processor = _processor_module

if TYPE_CHECKING:
    from ...infra.metrics import WeeklyMetricsSnapshot
    from ..orchestrator_metrics import MetricsBoundary


class Sender(Protocol):
    async def send(
        self,
        text: str,
        channel: Optional[str] = None,
        *,
        job: Optional[str] = None,
    ) -> None:
        ...


class PermitDecisionLike(Protocol):
    allowed: bool
    reason: Optional[str]
    retryable: bool
    job: Optional[str]
    retry_after: Optional[float]
    level: Optional[str]


@dataclass(frozen=True)
class _PermitDecision:
    allowed: bool
    reason: Optional[str] = None
    retryable: bool = True
    job: Optional[str] = None
    retry_after: Optional[float] = None
    level: Optional[str] = None

    @classmethod
    def allowed(cls, job: Optional[str] = None) -> "_PermitDecision":  # type: ignore[no-redef]
        return cls(True, None, True, job)

    @classmethod
    def allow(cls, job: Optional[str] = None) -> "_PermitDecision":
        return cls(True, None, True, job)


PermitDecision = _PermitDecision


class PermitEvaluator(Protocol):
    def __call__(
        self, platform: str, channel: Optional[str], job: str
    ) -> PermitDecisionLike:
        ...


@dataclass
class _SendRequest:
    text: str
    job: str
    platform: str
    channel: Optional[str]
    correlation_id: str
    engagement_score: Optional[float] = None


class Orchestrator:
    def __init__(
        self,
        *,
        sender: Sender,
        cooldown: CooldownGate,
        dedupe: NearDuplicateFilter,
        permit: PermitEvaluator,
        metrics: MetricsBackend | MetricsRecorder | None = None,
        logger: Optional[logging.Logger] = None,
        queue_size: int = 128,
        platform: str = "-",
    ) -> None:
        self._sender = sender
        self._cooldown = cooldown
        self._dedupe = dedupe
        self._permit = permit
        boundary = resolve_metrics_boundary(metrics)
        self._metrics_boundary: MetricsBoundary = boundary
        self._metrics_service = boundary.service
        self._metrics = boundary.recorder
        self._logger = logger or logging.getLogger(__name__)
        self._queue: asyncio.Queue[_SendRequest | None] = asyncio.Queue(maxsize=queue_size)
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._default_platform = platform
        self._start_worker()

    async def enqueue(
        self,
        text: str,
        *,
        job: str,
        platform: str,
        channel: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        if self._closed:
            raise RuntimeError("orchestrator is closed")
        corr = correlation_id or uuid.uuid4().hex
        engagement_score: Optional[float] = None
        raw_engagement = getattr(text, "engagement_score", None)
        if isinstance(raw_engagement, (int, float)):
            engagement_score = float(raw_engagement)
        request = _SendRequest(
            text=str(text),
            job=job,
            platform=platform,
            channel=channel,
            correlation_id=corr,
            engagement_score=engagement_score,
        )
        await self._queue.put(request)
        return corr

    async def flush(self, timeout: float = 5.0) -> None:
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)
        if self._worker:
            await self._worker

    async def weekly_snapshot(self) -> WeeklyMetricsSnapshot:
        return await collect_weekly_snapshot(self._metrics_service)

    def _start_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    async def send(
        self,
        text: str,
        channel: Optional[str] = None,
        *,
        job: str,
    ) -> None:
        await self.enqueue(
            text,
            job=job,
            platform=self._default_platform,
            channel=channel,
        )
        await self.flush()

    async def _run(self) -> None:
        while True:
            request = await self._queue.get()
            if request is None:
                self._queue.task_done()
                break
            try:
                await self._process(request)
            finally:
                self._queue.task_done()

    async def _process(self, request: _SendRequest) -> None:
        await _processor_module.process(
            request=request,
            sender=self._sender,
            cooldown=self._cooldown,
            dedupe=self._dedupe,
            permit=self._permit,
            metrics_boundary=self._metrics_boundary,
            metrics=self._metrics,
            logger=self._logger,
            record_event=self._record_event,
        )

    def _record_event(
        self,
        name: str,
        tags: Mapping[str, str],
        *,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, object] | None = None,
        force: bool = False,
    ) -> None:
        _processor_module.record_event(
            boundary=self._metrics_boundary,
            name=name,
            tags=tags,
            measurements=measurements,
            metadata=metadata,
            force=force,
        )
