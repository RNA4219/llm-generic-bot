from __future__ import annotations

# LEGACY_SETUP_CHECKLIST
# - [x] プロファイル別の送信者解決をコンフィグ駆動へ移行
#   削除プロセス: runtime/setup/runtime_helpers.resolve_sender を設定サービスへ昇格させた後、setup/__init__.py からの委譲を削除
# - [x] ジョブ登録ロジックを宣言的なテーブル定義へ移設
#   削除プロセス: runtime/setup/runtime_helpers.register_weekly_report_job を宣言的スケジュール層へ移し、setup/__init__.py の呼び出しを整理
# - [x] クールダウン/デデュープ構築の分離
# - [x] 送信ラッパの分離
# - [x] ジョブ登録処理の分離
# - [x] 週次レポート登録処理の分離

from collections.abc import Iterable, Sequence
from functools import wraps
from typing import Any, Awaitable, Callable, Mapping, Optional

from ...config.quotas import QuotaSettings, load_quota_settings
from ...core.arbiter import PermitGate
from ...core.orchestrator import Orchestrator, PermitEvaluator, Sender
from ...core.queue import CoalesceQueue
from ...core.scheduler import Scheduler
from ...features.dm_digest import build_dm_digest
from ...features.news import build_news_post
from ...features.omikuji import build_omikuji_post
from ...features.report import WeeklyReportTemplate, generate_weekly_summary
from ...features.weather import build_weather_post
from ...infra import metrics as metrics_module
from ...infra.metrics import MetricsService
from ..jobs import JobContext, ScheduledJob
from ..jobs.common import as_mapping, get_float, is_enabled, resolve_object
from ..jobs.dm_digest import build_dm_digest_jobs
from ..jobs.news import build_news_jobs
from ..jobs.omikuji import build_omikuji_jobs
from ..jobs.weather import build_weather_jobs
from .gates import build_cooldown, build_dedupe, build_permit
from .jobs import install_factories
from .reports import register_weekly_report
from .runtime_helpers import resolve_sender
from .sender import build_send_adapter

_resolve_object = resolve_object

__all__ = [
    "setup_runtime",
    "_resolve_object",
    "build_weather_post",
    "build_news_post",
    "build_dm_digest",
    "build_omikuji_post",
    "generate_weekly_summary",
    "WeeklyReportTemplate",
]


def _parse_positive_int_pair(raw: object, *, setting_name: str) -> tuple[int, int]:
    if isinstance(raw, Mapping):
        raise ValueError(f"{setting_name} must be a sequence of two positive integers")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(f"{setting_name} must be a sequence of two positive integers")

    values = list(raw)
    if len(values) != 2:
        raise ValueError(f"{setting_name} must contain exactly two positive integers")

    parsed: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{setting_name} values must be positive integers")
        if value <= 0:
            raise ValueError(f"{setting_name} values must be positive integers")
        parsed.append(value)

    lower, upper = parsed
    if lower > upper:
        raise ValueError(
            f"{setting_name} lower bound {lower} must not exceed upper bound {upper}"
        )

    return lower, upper


