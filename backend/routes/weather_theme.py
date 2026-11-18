"""Global weather-theme controls and authenticated live-theme resolution."""

from __future__ import annotations

import logging
import os

from flask import Blueprint, g, jsonify, request

from middleware.handlers import get_client_ip, rate_limit
from services.auth_service import require_auth
from services.weather_theme_service import (
    WeatherThemeError,
    resolve_weather_theme,
    validate_coordinates,
)
from utils import get_db_connection, log_audit


logger = logging.getLogger(__name__)
weather_theme_bp = Blueprint("weather_theme", __name__)
SETTING_KEY = "weather_dynamic_theme_enabled"


def _is_enabled() -> bool:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = ?", (SETTING_KEY,))
        row = cursor.fetchone()
        if not row:
            return False
        value = row.get("value") if isinstance(row, dict) else row[0]
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
    finally:
        conn.close()


def _set_enabled(enabled: bool) -> None:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO system_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (SETTING_KEY, "1" if enabled else "0"),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _device_coordinates(vendor_id):
    if not vendor_id:
        return None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT last_lat, last_lng
            FROM vendor_devices
            WHERE vendor_id = ? AND last_lat IS NOT NULL AND last_lng IS NOT NULL
            ORDER BY COALESCE(last_active_at, last_login_at, registered_at) DESC
            LIMIT 1
            """,
            (vendor_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return validate_coordinates(row.get("last_lat"), row.get("last_lng"))
        return validate_coordinates(row[0], row[1])
    except (ValueError, TypeError):
        return None
    finally:
        conn.close()


def _default_coordinates():
    latitude = os.environ.get("WEATHER_THEME_DEFAULT_LATITUDE", "").strip()
    longitude = os.environ.get("WEATHER_THEME_DEFAULT_LONGITUDE", "").strip()
    if not latitude or not longitude:
        return None
    try:
        return validate_coordinates(latitude, longitude)
    except ValueError:
        logger.warning("Ignoring invalid WEATHER_THEME_DEFAULT_LATITUDE/LONGITUDE")
        return None


@weather_theme_bp.get("/public/weather-theme/config")
@rate_limit(key_func=lambda: f"weather-config:{get_client_ip()}", limit=240, window=60)
def public_weather_theme_config():
    response = jsonify({"enabled": _is_enabled()})
    response.headers["Cache-Control"] = "private, max-age=30"
    return response


@weather_theme_bp.get("/admin/weather-theme")
@require_auth(roles=("super_admin",))
def get_weather_theme_setting():
    return jsonify({"enabled": _is_enabled()})


@weather_theme_bp.put("/admin/weather-theme")
@require_auth(roles=("super_admin",))
@rate_limit(key_func=lambda: f"weather-admin:{getattr(g, 'username', 'unknown')}", limit=20, window=60)
def update_weather_theme_setting():
    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        return jsonify({"error": "enabled must be true or false", "code": "VALIDATION_ERROR"}), 400

    _set_enabled(enabled)
    log_audit(
        "weather_theme_setting_updated",
        details={"enabled": enabled},
        actor=getattr(g, "username", None),
    )
    try:
        from app import socketio
        socketio.emit("weather_theme_setting_updated", {"enabled": enabled})
    except Exception as exc:
        logger.info("Weather theme websocket broadcast skipped: %s", type(exc).__name__)
    return jsonify({"enabled": enabled, "message": f"Weather themes {'enabled' if enabled else 'disabled'}"})


@weather_theme_bp.post("/weather-theme/current")
@require_auth()
@rate_limit(key_func=lambda: f"weather-current:{getattr(g, 'username', request.remote_addr)}", limit=12, window=60)
def current_weather_theme():
    if not _is_enabled():
        return jsonify({"enabled": False, "available": False, "theme": None})

    payload = request.get_json(silent=True) or {}
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    coordinates = None
    location_source = None
    if latitude is not None or longitude is not None:
        if latitude is None or longitude is None:
            return jsonify({"error": "Both latitude and longitude are required", "code": "VALIDATION_ERROR"}), 400
        try:
            coordinates = validate_coordinates(latitude, longitude)
            location_source = "browser"
        except ValueError as exc:
            return jsonify({"error": str(exc), "code": "VALIDATION_ERROR"}), 400

    if coordinates is None:
        coordinates = _device_coordinates(getattr(g, "vendor_id", None))
        location_source = "registered_device" if coordinates else None
    if coordinates is None:
        coordinates = _default_coordinates()
        location_source = "configured_default" if coordinates else None
    if coordinates is None:
        return jsonify({
            "enabled": True,
            "available": False,
            "theme": None,
            "message": "Location is unavailable; using the standard day/night theme",
        })

    try:
        result = resolve_weather_theme(*coordinates)
        return jsonify({"enabled": True, "location_source": location_source, **result})
    except WeatherThemeError as exc:
        logger.info("Weather theme fallback for %s: %s", getattr(g, "username", "unknown"), exc)
        return jsonify({
            "enabled": True,
            "available": False,
            "theme": None,
            "message": "Live weather is unavailable; using the standard day/night theme",
        })

