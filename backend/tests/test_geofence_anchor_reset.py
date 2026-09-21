import sqlite3
import sys
import time
import types
from pathlib import Path

import pytest


flask = pytest.importorskip("flask")
from flask import Flask, g


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from routes import admin as admin_routes
from routes import vendor as vendor_routes


class RecordingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, payload, room=None):
        self.events.append((event, payload, room))


@pytest.fixture()
def geofence_client(tmp_path, monkeypatch):
    database = tmp_path / "geofence.sqlite"
    conn = sqlite3.connect(database)
    conn.executescript("""
        CREATE TABLE vendor_devices (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER,
            device_id TEXT,
            device_name TEXT,
            last_active_at DATETIME,
            battery_level REAL,
            geofence_lat REAL,
            geofence_lng REAL,
            geofence_radius REAL,
            last_lat REAL,
            last_lng REAL
        );
        INSERT INTO vendor_devices
            (id, vendor_id, device_id, device_name, geofence_lat, geofence_lng, geofence_radius)
        VALUES (1, 1, 'device-a', 'Gate A', 18.5000, 73.8000, 100);
    """)
    conn.commit()
    conn.close()

    def connection():
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        return db

    def admin_authenticate():
        g.user_role = "super_admin"
        g.username = "root@example.com"
        return None, None

    def device_authenticate():
        g.user_role = "user"
        g.username = "kiosk@example.com"
        return 1, None

    socket = RecordingSocket()
    fake_app = types.ModuleType("app")
    fake_app.get_db_connection = connection
    fake_app.socketio = socket
    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setattr(admin_routes, "authenticate_vendor_access", admin_authenticate)
    monkeypatch.setattr(vendor_routes, "authenticate_vendor_access", device_authenticate)
    monkeypatch.setattr(admin_routes, "vendor_has_feature", lambda *_args: True)
    monkeypatch.setattr(vendor_routes, "vendor_has_feature", lambda *_args: True)

    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(admin_routes.admin_bp, url_prefix="/api/admin")
    app.register_blueprint(vendor_routes.vendor_bp, url_prefix="/api")
    return app.test_client(), connection, socket


def test_reset_broadcasts_and_next_fresh_heartbeat_captures_anchor(geofence_client):
    client, connection, socket = geofence_client

    reset = client.put(
        "/api/admin/vendors/1/devices/device-a/geofence",
        json={"radius_meters": 150, "reset_anchor": True},
    )
    assert reset.status_code == 200
    assert reset.get_json()["reset_anchor"] is True
    assert socket.events[-1][0] == "geofence_config_updated"
    assert socket.events[-1][1]["device_id"] == "device-a"
    assert socket.events[-1][2] == "vendor_1"

    heartbeat = client.post(
        "/api/mobile/heartbeat",
        json={
            "device_id": "device-a",
            "battery_level": 80,
            "latitude": 19.12345,
            "longitude": 72.98765,
            "accuracy": 12,
            "location_timestamp": int(time.time() * 1000),
        },
    )
    assert heartbeat.status_code == 200
    body = heartbeat.get_json()
    assert body["geofence_status"] == "inside"
    assert body["distance_meters"] == 0.0
    assert body["anchor_lat"] == pytest.approx(19.12345)
    assert body["anchor_lng"] == pytest.approx(72.98765)

    conn = connection()
    saved = conn.execute(
        "SELECT geofence_lat, geofence_lng, geofence_radius FROM vendor_devices WHERE id = 1"
    ).fetchone()
    conn.close()
    assert tuple(saved) == pytest.approx((19.12345, 72.98765, 150.0))


def test_reset_does_not_capture_stale_cached_android_location(geofence_client):
    client, connection, _socket = geofence_client
    reset = client.put(
        "/api/admin/vendors/1/devices/device-a/geofence",
        json={"radius_meters": 100, "reset_anchor": True},
    )
    assert reset.status_code == 200

    heartbeat = client.post(
        "/api/mobile/heartbeat",
        json={
            "device_id": "device-a",
            "latitude": 20.0,
            "longitude": 75.0,
            "accuracy": 10,
            "location_timestamp": int((time.time() - 3600) * 1000),
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.get_json()["geofence_status"] == "gps_required"
    assert heartbeat.get_json()["anchor_pending"] is True

    conn = connection()
    saved = conn.execute(
        "SELECT geofence_lat, geofence_lng FROM vendor_devices WHERE id = 1"
    ).fetchone()
    conn.close()
    assert tuple(saved) == (None, None)


def test_disabled_feature_ignores_stored_anchor(geofence_client, monkeypatch):
    client, _connection, _socket = geofence_client
    monkeypatch.setattr(vendor_routes, "vendor_has_feature", lambda *_args: False)

    heartbeat = client.post(
        "/api/mobile/heartbeat",
        json={
            "device_id": "device-a",
            "latitude": 20.0,
            "longitude": 75.0,
            "accuracy": 10,
            "location_timestamp": int(time.time() * 1000),
        },
    )

    assert heartbeat.status_code == 200
    assert heartbeat.get_json()["geofence_status"] == "disabled"
    assert heartbeat.get_json()["anchor_lat"] is None
    assert heartbeat.get_json()["radius_meters"] is None
