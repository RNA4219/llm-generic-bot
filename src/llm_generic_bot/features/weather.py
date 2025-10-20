from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, cast
import json
import os
import time
from pathlib import Path

from ..adapters.openweather import fetch_current_city
from ..core.cooldown import CooldownGate


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

CACHE = Path("weather_cache.json")


def _coerce_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _read_cache() -> Dict[str, Any]:
    if not CACHE.exists(): return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_cache(data: Dict[str, Any]) -> None:
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_history(
    history: Sequence[object],
    *,
    recent_limit: int,
    long_term_limit: int,
) -> tuple[List[float], List[float]]:
    def _coerce_sequence(items: Sequence[object]) -> List[float]:
        values: List[float] = []
        for item in items[: max(recent_limit, long_term_limit)]:
            coerced = _coerce_float(item)
            if coerced is not None:
                values.append(coerced)
        return values

    nested: List[Sequence[object]] = []
    for item in history:
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            nested.append(cast(Sequence[object], item))
    if nested:
        recent_source = nested[0]
        long_term_source = nested[1] if len(nested) > 1 else nested[0]
        recent_values = _coerce_sequence(recent_source)[:recent_limit]
        long_term_values = _coerce_sequence(long_term_source)[:long_term_limit]
        return recent_values, long_term_values

    values = _coerce_sequence(history)
    return values[:recent_limit], values[:long_term_limit]


def _score_from_values(values: Sequence[float], *, target: float) -> float:
    if not values:
        return 0.0
    average = sum(values) / len(values)
    if target > 0:
        average = average / target
    return _clamp_unit_interval(average)


def _filter_cache_entries(
    source: Mapping[str, Dict[str, Any]],
    *,
    retention_seconds: float,
    now_ts: float,
) -> Dict[str, Dict[str, Any]]:
    kept: Dict[str, Dict[str, Any]] = {}
    for city, snapshot in source.items():
        if not isinstance(snapshot, dict):
            continue
        ts_value = _coerce_float(snapshot.get("ts"))
        if ts_value is None or now_ts - ts_value > retention_seconds:
            continue
        kept[city] = dict(snapshot)
    return kept


