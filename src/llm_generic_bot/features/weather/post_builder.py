from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence, cast

from ...adapters.openweather import fetch_current_city
from ...core.cooldown import CooldownGate
from .cache import (
    CachePayload,
    CacheSnapshot,
    DEFAULT_CACHE_PATH,
    clamp_unit_interval,
    coerce_float,
    read_cache,
    resolve_snapshots,
    rotate_cache,
    write_cache,
)
from .engagement import EngagementResult, calculate_engagement


class ReactionHistoryProvider(Protocol):
    async def __call__(
        self,
        *,
        job: str,
        limit: int,
        platform: Optional[str],
        channel: Optional[str],
    ) -> Sequence[object]:
        ...


class WeatherPost(str):
    engagement_score: float
    engagement_recent: float
    engagement_long_term: float
    engagement_permit_quota: Optional[float]

    def __new__(
        cls,
        text: str,
        *,
        engagement_score: float,
        engagement_recent: Optional[float] = None,
        engagement_long_term: Optional[float] = None,
        engagement_permit_quota: Optional[float] = None,
    ) -> "WeatherPost":
        obj = cast("WeatherPost", super().__new__(cls, text))
        obj.engagement_score = engagement_score
        obj.engagement_recent = (
            engagement_recent if engagement_recent is not None else engagement_score
        )
        obj.engagement_long_term = (
            engagement_long_term
            if engagement_long_term is not None
            else obj.engagement_recent
        )
        obj.engagement_permit_quota = engagement_permit_quota
        return obj


