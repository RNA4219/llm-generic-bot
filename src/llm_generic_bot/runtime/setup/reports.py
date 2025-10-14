from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Optional

from ...core.orchestrator import Orchestrator
from ...core.scheduler import Scheduler
from ...features.report import ReportPayload, generate_weekly_summary
from .runtime_helpers import register_weekly_report_job
from .sender import PermitOverride


def register_weekly_report(
    *,
    config: Mapping[str, object],
    scheduler: Scheduler,
    orchestrator: Orchestrator,
    default_channel: Optional[str],
    platform: str,
    permit_overrides: dict[str, PermitOverride],
    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]],
    summary_factory: Callable[..., ReportPayload] = generate_weekly_summary,
) -> None:
    register_weekly_report_job(
        config=config,
        scheduler=scheduler,
        orchestrator=orchestrator,
        default_channel=default_channel,
        platform=platform,
        permit_overrides=permit_overrides,
        jobs=jobs,
        summary_factory=summary_factory,
    )
