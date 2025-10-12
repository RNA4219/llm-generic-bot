from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class DigestLogEntry:
    timestamp: datetime
    level: str
    message: str


class LogCollector(Protocol):
    async def collect(self, channel: str, *, limit: int) -> Sequence[DigestLogEntry]: ...


class SummaryProvider(Protocol):
    async def summarize(self, text: str, *, max_events: int | None = None) -> str: ...


class DMSender(Protocol):
    async def send(
        self,
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
        recipient_id: str | None = None,
    ) -> None: ...


class PermitDecisionLike(Protocol):
    allowed: bool
    retryable: bool
    job: str | None


class PermitEvaluator(Protocol):
    def __call__(self, platform: str, channel: str | None, job: str) -> PermitDecisionLike: ...


async def build_dm_digest(
    cfg: Mapping[str, object],
    *,
    log_provider: LogCollector,
    summarizer: SummaryProvider,
    sender: DMSender,
    permit: PermitEvaluator,
    logger: logging.Logger | None = None,
    correlation_id: str | None = None,
) -> str | None:
    logger = logger or logging.getLogger(__name__)
    source_channel = _require_str(cfg, "source_channel")
    recipient_id = _require_str(cfg, "recipient_id")
    job = str(cfg.get("job", "dm_digest"))
    header = _optional_str(cfg.get("header"), default="Daily Digest")
    max_events = _positive_int(cfg.get("max_events"), default=50)

    entries = list(await log_provider.collect(source_channel, limit=max_events))
    if not entries:
        logger.info(
            "dm_digest_skip_empty",
            extra={"event": "dm_digest_skip_empty", "job": job, "source": source_channel, "recipient": recipient_id},
        )
        return None

    summary_input = "\n".join(_format_entry(entry) for entry in entries)
    summary_text = await summarizer.summarize(summary_input, max_events=max_events)

    decision = permit("discord_dm", recipient_id, job)
    if not decision.allowed:
        logger.info(
            "dm_digest_permit_denied",
            extra={
                "event": "dm_digest_permit_denied",
                "job": decision.job or job,
                "recipient": recipient_id,
                "retryable": decision.retryable,
            },
        )
        return None
    job_name = decision.job or job

    body = f"{header}\n{summary_text}" if header else summary_text
    max_attempts = _positive_int(cfg.get("max_attempts"), default=2)

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await sender.send(
                body,
                None,
                correlation_id=correlation_id,
                job=job_name,
                recipient_id=recipient_id,
            )
            logger.info(
                "dm_digest_sent",
                extra={"event": "dm_digest_sent", "job": job_name, "recipient": recipient_id, "attempt": attempt},
            )
            return body
        except Exception as exc:  # noqa: BLE001 - 呼び出し側で制御
            last_error = exc
            if attempt >= max_attempts:
                break
            logger.warning(
                "dm_digest_retry",
                extra={"event": "dm_digest_retry", "job": job_name, "recipient": recipient_id, "attempt": attempt},
            )
    assert last_error is not None
    logger.error(
        "dm_digest_failed",
        extra={
            "event": "dm_digest_failed",
            "job": job_name,
            "recipient": recipient_id,
            "attempt": attempt,
            "error": f"{last_error.__class__.__name__}: {last_error}",
        },
    )
    raise last_error


def _require_str(cfg: Mapping[str, object], key: str) -> str:
    value = cfg.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_str(value: object, *, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        candidate = int(value)
    elif isinstance(value, (int, float)):
        candidate = int(value)
    else:
        candidate = default
    return candidate if candidate > 0 else default


def _format_entry(entry: DigestLogEntry) -> str:
    return f"{_format_timestamp(entry.timestamp)} [{entry.level}] {entry.message}"


def _format_timestamp(dt: datetime) -> str:
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return aware.strftime("%Y-%m-%d %H:%M")
