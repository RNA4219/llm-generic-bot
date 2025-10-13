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
    history_limit = int(engagement_cfg.get("history_limit", 5))
    if history_limit <= 0:
        history_limit = 1
    target_reactions = float(engagement_cfg.get("target_reactions", 5.0))
    if target_reactions <= 0:
        target_reactions = 1.0
    min_score = float(engagement_cfg.get("min_score", 0.0))
    resume_score = float(engagement_cfg.get("resume_score", min_score))
    if resume_score < min_score:
        resume_score = min_score
    time_band_factor = float(engagement_cfg.get("time_band_factor", 1.0))

    engagement_score = 1.0
    if reaction_history_provider is not None:
        history = await reaction_history_provider(
            job=job,
            limit=history_limit,
            platform=platform,
            channel=channel,
        )
        recent = list(history)[-history_limit:]
        if recent:
            total = sum(float(value) for value in recent)
            average = total / len(recent)
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

    new_cache = {"today": now_snap, "yesterday": previous_today}
    _write_cache(new_cache)
    text = "\n".join(out_lines).strip()
    return WeatherPost(text, engagement_score=engagement_score)
