from __future__ import annotations
from typing import Dict, Any, List, Optional, Callable, Awaitable, Mapping
import time, json, os, inspect
from dataclasses import dataclass
from pathlib import Path
from ..adapters.openweather import fetch_current_city
from ..core.cooldown import CooldownGate

CACHE = Path("weather_cache.json")

def _read_cache() -> Dict[str, Any]:
    if not CACHE.exists(): return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_cache(data: Dict[str, Any]) -> None:
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

EngagementProvider = Callable[[str, Optional[str], str], Awaitable[float] | float]


@dataclass(frozen=True)
class WeatherPostResult:
    text: str
    engagement_score: float


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    return {}


async def _resolve_engagement(
    cfg: Dict[str, Any],
    provider: Optional[EngagementProvider],
    platform: str,
    channel: Optional[str],
    job: str,
) -> float:
    value: Any
    if provider is not None:
        result = provider(platform, channel, job)
        value = await result if inspect.isawaitable(result) else result
    else:
        weather_cfg = _as_mapping(cfg.get("weather"))
        engagement_cfg = weather_cfg.get("engagement_recent")
        if engagement_cfg is None:
            engagement_cfg = _as_mapping(cfg.get("engagement")).get("recent")
        value = engagement_cfg
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 1.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


async def build_weather_post(
    cfg: Dict[str, Any],
    *,
    cooldown: Optional[CooldownGate] = None,
    platform: str = "-",
    channel: Optional[str] = None,
    job: str = "weather",
    engagement_provider: Optional[EngagementProvider] = None,
) -> WeatherPostResult | str | None:
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

    units = ow.get("units","metric")
    lang = ow.get("lang","ja")
    api_key = os.getenv("OPENWEATHER_API_KEY","")

    cities_by_region: Dict[str, List[str]] = wc.get("cities", {})
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
                desc = (raw.get("weather") or [{}])[0].get("description","")
                # hot icon
                hot_icon = ""
                if temp > hot35: hot_icon = icons.get("hot_35","🔥")
                elif temp > hot30: hot_icon = icons.get("hot_30","🌡️")
                # delta
                delta_tag = ""
                delta_warned = False
                y = (yesterday or {}).get(city)
                if y is not None and "temp" in y:
                    delta = temp - float(y["temp"])
                    if abs(delta) >= dstrong:
                        delta_tag = f"{icons.get('warn','⚠️')} " + (icons.get('delta_up','🔺') if delta>0 else icons.get('delta_down','🔻')) + f"({delta:+.1f})"
                        warns.append(f"• {city}: 前日比 {delta:+.1f}℃（強）")
                        delta_warned = True
                    elif abs(delta) >= dwarn:
                        delta_tag = (icons.get('delta_up','🔺') if delta>0 else icons.get('delta_down','🔻')) + f"({delta:+.1f})"
                        warns.append(f"• {city}: 前日比 {delta:+.1f}℃")
                        delta_warned = True
                out_lines.append(linefmt.format(city=city, temp=temp, desc=desc, hot_icon=hot_icon, delta_tag=delta_tag))
                now_snap[city] = {"temp": temp, "ts": int(time.time())}
            except Exception:
                out_lines.append(f"{city}: (cache)")
                # keep previous
        out_lines.append("")

    # footer warns
    if warns:
        out_lines.append(footer_warn.replace("{bullets}", "\n".join(warns)))

    # rotate cache
    new_cache = {"today": now_snap, "yesterday": previous_today}
    _write_cache(new_cache)
    text = "\n".join(out_lines).strip()

    engagement_score = await _resolve_engagement(
        cfg, engagement_provider, platform, channel, job
    )

    cooldown_cfg = wc.get("cooldown", {})
    suppress_threshold_raw = cooldown_cfg.get("suppress_threshold")
    time_band_factor_raw = cooldown_cfg.get("time_band_factor")
    try:
        suppress_threshold = float(suppress_threshold_raw)
    except (TypeError, ValueError):
        suppress_threshold = 1.5
    try:
        time_band_factor = float(time_band_factor_raw)
    except (TypeError, ValueError):
        time_band_factor = 1.0

    if cooldown is not None:
        multiplier = cooldown.multiplier(
            platform,
            (channel or "-"),
            job,
            time_band_factor=time_band_factor,
            engagement_recent=engagement_score,
        )
        if multiplier >= suppress_threshold:
            return None

    weather_cfg = _as_mapping(cfg.get("weather"))
    engagement_cfg = _as_mapping(cfg.get("engagement"))
    if (
        cooldown is None
        and engagement_provider is None
        and weather_cfg.get("engagement_recent") is None
        and engagement_cfg.get("recent") is None
    ):
        return text

    return WeatherPostResult(text=text, engagement_score=engagement_score)