async def build_weather_post(
    cfg: Dict[str, Any],
    *,
    cooldown: Optional[CooldownGate] = None,
    reaction_history_provider: Optional[ReactionHistoryProvider] = None,
    platform: Optional[str] = None,
    channel: Optional[str] = None,
    job: str = "weather",
    permit_quota_ratio: Optional[float] = None,
) -> Optional[WeatherPost]:
    ow = cfg.get("openweather", {})
    wc = cfg.get("weather", {})
    thresholds = wc.get("thresholds", {})
    hot30 = thresholds.get("hot_30", 30.0)
    hot35 = thresholds.get("hot_35", 35.0)
    dwarn = thresholds.get("delta_warn", 7.0)
    dstrong = thresholds.get("delta_strong", 10.0)
    icons = wc.get("icons", {})
    tpl = wc.get("template", {})
    header = tpl.get("header", "今夜の各地の天気")
    linefmt = tpl.get("line", "{city}: {temp:.1f}℃ {desc} {hot_icon}{delta_tag}")
    footer_warn = tpl.get("footer_warn", "— 注意喚起 —\n{bullets}")

    units = ow.get("units", "metric")
    lang = ow.get("lang", "ja")
    api_key = os.getenv("OPENWEATHER_API_KEY", "")

    cities_by_region: Dict[str, List[str]] = wc.get("cities", {})

    engagement_raw = wc.get("engagement", {})
    engagement_cfg: Dict[str, Any] = engagement_raw if isinstance(engagement_raw, dict) else {}
    history_limit = int(engagement_cfg.get("history_limit", 5))
    if history_limit <= 0:
        history_limit = 1
    long_term_limit = int(engagement_cfg.get("long_term_history_limit", history_limit))
    if long_term_limit <= 0:
        long_term_limit = history_limit
    target_reactions = float(engagement_cfg.get("target_reactions", 5.0))
    if target_reactions <= 0:
        target_reactions = 1.0
    min_score = float(engagement_cfg.get("min_score", 0.0))
    resume_score = float(engagement_cfg.get("resume_score", min_score))
    if resume_score < min_score:
        resume_score = min_score
    time_band_factor = float(engagement_cfg.get("time_band_factor", 1.0))
    long_term_weight = _clamp_unit_interval(
        float(engagement_cfg.get("long_term_weight", 0.0))
    )
    permit_quota_weight = _clamp_unit_interval(
        float(engagement_cfg.get("permit_quota_weight", 0.0))
    )
    if permit_quota_ratio is None:
        permit_quota_ratio = _coerce_float(engagement_cfg.get("permit_quota_ratio"))
    permit_quota_clamped = (
        _clamp_unit_interval(permit_quota_ratio)
        if permit_quota_ratio is not None
        else None
    )

    engagement_recent_score = 1.0
    engagement_long_term_score = 1.0
    engagement_score = 1.0
    if reaction_history_provider is not None:
        history = await reaction_history_provider(
            job=job,
            limit=history_limit,
            platform=platform,
            channel=channel,
        )
        recent_values, long_term_values = _normalize_history(
            list(history),
            recent_limit=history_limit,
            long_term_limit=long_term_limit,
        )
        engagement_recent_score = _score_from_values(
            recent_values,
            target=target_reactions,
        )
        engagement_long_term_score = _score_from_values(
            long_term_values or recent_values,
            target=target_reactions,
        )
        if long_term_weight > 0.0:
            engagement_score = _clamp_unit_interval(
                engagement_recent_score * (1.0 - long_term_weight)
                + engagement_long_term_score * long_term_weight
            )
        else:
            engagement_score = engagement_recent_score

        if permit_quota_clamped is not None and permit_quota_weight > 0.0:
            engagement_score = _clamp_unit_interval(
                engagement_score * (1.0 - permit_quota_weight)
                + permit_quota_clamped * permit_quota_weight
            )

        multiplier = 1.0
        if cooldown is not None:
            multiplier = cooldown.multiplier(
                platform or "-",
                channel or "-",
                job,
                time_band_factor=time_band_factor,
                engagement_recent=engagement_score,
            )
        if engagement_score < resume_score:
            effective = engagement_score / multiplier if multiplier > 0 else engagement_score
            if effective < min_score:
                return None

    cache = _read_cache()
    now_ts = time.time()
    retention_hours = _coerce_float(wc.get("cache_retention_hours"))
    if retention_hours is None or retention_hours <= 0:
        retention_hours = 48.0
    retention_seconds = retention_hours * 3600.0
    previous_today_source = cache.get("today", {}) or {}
    if isinstance(previous_today_source, dict):
        previous_today = _filter_cache_entries(
            previous_today_source,
            retention_seconds=retention_seconds,
            now_ts=now_ts,
        )
    else:
        previous_today = {}
    yesterday_source = cache.get("yesterday", {}) or {}
    if previous_today:
        yesterday: Dict[str, Dict[str, Any]] = previous_today
    elif isinstance(yesterday_source, dict):
        yesterday = _filter_cache_entries(
            yesterday_source,
            retention_seconds=retention_seconds,
            now_ts=now_ts,
        )
    else:
        yesterday = {}
    now_snap: Dict[str, Dict[str, Any]] = {}

    out_lines = [header]
    warns: List[str] = []

    for region, cities in cities_by_region.items():
        out_lines.append(f"[{region}]")
        for city in cities:
            try:
                raw = await fetch_current_city(city, api_key=api_key, units=units, lang=lang)
                temp = float((raw.get("main") or {}).get("temp"))
                desc = (raw.get("weather") or [{}])[0].get("description", "")
                snapshot = {"temp": temp, "ts": int(time.time()), "desc": desc}
            except Exception:
                fallback_source = previous_today.get(city) or yesterday.get(city)
                if not (isinstance(fallback_source, dict) and "temp" in fallback_source):
                    out_lines.append(f"{city}: (cache)")
                    continue
                temp = float(fallback_source["temp"])
                desc = str(fallback_source.get("desc", ""))
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
            y = (yesterday or {}).get(city)
            if y is not None and "temp" in y:
                delta = temp - float(y["temp"])
                if abs(delta) >= dstrong:
                    delta_tag = (
                        f"{icons.get('warn','⚠️')} "
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

    new_cache = {"today": now_snap, "yesterday": _filter_cache_entries(previous_today, retention_seconds=retention_seconds, now_ts=now_ts)}
    _write_cache(new_cache)
    text = "\n".join(out_lines).strip()
    return WeatherPost(
        text,
        engagement_score=engagement_score,
        engagement_recent=engagement_recent_score,
        engagement_long_term=engagement_long_term_score,
        engagement_permit_quota=permit_quota_clamped,
    )
