from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol

from .cooldown import CooldownGate
from .dedupe import NearDuplicateFilter


class Sender(Protocol):
    async def send(self, text: str, channel: Optional[str] = None) -> None:
        ...


@dataclass(frozen=True)
class PermitDecision:
    allowed: bool
    reason: Optional[str] = None
    job: Optional[str] = None

    @classmethod
    def allowed(cls, job: Optional[str] = None) -> "PermitDecision":
        return cls(True, None, job)


class PermitEvaluator(Protocol):
    def __call__(self, platform: str, channel: Optional[str], job: str) -> PermitDecision:
        ...


class MetricsRecorder(Protocol):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        ...

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        ...


class NullMetricsRecorder:
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        return None

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        return None


@dataclass
class _SendRequest:
    text: str
    job: str
    platform: str
    channel: Optional[str]
    correlation_id: str


class Orchestrator:
    def __init__(
        self,
        *,
        sender: Sender,
        cooldown: CooldownGate,
        dedupe: NearDuplicateFilter,
        permit: PermitEvaluator,
        metrics: MetricsRecorder | None = None,
        logger: Optional[logging.Logger] = None,
        queue_size: int = 128,
    ) -> None:
        self._sender = sender
        self._cooldown = cooldown
        self._dedupe = dedupe
        self._permit = permit
        self._metrics = metrics or NullMetricsRecorder()
        self._logger = logger or logging.getLogger(__name__)
        self._queue: asyncio.Queue[_SendRequest | None] = asyncio.Queue(maxsize=queue_size)
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
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
        request = _SendRequest(
            text=text,
            job=job,
            platform=platform,
            channel=channel,
            correlation_id=corr,
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

    def _start_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

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
        if not decision.allowed:
            self._metrics.increment("send.denied", tags)
            self._logger.info(
                "permit_denied",
                extra={
                    "event": "send_permit_denied",
                    "correlation_id": request.correlation_id,
                    "job": job_name,
                    "platform": request.platform,
                    "channel": request.channel,
                    "reason": decision.reason,
                },
            )
            return

        if not self._dedupe.permit(request.text):
            self._metrics.increment("send.duplicate", tags)
            self._logger.info(
                "duplicate_skipped",
                extra={
                    "event": "send_duplicate_skip",
                    "correlation_id": request.correlation_id,
                    "job": job_name,
                    "platform": request.platform,
                    "channel": request.channel,
                },
            )
            return

        start = time.perf_counter()
        try:
            await self._sender.send(request.text, request.channel)
        except Exception as exc:  # noqa: BLE001 - 上位での再送制御対象
            self._metrics.increment("send.failure", tags)
            self._logger.error(
                "send_failed",
                extra={
                    "event": "send_failure",
                    "correlation_id": request.correlation_id,
                    "job": job_name,
                    "platform": request.platform,
                    "channel": request.channel,
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )
            return

        duration = time.perf_counter() - start
        self._metrics.increment("send.success", tags)
        self._metrics.observe("send.duration", duration, tags)
        self._cooldown.note_post(request.platform, request.channel or "-", job_name)
        self._logger.info(
            "send_success",
            extra={
                "event": "send_success",
                "correlation_id": request.correlation_id,
                "job": job_name,
                "platform": request.platform,
                "channel": request.channel,
                "duration_sec": duration,
            },
        )
