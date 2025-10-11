from __future__ import annotations
import os, httpx

async def fetch_current_city(city: str, api_key: str | None = None, units: str="metric", lang: str="ja") -> dict:
    api_key = api_key or os.getenv("OPENWEATHER_API_KEY","")
    if not api_key: raise RuntimeError("OPENWEATHER_API_KEY missing")
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": api_key, "units": units, "lang": lang}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()