async def build_weather_post(
    cfg: Mapping[str, Any],
    *,
    cooldown: Optional[CooldownGate] = None,
    reaction_history_provider: Optional[ReactionHistoryProvider] = None,
    platform: Optional[str] = None,
    channel: Optional[str] = None,
    job: str = "weather",
    permit_quota_ratio: Optional[float] = None,
    cache_path: Optional[str | os.PathLike[str]] = None,
) -> Optional[WeatherPost]:
    ow_cfg = cast(Mapping[str, Any], cfg.get("openweather", {}))
    weather_cfg = cast(Mapping[str, Any], cfg.get("weather", {}))
    thresholds = cast(Mapping[str, Any], weather_cfg.get("thresholds", {}))
    icons = cast(Mapping[str, str], weather_cfg.get("icons", {}))
    tpl = cast(Mapping[str, str], weather_cfg.get("template", {}))

    hot30 = float(thresholds.get("hot_30", 30.0))
    hot35 = float(thresholds.get("hot_35", 35.0))
    dwarn = float(thresholds.get("delta_warn", 7.0))
    dstrong = float(thresholds.get("delta_strong", 10.0))

    header = tpl.get("header", "今夜の各地の天気")
    linefmt = tpl.get("line", "{city}: {temp:.1f}℃ {desc} {hot_icon}{delta_tag}")
    footer_warn = tpl.get("footer_warn", "— 注意喚起 —\n{bullets}")

    units = str(ow_cfg.get("units", "metric"))
    lang = str(ow_cfg.get("lang", "ja"))
    api_key = os.getenv("OPENWEATHER_API_KEY", "")

    cities_by_region = cast(Mapping[str, Sequence[str]], weather_cfg.get("cities", {}))

    engagement_cfg = cast(Mapping[str, Any], weather_cfg.get("engagement", {}))
    history_limit = max(int(coerce_float(engagement_cfg.get("history_limit")) or 0), 1)
    long_term_limit = int(
        coerce_float(engagement_cfg.get("long_term_history_limit")) or history_limit
    )
    if long_term_limit <= 0:
        long_term_limit = history_limit
    target_reactions = coerce_float(engagement_cfg.get("target_reactions")) or 5.0
    if target_reactions <= 0:
        target_reactions = 1.0
    min_score = coerce_float(engagement_cfg.get("min_score")) or 0.0
    resume_score = coerce_float(engagement_cfg.get("resume_score")) or min_score
    if resume_score < min_score:
        resume_score = min_score
    time_band_factor = coerce_float(engagement_cfg.get("time_band_factor")) or 1.0
    long_term_weight = coerce_float(engagement_cfg.get("long_term_weight")) or 0.0
    permit_quota_weight = coerce_float(engagement_cfg.get("permit_quota_weight")) or 0.0

    permit_quota_source = (
        permit_quota_ratio
        if permit_quota_ratio is not None
        else coerce_float(engagement_cfg.get("permit_quota_ratio"))
    )

    engagement_result = EngagementResult(
        score=1.0,
        recent=1.0,
        long_term=1.0,
        permit_quota=(
            clamp_unit_interval(permit_quota_source)
            if permit_quota_source is not None
            else None
        ),
    )

    multiplier = 1.0
    if reaction_history_provider is not None:
        history = await reaction_history_provider(
            job=job,
            limit=history_limit,
            platform=platform,
            channel=channel,
        )
        engagement_result = calculate_engagement(
            list(history),
            history_limit=history_limit,
            long_term_limit=long_term_limit,
            target_reactions=target_reactions,
            long_term_weight=long_term_weight,
            permit_quota_weight=permit_quota_weight,
            permit_quota_ratio=permit_quota_source,
        )

        if cooldown is not None:
            multiplier = cooldown.multiplier(
                platform or "-",
                channel or "-",
                job,
                time_band_factor=time_band_factor,
                engagement_recent=engagement_result.score,
            )
        if engagement_result.score < resume_score:
            effective = (
                engagement_result.score / multiplier
                if multiplier > 0
                else engagement_result.score
            )
            if effective < min_score:
                return None

    cache_location = (
        DEFAULT_CACHE_PATH if cache_path is None else Path(cache_path)
    )
    cache_data: CachePayload = read_cache(cache_location)
    now_ts = time.time()
    retention_hours = coerce_float(weather_cfg.get("cache_retention_hours")) or 48.0
    retention_seconds = retention_hours * 3600.0

    previous_today, yesterday = resolve_snapshots(
        cache_data,
        retention_seconds=retention_seconds,
        now_ts=now_ts,
    )

    now_snap: CacheSnapshot = {}
    out_lines = [header]
    warns: list[str] = []

    for region, cities in cities_by_region.items():
        out_lines.append(f"[{region}]")
        for city in cities:
            snapshot: Dict[str, Any]
            try:
                raw = await fetch_current_city(
                    city,
                    api_key=api_key,
                    units=units,
                    lang=lang,
                )
                main_section = cast(Mapping[str, Any], raw.get("main") or {})
                temp_value = coerce_float(main_section.get("temp"))
                if temp_value is None:
                    raise ValueError("missing temperature")
                weather_section = cast(Sequence[Mapping[str, Any]], raw.get("weather") or ())
                first_weather = weather_section[0] if weather_section else {}
                desc = str(first_weather.get("description", ""))
                temp = temp_value
                snapshot = {"temp": temp, "ts": int(time.time()), "desc": desc}
            except Exception:
                fallback_source = previous_today.get(city) or yesterday.get(city)
                if not isinstance(fallback_source, Mapping):
                    out_lines.append(f"{city}: (cache)")
                    continue
                temp_fallback = coerce_float(fallback_source.get("temp"))
                if temp_fallback is None:
                    out_lines.append(f"{city}: (cache)")
                    continue
                desc = str(fallback_source.get("desc", ""))
                temp = temp_fallback
                snapshot = dict(fallback_source)
                snapshot["temp"] = temp
                snapshot.setdefault("ts", int(time.time()))
                snapshot["desc"] = desc
            hot_icon = ""
            if temp > hot35:
                hot_icon = icons.get("hot_35", "🔥")
            elif temp > hot30:
                hot_icon = icons.get("hot_30", "🌡️")
            delta_tag = ""
            previous = yesterday.get(city)
            delta: Optional[float] = None
            if previous is not None:
                prev_temp = coerce_float(previous.get("temp"))
                if prev_temp is not None:
                    delta = temp - prev_temp
            if delta is not None:
                if abs(delta) >= dstrong:
                    delta_tag = (
                        f"{icons.get('warn', '⚠️')} "
                        + (
                            icons.get("delta_up", "🔺")
                            if delta > 0
                            else icons.get("delta_down", "🔻")
                        )
                        + f"({delta:+.1f})"
                    )
                    warns.append(f"• {city}: 前日比 {delta:+.1f}℃（強）")
                elif abs(delta) >= dwarn:
                    delta_tag = (
                        icons.get("delta_up", "🔺")
                        if delta > 0
                        else icons.get("delta_down", "🔻")
                    ) + f"({delta:+.1f})"
                    warns.append(f"• {city}: 前日比 {delta:+.1f}℃")
            out_lines.append(
                linefmt.format(
                    city=city,
                    temp=temp,
                    desc=desc,
                    hot_icon=hot_icon,
                    delta_tag=delta_tag,
                )
            )
            now_snap[city] = snapshot
        out_lines.append("")

    if warns:
        out_lines.append(footer_warn.replace("{bullets}", "\n".join(warns)))

    new_cache = rotate_cache(
        today=now_snap,
        previous_today=previous_today,
        retention_seconds=retention_seconds,
        now_ts=now_ts,
    )
    write_cache(new_cache, cache_location)

    text = "\n".join(out_lines).strip()
    return WeatherPost(
        text,
        engagement_score=engagement_result.score,
        engagement_recent=engagement_result.recent,
        engagement_long_term=engagement_result.long_term,
        engagement_permit_quota=engagement_result.permit_quota,
    )


__all__ = [
    "ReactionHistoryProvider",
    "WeatherPost",
    "build_weather_post",
]
