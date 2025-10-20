from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, TYPE_CHECKING

from ...infra import MetricsBackend, collect_weekly_snapshot
from ..cooldown import CooldownGate
from ..dedupe import NearDuplicateFilter
from ..orchestrator_metrics import (
    MetricsBoundary,
    MetricsRecorder,
    resolve_metrics_boundary,
)
from . import processor

if TYPE_CHECKING:
    from ...infra.metrics import WeeklyMetricsSnapshot


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


class PermitDecision:
    __slots__ = (
        "_allowed",
        "_reason",
        "_retryable",
        "_job",
        "_retry_after",
        "_level",
    )

    def __init__(
        self,
        allowed: bool,
        reason: Optional[str] = None,
        retryable: bool = True,
        job: Optional[str] = None,
        *,
        retry_after: Optional[float] = None,
        level: Optional[str] = None,
    ) -> None:
        self._allowed = allowed
        self._reason = reason
        self._retryable = retryable
        self._job = job
        self._retry_after = retry_after
        self._level = level

    def __getattribute__(self, name: str) -> object:
        if name in {"allowed", "reason", "retryable", "job", "retry_after", "level"}:
            return object.__getattribute__(self, f"_{name}")
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: object) -> None:
        if not name.startswith("_"):
            raise AttributeError("PermitDecision is immutable")
        super().__setattr__(name, value)

    @classmethod
    def allow(cls, job: Optional[str] = None) -> PermitDecision:
        return cls(allowed=True, reason=None, retryable=True, job=job)

    @classmethod
    def allowed(cls, job: Optional[str] = None) -> PermitDecision:
        return cls.allow(job)

    def __repr__(self) -> str:
        return (
            "PermitDecision(allowed={allowed!r}, reason={reason!r}, "
            "retryable={retryable!r}, job={job!r}, "
            "retry_after={retry_after!r}, level={level!r})"
        ).format(
            allowed=self.allowed,
            reason=self.reason,
            retryable=self.retryable,
            job=self.job,
            retry_after=self.retry_after,
            level=self.level,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PermitDecision):
            return NotImplemented
        return (
            self.allowed == other.allowed
            and self.reason == other.reason
            and self.retryable == other.retryable
            and self.job == other.job
            and self.retry_after == other.retry_after
            and self.level == other.level
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.allowed,
                self.reason,
                self.retryable,
                self.job,
                self.retry_after,
                self.level,
            )
        )


class PermitEvaluator(Protocol):
    def __call__(self, platform: str, channel: Optional[str], job: str) -> PermitDecisionLike:
        ...


@dataclass
class _SendRequest:
    text: str
    job: str
    platform: str
    channel: Optional[str]
    correlation_id: str
    engagement_score: Optional[float] = None
    engagement_recent: Optional[float] = None
    engagement_long_term: Optional[float] = None
    engagement_permit_quota: Optional[float] = None


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
        self._metrics: MetricsRecorder = boundary.recorder
        self._metrics_service = boundary.service
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
        def _maybe_float(value: object) -> Optional[float]:
            if isinstance(value, (int, float)):
                return float(value)
            return None

        engagement_score = _maybe_float(getattr(text, "engagement_score", None))
        engagement_recent = _maybe_float(getattr(text, "engagement_recent", None))
        engagement_long_term = _maybe_float(
            getattr(text, "engagement_long_term", None)
        )
        engagement_permit_quota = _maybe_float(
            getattr(text, "engagement_permit_quota", None)
        )
        request = _SendRequest(
            text=str(text),
            job=job,
            platform=platform,
            channel=channel,
            correlation_id=corr,
            engagement_score=engagement_score,
            engagement_recent=engagement_recent,
            engagement_long_term=engagement_long_term,
            engagement_permit_quota=engagement_permit_quota,
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
        await processor.process(
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
        processor.record_event(
            boundary=self._metrics_boundary,
            name=name,
            tags=tags,
            measurements=measurements,
            metadata=metadata,
            force=force,
        )


__all__ = [
    "Orchestrator",
    "PermitDecision",
    "PermitDecisionLike",
    "PermitEvaluator",
    "Sender",
    "_SendRequest",
]
