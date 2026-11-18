"""Live weather resolution and bounded seasonal-theme classification.

Weather data is intentionally reduced to numeric fields before it can reach the
optional LLM classifier. The model is advisory only: deterministic rules remain
authoritative for snow, rain and temperature extremes, and every model response
is checked against a small allowlist.
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

import requests


logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
ALLOWED_THEMES = frozenset({"summer", "rainy", "winter", "autumn", "snow"})
SNOW_CODES = frozenset({71, 73, 75, 77, 85, 86})
RAIN_CODES = frozenset({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 97, 99})

WEATHER_CODE_LABELS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    97: "Heavy thunderstorm",
    99: "Thunderstorm with heavy hail",
}

_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple[float, float], tuple[float, dict]] = OrderedDict()
_CACHE_MAX_ENTRIES = 96


class WeatherThemeError(RuntimeError):
    """A recoverable weather-provider or response error."""


def validate_coordinates(latitude, longitude) -> tuple[float, float]:
    """Return finite coordinates inside the legal geographic ranges."""
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


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _month_for_weather(current: dict) -> int:
    raw_time = str(current.get("time") or "")[:10]
    try:
        return datetime.fromisoformat(raw_time).month
    except (TypeError, ValueError):
        return datetime.utcnow().month


def deterministic_theme(current: dict, latitude: float) -> tuple[str, str, bool]:
    """Choose a safe theme and report whether an LLM could improve ambiguity."""
    code = int(_number(current.get("weather_code"), 0))
    temperature = _number(current.get("temperature_2m"))
    apparent = _number(current.get("apparent_temperature"), temperature)
    precipitation = _number(current.get("precipitation"))
    rain = _number(current.get("rain"))
    showers = _number(current.get("showers"))
    snowfall = _number(current.get("snowfall"))

    if snowfall > 0 or code in SNOW_CODES:
        return "snow", "Current conditions report snowfall", False
    if precipitation > 0 or rain > 0 or showers > 0 or code in RAIN_CODES:
        return "rainy", "Current conditions report rain or a thunderstorm", False
    if apparent <= 13 or temperature <= 12:
        return "winter", "Current temperature is in the cold range", False
    if apparent >= 30 or temperature >= 29:
        return "summer", "Current temperature is in the hot range", False

    # Mild, dry conditions are where a short model classification adds value.
    # The seasonal fallback stays deterministic if no AI provider is available.
    month = _month_for_weather(current)
    if latitude < 0:
        month = ((month + 5) % 12) + 1
    if month in {12, 1, 2}:
        return "winter", "Mild and dry during the local winter season", True
    if month in {3, 4, 5}:
        return "summer", "Mild and dry during the local summer season", True
    if month in {6, 7, 8}:
        return "rainy", "Mild conditions during the local rainy season", True
    return "autumn", "Mild and dry during the local autumn season", True


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
    """Keep this decorative classifier fast and inexpensive."""
    providers = getattr(provider, "providers", None) or [provider]
    for item in providers:
        if hasattr(item, "timeout"):
            item.timeout = min(float(getattr(item, "timeout", 3) or 3), 3)
        if hasattr(item, "max_retries"):
            item.max_retries = 0
        if hasattr(item, "max_output_tokens"):
            item.max_output_tokens = 32


def _llm_theme(current: dict, latitude: float, fallback: str) -> str | None:
    if str(os.environ.get("WEATHER_THEME_LLM_ASSISTANCE", "true")).strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        return None

    # Only numeric, bounded data is sent. No remote text or user-provided text
    # is included, which removes the indirect-prompt-injection surface.
    facts = {
        "weather_code": int(_number(current.get("weather_code"), 0)),
        "temperature_c": round(_number(current.get("temperature_2m")), 1),
        "apparent_temperature_c": round(_number(current.get("apparent_temperature")), 1),
        "humidity_percent": int(_number(current.get("relative_humidity_2m"), 0)),
        "cloud_cover_percent": int(_number(current.get("cloud_cover"), 0)),
        "wind_kmh": round(_number(current.get("wind_speed_10m")), 1),
        "is_day": 1 if int(_number(current.get("is_day"), 1)) == 1 else 0,
        "month": _month_for_weather(current),
        "hemisphere": "south" if latitude < 0 else "north",
        "rule_fallback": fallback,
    }
    try:
        from services.xchat_service import configured_provider

        provider = configured_provider()
        _bound_provider(provider)
        response = provider.complete([
            {
                "role": "system",
                "content": (
                    "Classify numeric weather facts for a decorative web theme. "
                    "Reply with exactly one lowercase word from: summer, rainy, winter, autumn, snow. "
                    "Do not add punctuation or explanation."
                ),
            },
            {"role": "user", "content": repr(facts)},
        ], [])
        candidate = _provider_content(response).strip().lower()
        candidate = re.sub(r"[^a-z]", "", candidate)
        if candidate not in ALLOWED_THEMES:
            return None

        # The model cannot invent precipitation or impossible temperature
        # conditions. Ambiguous dry weather may only select plausible themes.
        temperature = facts["temperature_c"]
        plausible = {fallback, "autumn"}
        if temperature >= 18:
            plausible.add("summer")
        if temperature <= 24:
            plausible.add("winter")
        if facts["humidity_percent"] >= 70 or facts["cloud_cover_percent"] >= 75:
            plausible.add("rainy")
        if temperature <= 5:
            plausible.add("snow")
        return candidate if candidate in plausible else None
    except Exception as exc:  # AI is optional and must never affect the app.
        logger.info("Weather theme AI assistance unavailable: %s", type(exc).__name__)
        return None


def classify_theme(current: dict, latitude: float) -> tuple[str, str, str]:
    fallback, reason, ambiguous = deterministic_theme(current, latitude)
    if ambiguous:
        assisted = _llm_theme(current, latitude, fallback)
        if assisted:
            return assisted, "AI-assisted classification of mild weather", "llm_assisted"
    return fallback, reason, "weather_rules"


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
        ttl = int(os.environ.get("WEATHER_THEME_CACHE_SECONDS", "900"))
    except (TypeError, ValueError):
        ttl = 900
    ttl = max(300, min(ttl, 3600))
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + ttl, dict(payload))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)


def resolve_weather_theme(latitude, longitude) -> dict:
    lat, lon = validate_coordinates(latitude, longitude)
    # Coarse cache keys avoid retaining precise browser coordinates and prevent
    # many nearby clients from multiplying weather and AI requests.
    cache_key = (round(lat, 1), round(lon, 1))
    if cached := _cache_get(cache_key):
        cached["cached"] = True
        return cached

    try:
        configured_timeout = float(os.environ.get("WEATHER_API_TIMEOUT_SECONDS", "4"))
    except (TypeError, ValueError):
        configured_timeout = 4
    timeout = max(2, min(configured_timeout, 10))
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "current": (
            "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,"
            "rain,showers,snowfall,weather_code,cloud_cover,wind_speed_10m,is_day"
        ),
        "timezone": "auto",
        "forecast_days": 1,
    }
    api_key = os.environ.get("OPEN_METEO_API_KEY", "").strip()
    if api_key:
        params["apikey"] = api_key
    weather_api_url = os.environ.get("WEATHER_API_BASE_URL", OPEN_METEO_URL).strip() or OPEN_METEO_URL
    try:
        response = requests.get(
            weather_api_url,
            params=params,
            headers={"User-Agent": "TapInX-Weather-Theme/1.0"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherThemeError("Live weather is temporarily unavailable") from exc

    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict) or "weather_code" not in current:
        raise WeatherThemeError("Weather provider returned an incomplete response")

    theme, reason, selection_source = classify_theme(current, lat)
    weather_code = int(_number(current.get("weather_code"), 0))
    result = {
        "available": True,
        "theme": theme,
        "reason": reason,
        "selection_source": selection_source,
        "condition": WEATHER_CODE_LABELS.get(weather_code, "Current weather"),
        "weather_code": weather_code,
        "temperature_c": round(_number(current.get("temperature_2m")), 1),
        "apparent_temperature_c": round(_number(current.get("apparent_temperature")), 1),
        "is_day": bool(int(_number(current.get("is_day"), 1))),
        "observed_at": str(current.get("time") or "")[:32],
        "timezone": str(payload.get("timezone") or "")[:80],
        "cached": False,
    }
    _cache_put(cache_key, result)
    return result

