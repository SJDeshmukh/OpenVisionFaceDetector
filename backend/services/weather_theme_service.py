"""LLM-driven seasonal themes based on normal conditions across India.

This module deliberately does not call a weather-data service. It asks the
already configured XChat provider to select the most representative visual
theme from the Indian date, time and coarse coordinates. A deterministic
India-season fallback keeps this decorative feature available if AI is down.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import logging
import math
import os
import re
import threading
import time
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

ALLOWED_THEMES = frozenset({"summer", "rainy", "winter", "autumn", "snow"})
THEME_CONDITIONS = {
    "summer": "Typical hot-season conditions in India",
    "rainy": "Typical monsoon conditions in India",
    "winter": "Typical cool-season conditions in India",
    "autumn": "Typical mild post-monsoon conditions in India",
    "snow": "Typical Himalayan winter conditions in India",
}
INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")

_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple[float, float, str, bool], tuple[float, dict]] = OrderedDict()
_CACHE_MAX_ENTRIES = 96


def validate_coordinates(latitude, longitude) -> tuple[float, float]:
    """Return finite coordinates inside legal geographic ranges."""
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("Latitude and longitude must be numbers") from exc
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("Latitude and longitude must be finite numbers")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude or longitude is outside the valid range")
    return lat, lon


def normal_india_theme(month: int, _latitude: float) -> tuple[str, str]:
    """India-specific fallback used only when the configured LLM is unavailable."""
    month = max(1, min(int(month), 12))
    # Snow is never guessed from latitude alone: many northern cities share
    # Himalayan latitudes without normal snowfall. The LLM can use both coarse
    # coordinates to distinguish those regions.
    if month in {6, 7, 8, 9}:
        return "rainy", "India seasonal fallback: normal monsoon period"
    if month in {3, 4, 5}:
        return "summer", "India seasonal fallback: normal hot period"
    if month in {11, 12, 1, 2}:
        return "winter", "India seasonal fallback: normal cool period"
    return "autumn", "India seasonal fallback: normal post-monsoon period"


def _provider_content(message) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for item in content:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                pieces.append(item["text"])
        return " ".join(pieces)
    return ""


def _bound_provider(provider) -> None:
    """Keep this cosmetic classification short, fast and inexpensive."""
    providers = getattr(provider, "providers", None)
    providers = providers if isinstance(providers, (list, tuple)) else [provider]
    for item in providers:
        if hasattr(item, "timeout"):
            try:
                timeout = float(getattr(item, "timeout", 3) or 3)
            except (TypeError, ValueError):
                timeout = 3
            item.timeout = min(timeout, 3)
        if hasattr(item, "max_retries"):
            item.max_retries = 0
        if hasattr(item, "max_output_tokens"):
            item.max_output_tokens = 32


def _snow_is_plausible(theme: str, month: int, latitude: float, longitude: float) -> bool:
    if theme != "snow":
        return True
    # A hard constraint prevents an ungrounded model response from showing snow
    # across the plains or during the Indian summer/monsoon.
    return month in {12, 1, 2, 3} and latitude >= 29.5 and 74 <= longitude <= 97


def select_theme_with_llm(now: datetime, latitude: float, longitude: float) -> str | None:
    """Ask XChat for one allowlisted theme representing normal Indian weather."""
    enabled = os.environ.get(
        "WEATHER_THEME_LLM_ENABLED",
        os.environ.get("WEATHER_THEME_LLM_ASSISTANCE", "true"),
    )
    if str(enabled).strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        return None

    # Facts contain only server-created numeric/date values. User text and
    # external documents never enter this prompt, avoiding prompt injection.
    facts = {
        "country": "India",
        "date": now.date().isoformat(),
        "month": now.month,
        "local_hour_ist": now.hour,
        "latitude_approx": round(latitude, 2),
        "longitude_approx": round(longitude, 2),
    }
    try:
        from services.xchat_service import configured_provider

        provider = configured_provider()
        _bound_provider(provider)
        response = provider.complete([
            {
                "role": "system",
                "content": (
                    "You select a decorative seasonal theme for a web application in India. "
                    "Use Indian seasonal climatology and the approximate coordinates to infer the "
                    "normal expected condition for this date and region; this is not live weather. "
                    "Use snow only for a normally snowy Himalayan location during its winter. "
                    "Reply with exactly one lowercase word from: summer, rainy, winter, autumn, snow. "
                    "Do not add punctuation, markdown, or explanation."
                ),
            },
            {"role": "user", "content": repr(facts)},
        ], [])
        candidate = re.sub(r"[^a-z]", "", _provider_content(response).strip().lower())
        if candidate not in ALLOWED_THEMES:
            return None
        if not _snow_is_plausible(candidate, now.month, latitude, longitude):
            return None
        return candidate
    except Exception as exc:
        logger.info("India seasonal theme LLM unavailable: %s", type(exc).__name__)
        return None


def _cache_get(key):
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if expires_at <= now:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return dict(payload)


def _cache_put(key, payload):
    try:
        ttl = int(os.environ.get("WEATHER_THEME_CACHE_SECONDS", "21600"))
    except (TypeError, ValueError):
        ttl = 21600
    ttl = max(900, min(ttl, 86400))
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + ttl, dict(payload))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)


def resolve_weather_theme(latitude, longitude, now: datetime | None = None) -> dict:
    """Return an AI-selected normal seasonal theme with a safe fallback."""
    lat, lon = validate_coordinates(latitude, longitude)
    current = now or datetime.now(INDIA_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=INDIA_TIMEZONE)
    else:
        current = current.astimezone(INDIA_TIMEZONE)
    is_day = 6 <= current.hour < 18

    # Coarse coordinates protect precise browser location and let nearby users
    # share a single LLM result. Day/night remains separate for sun/moon visuals.
    cache_key = (round(lat, 1), round(lon, 1), current.date().isoformat(), is_day)
    if cached := _cache_get(cache_key):
        cached["cached"] = True
        return cached

    fallback, fallback_reason = normal_india_theme(current.month, lat)
    llm_theme = select_theme_with_llm(current, lat, lon)
    theme = llm_theme or fallback
    result = {
        "available": True,
        "theme": theme,
        "reason": (
            "XChat selected the normal seasonal condition for this Indian region"
            if llm_theme else fallback_reason
        ),
        "selection_source": "llm_india_seasonal" if llm_theme else "india_seasonal_fallback",
        "condition": THEME_CONDITIONS[theme],
        "is_day": is_day,
        "evaluated_at": current.isoformat(timespec="minutes"),
        "timezone": "Asia/Kolkata",
        "estimated": True,
        "cached": False,
    }
    _cache_put(cache_key, result)
    return result

