from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Optional, Protocol

from .cooldown import CooldownGate
from .dedupe import NearDuplicateFilter
from ..infra import MetricsBackend, collect_weekly_snapshot
from ..infra import metrics as metrics_module
from .orchestrator_metrics import (
    MetricsRecorder,
    NullMetricsRecorder,
    format_metric_value,
    resolve_metrics_boundary,
)

if TYPE_CHECKING:
    from ..infra.metrics import WeeklyMetricsSnapshot
    from .orchestrator_metrics import MetricsBoundary


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


@dataclass(frozen=True)
class _PermitDecision:
    allowed: bool
    reason: Optional[str] = None
    retryable: bool = True
    job: Optional[str] = None

    @classmethod
    def allowed(cls, job: Optional[str] = None) -> "PermitDecisionLike":
        return cls(True, None, True, job)

    @classmethod
    def allow(cls, job: Optional[str] = None) -> "PermitDecisionLike":
        return cls.allowed(job)


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
        decision = self._permit(request.platform, request.channel, request.job)
        job_name = decision.job or request.job
        tags = {
            "job": job_name,
            "platform": request.platform,
            "channel": request.channel or "-",
        }
        boundary = self._metrics_boundary
        metrics_enabled = boundary.is_enabled()

        if not decision.allowed:
            retryable_flag = "true" if decision.retryable else "false"
            denied_tags = {**tags, "retryable": retryable_flag}
            reason = decision.reason or "unknown"
            if metrics_enabled:
                with boundary.suppress_backend(False):
                    metrics_module.report_permit_denied(
                        job=job_name,
                        platform=request.platform,
                        channel=request.channel,
                        reason=reason,
                        permit_tags={"retryable": retryable_flag},
                    )
            denied_metadata = {
                "correlation_id": request.correlation_id,
                "reason": decision.reason,
                "retryable": decision.retryable,
            }
            self._record_event("send.denied", denied_tags, metadata=denied_metadata)
            self._logger.info(
                "permit_denied",
                extra={
                    "event": "send_permit_denied",
                    "correlation_id": request.correlation_id,
                    "job": job_name,
                    "platform": request.platform,
                    "channel": request.channel,
                    "reason": decision.reason,
                    "retryable": decision.retryable,
                },
            )
            return

        if not self._dedupe.permit(request.text):
            duplicate_tags = {**tags, "status": "duplicate", "retryable": "false"}
            self._metrics.increment("send.duplicate", duplicate_tags)
            metadata = {
                "correlation_id": request.correlation_id,
                "status": "duplicate",
                "retryable": False,
            }
            self._record_event("send.duplicate", duplicate_tags, metadata=metadata)
            self._logger.info(
                "duplicate_skipped",
                extra={
                    "event": "send_duplicate_skip",
                    "correlation_id": request.correlation_id,
                    "job": job_name,
                    "platform": request.platform,
                    "channel": request.channel,
                    "status": "duplicate",
                    "retryable": False,
                },
            )
            return

        start = time.perf_counter()
        try:
            await self._sender.send(request.text, request.channel, job=job_name)
        except TypeError as exc:
            message = str(exc)
            if "unexpected keyword argument" not in message or "job" not in message:
                raise
            await self._sender.send(request.text, request.channel)
        except Exception as exc:  # noqa: BLE001 - 上位での再送制御対象
            duration = time.perf_counter() - start
            error_type = exc.__class__.__name__
            failure_tags = {**tags, "error": error_type}
            if metrics_enabled:
                with boundary.suppress_backend(True):
                    await metrics_module.report_send_failure(
                        job=job_name,
                        platform=request.platform,
                        channel=request.channel,
                        duration_seconds=duration,
                        error_type=error_type,
                    )
            self._metrics.observe("send.duration", duration, {**tags, "unit": "seconds"})
            self._metrics.increment("send.failure", failure_tags)
            failure_metadata = {
                "correlation_id": request.correlation_id,
                "error_type": error_type,
                "error_message": str(exc),
                "duration_sec": duration,
            }
            event_tags = {**failure_tags, "unit": "seconds"}
            self._record_event(
                "send.failure",
                event_tags,
                measurements={"duration_sec": duration},
                metadata=failure_metadata,
                force=True,
            )
            self._logger.error(
                "send_failed",
                extra={
                    "event": "send_failure",
                    "correlation_id": request.correlation_id,
                    "job": job_name,
                    "platform": request.platform,
                    "channel": request.channel,
                    "error_type": error_type,
                    "error_message": str(exc),
                    "duration_sec": duration,
                },
            )
            return

        duration = time.perf_counter() - start
        success_tags = dict(tags)
        log_extra = {
            "event": "send_success",
            "correlation_id": request.correlation_id,
            "job": job_name,
            "platform": request.platform,
            "channel": request.channel,
            "duration_sec": duration,
        }
        permit_tags: dict[str, str] | None = None
        if request.engagement_score is not None:
            formatted_score = format_metric_value(request.engagement_score)
            success_tags["engagement_score"] = formatted_score
            log_extra["engagement_score"] = request.engagement_score
            permit_tags = {"engagement_score": formatted_score}
        if metrics_enabled:
            with boundary.suppress_backend(False):
                await metrics_module.report_send_success(
                    job=job_name,
                    platform=request.platform,
                    channel=request.channel,
                    duration_seconds=duration,
                    permit_tags=permit_tags,
                )
        metadata = {"correlation_id": request.correlation_id}
        if request.engagement_score is not None:
            metadata["engagement_score"] = request.engagement_score
        self._record_event(
            "send.success",
            success_tags,
            measurements={"duration_sec": duration},
            metadata=metadata,
        )
        self._cooldown.note_post(request.platform, request.channel or "-", job_name)
        self._logger.info(
            "send_success",
            extra=log_extra,
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
        self._metrics_boundary.record_event(
            name,
            tags,
            measurements=measurements,
            metadata=metadata,
            force=force,
        )
