from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import NoReturn

import httpx


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    base_backoff: float = 1.0
    max_backoff: float = 8.0


def _structured_log(
    logger: logging.Logger,
    level: int,
    *,
    event: str,
    adapter: str,
    correlation_id: str,
    **extra: object,
) -> None:
    """Emit JSON logs with a stable schema for retry telemetry."""

    payload = {
        "event": event,
        "adapter": adapter,
        "correlation_id": correlation_id,
        **extra,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":")))


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        parsed = parsedate_to_datetime(value)
        if parsed is None:
            return None
        delta = (parsed - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)


def _backoff(attempt: int, config: RetryConfig) -> float:
    power = attempt - 1
    delay = config.base_backoff * (2**power)
    return min(delay, config.max_backoff)


def _propagate_failure(response: httpx.Response | None, error: httpx.RequestError | None) -> NoReturn:
    if response is not None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - propagated
            raise exc
        raise httpx.HTTPStatusError(
            "request failed",
            request=response.request,
            response=response,
        )

    assert error is not None
    raise error


async def run_with_retry(
    *,
    adapter: str,
    correlation_id: str,
    target: str,
    attempt: Callable[[], Awaitable[httpx.Response]],
    retry_config: RetryConfig,
    logger: logging.Logger,
) -> httpx.Response:
    response: httpx.Response | None = None
    error: httpx.RequestError | None = None

    for current_attempt in range(1, retry_config.max_attempts + 1):
        response = None
        error = None
        try:
            response = await attempt()
        except httpx.TimeoutException as exc:
            error = exc
            retryable = True
            status_code = None
        except httpx.RequestError as exc:
            error = exc
            retryable = True
            status_code = None
        else:
            status_code = response.status_code
            retryable = status_code == 429 or 500 <= status_code < 600
            if 200 <= status_code < 300:
                _structured_log(
                    logger,
                    logging.INFO,
                    event="send_success",
                    adapter=adapter,
                    correlation_id=correlation_id,
                    attempt=current_attempt,
                    max_attempts=retry_config.max_attempts,
                    status_code=status_code,
                    target=target,
                )
                return response
            error = None

        if not retryable:
            _structured_log(
                logger,
                logging.ERROR,
                event="send_failed",
                adapter=adapter,
                correlation_id=correlation_id,
                attempt=current_attempt,
                max_attempts=retry_config.max_attempts,
                status_code=status_code,
                target=target,
            )
            _propagate_failure(response, error)

        if current_attempt == retry_config.max_attempts:
            _structured_log(
                logger,
                logging.ERROR,
                event="retry_exhausted",
                adapter=adapter,
                correlation_id=correlation_id,
                attempt=current_attempt,
                max_attempts=retry_config.max_attempts,
                status_code=status_code,
                target=target,
                error=str(error) if error is not None else None,
            )
            _propagate_failure(response, error)

        retry_in = None
        if status_code == 429 and response is not None:
            retry_in = _retry_after_seconds(response.headers.get("Retry-After"))
        if retry_in is None:
            retry_in = _backoff(current_attempt, retry_config)

        _structured_log(
            logger,
            logging.WARNING,
            event="retry_scheduled",
            adapter=adapter,
            correlation_id=correlation_id,
            attempt=current_attempt,
            max_attempts=retry_config.max_attempts,
            status_code=status_code,
            target=target,
            retry_in=retry_in,
            error=str(error) if error is not None else None,
        )
        await asyncio.sleep(retry_in)

    raise RuntimeError("retry loop exited unexpectedly")

