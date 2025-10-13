from __future__ import annotations

from .news import register_news_job
from .weather import register_weather_job

__all__ = ["register_weather_job", "register_news_job"]
