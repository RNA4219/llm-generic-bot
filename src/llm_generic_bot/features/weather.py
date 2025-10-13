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
    ) -> Sequence[int]:
        ...


class WeatherPost(str):
    engagement_score: float

    def __new__(cls, text: str, *, engagement_score: float) -> "WeatherPost":
        obj = cast("WeatherPost", super().__new__(cls, text))
        obj.engagement_score = engagement_score
        return obj

CACHE = Path("weather_cache.json")

def _read_cache() -> Dict[str, Any]:
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_cache(data: Dict[str, Any]) -> None:
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, bytes):
        try:
            return float(value.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
    return None


def _coerce_positive_int(value: Any, *, default: int, minimum: int = 1) -> int:
    candidate = _coerce_float(value)
    if candidate is None:
        return max(minimum, default)
    integer = int(candidate)
    if integer < minimum:
        return minimum
    return integer

async def build_weather_post(
    cfg: Dict[str, Any],
    *,
    cooldown: Optional[CooldownGate] = None,
    reaction_history_provider: Optional[ReactionHistoryProvider] = None,
    platform: Optional[str] = None,
    channel: Optional[str] = None,
    job: str = "weather",
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
    history_limit = _coerce_positive_int(
        engagement_cfg.get("history_limit"), default=5, minimum=1
    )
    target_raw = _coerce_float(engagement_cfg.get("target_reactions"))
    if target_raw is None:
        target_reactions = 5.0
    elif target_raw <= 0:
        target_reactions = 1.0
    else:
        target_reactions = target_raw
    min_raw = _coerce_float(engagement_cfg.get("min_score"))
    min_score = min_raw if min_raw is not None else 0.0
    resume_raw = _coerce_float(engagement_cfg.get("resume_score"))
    resume_score = resume_raw if resume_raw is not None else min_score
    if resume_score < min_score:
        resume_score = min_score
    tbf_raw = _coerce_float(engagement_cfg.get("time_band_factor"))
    time_band_factor = tbf_raw if tbf_raw is not None else 1.0

    engagement_score = 1.0
    if reaction_history_provider is not None:
        history = await reaction_history_provider(
            job=job,
            limit=history_limit,
            platform=platform,
            channel=channel,
        )
        recent = list(history)[-history_limit:]
        valid_reactions: List[float] = []
        for value in recent:
            coerced = _coerce_float(value)
            if coerced is not None:
                valid_reactions.append(coerced)
        if valid_reactions:
            total = sum(valid_reactions)
            average = total / len(valid_reactions)
            normalized = average / target_reactions if target_reactions > 0 else average
            engagement_score = max(0.0, min(1.0, normalized))
        else:
            engagement_score = 0.0

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
    previous_today_source = cache.get("today", {}) or {}
    if isinstance(previous_today_source, dict):
        previous_today: Dict[str, Dict[str, Any]] = {
            city: dict(snapshot)
            for city, snapshot in previous_today_source.items()
            if isinstance(snapshot, dict)
        }
    else:
        previous_today = {}
    yesterday_source = cache.get("yesterday", {}) or {}
    if previous_today:
        yesterday: Dict[str, Dict[str, Any]] = previous_today
    elif isinstance(yesterday_source, dict):
        yesterday = {
            city: dict(snapshot)
            for city, snapshot in yesterday_source.items()
            if isinstance(snapshot, dict)
        }
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
                if not isinstance(raw, Mapping):
                    raise TypeError("unexpected weather payload")
                main_data = raw.get("main")
                temp_value: Any = None
                if isinstance(main_data, Mapping):
                    temp_value = main_data.get("temp")
                temp = _coerce_float(temp_value)
                if temp is None:
                    raise ValueError("temperature missing")
                weather_items = raw.get("weather")
                desc = ""
                if isinstance(weather_items, Sequence):
                    for item in weather_items:
                        if isinstance(item, Mapping):
                            desc_value = item.get("description")
                            if isinstance(desc_value, str):
                                desc = desc_value
                                break
                hot_icon = ""
                if temp > hot35:
                    hot_icon = icons.get("hot_35", "🔥")
                elif temp > hot30:
                    hot_icon = icons.get("hot_30", "🌡️")
                delta_tag = ""
                y = (yesterday or {}).get(city)
                delta_source: Optional[float] = None
                if isinstance(y, Mapping):
                    delta_source = _coerce_float(y.get("temp"))
                if delta_source is not None:
                    delta = temp - delta_source
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
                now_snap[city] = {"temp": temp, "ts": int(time.time())}
            except Exception:
                out_lines.append(f"{city}: (cache)")
        out_lines.append("")

    if warns:
        out_lines.append(footer_warn.replace("{bullets}", "\n".join(warns)))

    new_cache = {"today": now_snap, "yesterday": previous_today}
    _write_cache(new_cache)
    text = "\n".join(out_lines).strip()
    return WeatherPost(text, engagement_score=engagement_score)
