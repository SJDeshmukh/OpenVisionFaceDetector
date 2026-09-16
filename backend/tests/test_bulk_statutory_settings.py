import sqlite3
import sys
from pathlib import Path

import pytest


flask = pytest.importorskip("flask")
from flask import Flask, g


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from routes import vendor as vendor_routes
import services.auth_service as auth_service
import utils


@pytest.fixture()
def statutory_client(tmp_path, monkeypatch):
    database = tmp_path / "statutory.sqlite"
    conn = sqlite3.connect(database)
    conn.executescript("""
        CREATE TABLE subscriptions (vendor_id INTEGER, features TEXT);
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER,
            pf_enabled INTEGER,
            esi_enabled INTEGER
        );
        INSERT INTO subscriptions VALUES (1, '["payroll"]');
        INSERT INTO faces VALUES (1, 1, 1, 1);
        INSERT INTO faces VALUES (2, 1, 1, 1);
        INSERT INTO faces VALUES (3, 2, 1, 1);
    """)
    conn.commit()
    conn.close()

    def connection():
        return sqlite3.connect(database)

    def authenticate():
        g.user_role = "owner"
        g.username = "owner@example.com"
        g.vendor_id = 1
        return 1, None

    def verify_current_password(_cursor, supplied_password):
        if supplied_password != "correct-password":
            return "Incorrect password", 403
        return None

    monkeypatch.setattr(utils, "get_db_connection", connection)
    monkeypatch.setattr(vendor_routes, "get_db_connection", connection)
    monkeypatch.setattr(auth_service, "authenticate_vendor_access", authenticate)
    monkeypatch.setattr(vendor_routes, "authenticate_vendor_access", authenticate)
    monkeypatch.setattr(vendor_routes, "_verify_current_web_password", verify_current_password)
    monkeypatch.setattr(vendor_routes, "cache_delete_vendor_prefix", lambda _vendor_id: None)
    monkeypatch.setattr(vendor_routes, "log_audit", lambda *args, **kwargs: None)

    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(vendor_routes.vendor_bp, url_prefix="/api")
    return app.test_client(), connection


def test_bulk_disable_requires_password_and_stays_in_vendor_scope(statutory_client):
    client, connection = statutory_client

    denied = client.put(
        "/api/persons/wages/statutory/bulk",
        json={"enabled": False, "password": "wrong-password"},
    )
    assert denied.status_code == 403

    response = client.put(
        "/api/persons/wages/statutory/bulk",
        json={"enabled": False, "password": "correct-password"},
    )
    assert response.status_code == 200
    assert response.get_json()["affected_employees"] == 2

    conn = connection()
    rows = conn.execute(
        "SELECT vendor_id, pf_enabled, esi_enabled FROM faces ORDER BY id"
    ).fetchall()
    conn.close()
    assert rows == [(1, 0, 0), (1, 0, 0), (2, 1, 1)]