def setup_runtime(
    settings: Mapping[str, Any],
    *,
    sender: Optional[Sender] = None,
    queue: Optional[CoalesceQueue] = None,
    permit_gate: Optional[PermitGate] = None,
) -> tuple[Scheduler, Orchestrator, dict[str, Callable[[], Awaitable[Optional[str]]]]]:
    cfg = dict(settings)
    tz = str(cfg.get("timezone", "Asia/Tokyo"))

    cooldown_cfg = as_mapping(cfg.get("cooldown"))
    cooldown = build_cooldown(cooldown_cfg)
    dedupe_cfg = as_mapping(cfg.get("dedupe"))
    dedupe = build_dedupe(dedupe_cfg)

    jitter_range_override: Optional[tuple[int, int]] = None
    jitter_from_settings = False

    scheduler_cfg = as_mapping(cfg.get("scheduler"))
    queue_threshold_override: Optional[int] = None
    queue_window_override: Optional[float] = None
    if scheduler_cfg:
        jitter_values = scheduler_cfg.get("jitter_range_seconds")
        if jitter_values is not None:
            jitter_range_override = _parse_positive_int_pair(
                jitter_values, setting_name="scheduler.jitter_range_seconds"
            )
            jitter_from_settings = True
        queue_cfg = as_mapping(scheduler_cfg.get("queue"))
        if queue_cfg:
            threshold_value = queue_cfg.get("threshold")
            if threshold_value is not None:
                if isinstance(threshold_value, bool) or not isinstance(threshold_value, int):
                    raise ValueError("scheduler.queue.threshold must be a positive integer")
                if threshold_value <= 0:
                    raise ValueError("scheduler.queue.threshold must be a positive integer")
                queue_threshold_override = threshold_value
            window_value = queue_cfg.get("window_sec")
            if window_value is not None:
                window_seconds = get_float(window_value, 180.0)
                if window_seconds < 0:
                    raise ValueError("scheduler.queue.window_sec must be non-negative")
                queue_window_override = window_seconds

    if not jitter_from_settings:
        arbiter_cfg = as_mapping(cfg.get("arbiter"))
        if arbiter_cfg:
            jitter_values = arbiter_cfg.get("jitter_sec")
            if jitter_values is not None:
                jitter_range_override = _parse_positive_int_pair(
                    jitter_values, setting_name="arbiter.jitter_sec"
                )

    quota: QuotaSettings = load_quota_settings(cfg)
    permit = build_permit(quota, permit_gate=permit_gate)

    profiles = as_mapping(cfg.get("profiles"))
    discord_cfg = as_mapping(profiles.get("discord"))
    misskey_cfg = as_mapping(profiles.get("misskey"))
    discord_enabled = is_enabled(discord_cfg, default=False)
    misskey_enabled = is_enabled(misskey_cfg, default=False)
    if not discord_enabled and not misskey_enabled:
        raise ValueError("no sending profiles enabled")

    platform, default_channel, active_sender = resolve_sender(
        profiles,
        sender=sender,
    )

    metrics_cfg = as_mapping(cfg.get("metrics"))
    metrics_enabled = is_enabled(metrics_cfg, default=True)
    metrics_service: Optional[MetricsService] = None
    metrics_module.set_retention_days(None)
    if not metrics_enabled:
        metrics_module.clear_history()
        metrics_module.configure_backend(None)
    else:
        backend_raw = metrics_cfg.get("backend", "memory")
        backend_name = str(backend_raw).strip()
        backend_normalized = backend_name.lower()
        if backend_normalized != "memory" or backend_name != "memory":
            raise ValueError(f"unsupported metrics backend: {backend_raw!r}")
        retention_days = None
        retention_value = metrics_cfg.get("retention_days")
        if retention_value is not None:
            retention_candidate = int(get_float(retention_value, 7.0))
            retention_days = max(1, retention_candidate)
        if retention_days is not None:
            metrics_module.set_retention_days(retention_days)
            metrics_service = MetricsService(retention_days=retention_days)
        else:
            metrics_service = MetricsService()

    orchestrator = Orchestrator(
        sender=active_sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics_service,
        platform=platform,
    )

    scheduler_sender, permit_overrides = build_send_adapter(
        orchestrator=orchestrator,
        platform=platform,
        default_channel=default_channel,
    )

    @wraps(build_weather_post)
    async def _call_weather_post(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_weather_post(*args, **kwargs)

    @wraps(build_news_post)
    async def _call_news_post(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_news_post(*args, **kwargs)

    @wraps(build_omikuji_post)
    async def _call_omikuji_post(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_omikuji_post(*args, **kwargs)

    @wraps(build_dm_digest)
    async def _call_dm_digest(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_dm_digest(*args, **kwargs)

    scheduler_kwargs: dict[str, Any] = {}
    if jitter_range_override is not None:
        scheduler_kwargs["jitter_range"] = jitter_range_override
        scheduler_kwargs["jitter_range_overridden"] = jitter_from_settings

    scheduler_queue = queue
    if scheduler_queue is None:
        window_seconds = queue_window_override if queue_window_override is not None else 180.0
        threshold_value = queue_threshold_override if queue_threshold_override is not None else 3
        scheduler_queue = CoalesceQueue(window_seconds=window_seconds, threshold=threshold_value)
    elif queue_threshold_override is not None or queue_window_override is not None:
        scheduler_queue = queue

    scheduler = Scheduler(
        tz=tz,
        sender=scheduler_sender,
        queue=scheduler_queue,
        **scheduler_kwargs,
    )

    context = JobContext(
        settings=cfg,
        scheduler=scheduler,
        platform=platform,
        default_channel=default_channel,
        cooldown=cooldown,
        permit=permit,
        build_weather_post=_call_weather_post,
        build_news_post=_call_news_post,
        build_omikuji_post=_call_omikuji_post,
        build_dm_digest=_call_dm_digest,
    )

    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]] = {}
    factories: tuple[
        Callable[[JobContext], Iterable[ScheduledJob]],
        ...,
    ] = (
        build_weather_jobs,
        build_news_jobs,
        build_omikuji_jobs,
        build_dm_digest_jobs,
    )
    install_factories(scheduler, jobs, factories, context)

    report_cfg = as_mapping(cfg.get("report"))
    register_weekly_report(
        config=report_cfg,
        scheduler=scheduler,
        orchestrator=orchestrator,
        default_channel=default_channel,
        platform=platform,
        permit_overrides=permit_overrides,
        jobs=jobs,
        summary_factory=generate_weekly_summary,
    )

    return scheduler, orchestrator, jobs
