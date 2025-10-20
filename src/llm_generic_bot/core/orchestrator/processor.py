from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Mapping, Optional, Protocol

from ..cooldown import CooldownGate
from ..dedupe import NearDuplicateFilter
from ..orchestrator_metrics import MetricsBoundary, MetricsRecorder, format_metric_value
from ..arbiter import (
    PermitReevaluationOutcome,
    reevaluation_allowed,
    reevaluation_level,
    reevaluation_reason,
    reevaluation_retry_after,
)
from ...infra import metrics as metrics_module

if TYPE_CHECKING:
    class PermitDecisionLike(Protocol):
        allowed: bool
        reason: Optional[str]
        retryable: bool
        job: Optional[str]
        reevaluation: PermitReevaluationOutcome | str | None

    class PermitEvaluator(Protocol):
        def __call__(
            self, platform: str, channel: Optional[str], job: str
        ) -> PermitDecisionLike:
            ...

    class Sender(Protocol):
        async def send(
            self,
            text: str,
            channel: Optional[str] = None,
            *,
            job: Optional[str] = None,
        ) -> None:
            ...


class SendRequest(Protocol):
    text: str
    job: str
    platform: str
    channel: Optional[str]
    correlation_id: str
    engagement_score: Optional[float]


class RecordEvent(Protocol):
    def __call__(
        self,
        name: str,
        tags: Mapping[str, str],
        *,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, object] | None = None,
        force: bool = False,
    ) -> None:
        ...


class ScheduleReevaluation(Protocol):
    async def __call__(self, request: SendRequest, *, retry_after: float) -> None:
        ...


async def process(
    *,
    request: SendRequest,
    sender: "Sender",
    cooldown: CooldownGate,
    dedupe: NearDuplicateFilter,
    permit: "PermitEvaluator",
    metrics_boundary: MetricsBoundary,
    metrics: MetricsRecorder,
    logger: logging.Logger,
    record_event: RecordEvent,
    schedule_reevaluation: ScheduleReevaluation,
) -> None:
    decision: "PermitDecisionLike" = permit(request.platform, request.channel, request.job)
    job_name = decision.job or request.job
    tags = {
        "job": job_name,
        "platform": request.platform,
        "channel": request.channel or "-",
    }
    metrics_enabled = metrics_boundary.is_enabled()

    if not decision.allowed:
        retryable_flag = "true" if decision.retryable else "false"
        denied_tags = {**tags, "retryable": retryable_flag}
        reason = decision.reason or "unknown"
        retry_after = reevaluation_retry_after(decision.reevaluation)
        reeval_level = reevaluation_level(decision.reevaluation)
        reeval_reason = reevaluation_reason(decision.reevaluation)
        allowed_hint = reevaluation_allowed(decision.reevaluation)
        permit_payload: dict[str, str] = {"retryable": retryable_flag}
        if reeval_level is not None:
            permit_payload["reevaluation_level"] = reeval_level
        if reeval_reason:
            permit_payload["reevaluation_reason"] = reeval_reason
        if retry_after is not None and retry_after >= 0.0:
            permit_payload["reevaluation_retry_after"] = format_metric_value(retry_after)
        if allowed_hint is not None:
            permit_payload["reevaluation_allowed"] = "true" if allowed_hint else "false"
        if metrics_enabled:
            with metrics_boundary.suppress_backend(False):
                metrics_module.report_permit_denied(
                    job=job_name,
                    platform=request.platform,
                    channel=request.channel,
                    reason=reason,
                    permit_tags=permit_payload,
                )
        denied_metadata = {
            "correlation_id": request.correlation_id,
            "reason": decision.reason,
            "retryable": decision.retryable,
        }
        record_event("send.denied", denied_tags, metadata=denied_metadata)
        logger.info(
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
        if retry_after is not None and retry_after >= 0.0:
            level = reeval_level or "unspecified"
            reeval_reason = reeval_reason or reason
            decision_label = (
                "allow" if allowed_hint is True else "deny" if allowed_hint is False else "pending"
            )
            reevaluation_tags = {**tags, "level": level, "decision": decision_label}
            if reeval_reason:
                reevaluation_tags["reason"] = reeval_reason
            reevaluation_tags["retry_after"] = format_metric_value(retry_after)
            metrics.increment("send.permit_reevaluation", reevaluation_tags)
            if metrics_enabled:
                with metrics_boundary.suppress_backend(False):
                    await metrics_module.report_permit_reevaluation(
                        job=job_name,
                        platform=request.platform,
                        channel=request.channel,
                        level=level,
                        reason=reeval_reason,
                        retry_after_seconds=retry_after,
                        decision=decision_label,
                    )
            metadata = {
                "correlation_id": request.correlation_id,
                "reason": reeval_reason,
                "retry_after": retry_after,
                "decision": decision_label,
            }
            record_event(
                "send.permit_reevaluation",
                reevaluation_tags,
                metadata=metadata,
                force=True,
            )
            logger.info(
                "permit_reevaluation_scheduled",
                extra={
                    "event": "send_permit_reevaluation",
                    "correlation_id": request.correlation_id,
                    "job": job_name,
                    "platform": request.platform,
                    "channel": request.channel,
                    "reason": reeval_reason,
                    "retry_after": retry_after,
                    "decision": decision_label,
                },
            )
            await schedule_reevaluation(request, retry_after=retry_after)
        return

    if not dedupe.permit(request.text):
        duplicate_tags = {**tags, "status": "duplicate", "retryable": "false"}
        metrics.increment("send.duplicate", duplicate_tags)
        metadata = {
            "correlation_id": request.correlation_id,
            "status": "duplicate",
            "retryable": False,
        }
        record_event("send.duplicate", duplicate_tags, metadata=metadata)
        logger.info(
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
        await sender.send(request.text, request.channel, job=job_name)
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument" not in message or "job" not in message:
            raise
        await sender.send(request.text, request.channel)
    except Exception as exc:  # noqa: BLE001 - 上位での再送制御対象
        duration = time.perf_counter() - start
        error_type = exc.__class__.__name__
        failure_tags = {**tags, "error": error_type}
        if metrics_enabled:
            with metrics_boundary.suppress_backend(True):
                await metrics_module.report_send_failure(
                    job=job_name,
                    platform=request.platform,
                    channel=request.channel,
                    duration_seconds=duration,
                    error_type=error_type,
                )
        metrics.observe("send.duration", duration, {**tags, "unit": "seconds"})
        metrics.increment("send.failure", failure_tags)
        failure_metadata = {
            "correlation_id": request.correlation_id,
            "error_type": error_type,
            "error_message": str(exc),
            "duration_sec": duration,
        }
        event_tags = {**failure_tags, "unit": "seconds"}
        record_event(
            "send.failure",
            event_tags,
            measurements={"duration_sec": duration},
            metadata=failure_metadata,
            force=True,
        )
        logger.error(
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
    log_extra: dict[str, object] = {
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
        with metrics_boundary.suppress_backend(False):
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
    record_event(
        "send.success",
        success_tags,
        measurements={"duration_sec": duration},
        metadata=metadata,
    )
    cooldown.note_post(request.platform, request.channel or "-", job_name)
    logger.info(
        "send_success",
        extra=log_extra,
    )


def record_event(
    *,
    boundary: MetricsBoundary,
    name: str,
    tags: Mapping[str, str],
    measurements: Mapping[str, float] | None = None,
    metadata: Mapping[str, object] | None = None,
    force: bool = False,
) -> None:
    boundary.record_event(
        name,
        tags,
        measurements=measurements,
        metadata=metadata,
        force=force,
    )
