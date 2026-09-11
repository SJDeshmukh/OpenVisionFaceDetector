import importlib
import sqlite3
import sys
import types

import pytest

flask = pytest.importorskip("flask")
from flask import Flask, g, request


@pytest.fixture()
def owner_client(tmp_path, monkeypatch):
    # Owner routes import production vision/database utilities through the auth
    # module. Stub those unrelated native dependencies only for this fixture,
    # then fully restore the import table so other tests cannot be affected.
    module_names = ("utils", "db_factory", "services.auth_service", "routes.owner")
    saved_modules = {name: sys.modules.get(name) for name in module_names}
    utils_stub = types.ModuleType("utils")
    utils_stub.parse_db_date = lambda value: value
    db_stub = types.ModuleType("db_factory")
    db_stub.get_db_connection = lambda: None
    sys.modules["utils"] = utils_stub
    sys.modules["db_factory"] = db_stub
    sys.modules.pop("services.auth_service", None)
    sys.modules.pop("routes.owner", None)
    owner_routes = importlib.import_module("routes.owner")
    test_auth_service = sys.modules["services.auth_service"]
    for name in ("utils", "db_factory"):
        module = saved_modules[name]
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module

    employee_email_reports_service = importlib.import_module("services.employee_email_reports_service")
    database = tmp_path / "owner-advances.sqlite"
    conn = sqlite3.connect(database)
    conn.executescript("""
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, display_id INTEGER
        );
        CREATE TABLE advances (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER, amount REAL,
            amount_cash REAL, amount_online REAL, date TEXT, status TEXT,
            deduction_month TEXT, approved_by TEXT, approved_at TEXT,
            rejection_reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO faces VALUES (1, 1, 'Sudhanshu', 101);
        INSERT INTO faces VALUES (2, 2, 'Other Vendor Employee', 201);
        INSERT INTO advances (
            id, vendor_id, person_id, amount, amount_cash, amount_online,
            date, status, deduction_month
        ) VALUES (10, 1, 1, 2500, 500, 2000, '2026-09-11', 'pending', '2026-09');
        INSERT INTO advances (
            id, vendor_id, person_id, amount, amount_cash, amount_online,
            date, status, deduction_month
        ) VALUES (20, 2, 2, 9000, 9000, 0, '2026-09-11', 'pending', '2026-09');
    """)
    conn.commit()
    conn.close()

    def connection():
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        return db

    def authenticate():
        g.user_role = request.headers.get("X-Test-Role", "owner")
        g.username = "business-owner"
        return 1, None

    monkeypatch.setattr(owner_routes, "get_db_connection", connection)
    monkeypatch.setattr(test_auth_service, "authenticate_vendor_access", authenticate)
    monkeypatch.setattr(employee_email_reports_service, "queue_advance_notification", lambda advance_id, event: True)

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test")
    app.register_blueprint(owner_routes.owner_bp, url_prefix="/api")
    yield app.test_client(), connection

    for name, module in saved_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def test_owner_sees_only_own_vendor_advance_requests(owner_client):
    client, _connection = owner_client

    response = client.get("/api/owner/advances?status=all", headers={"X-Test-Role": "owner"})

    assert response.status_code == 200
    advances = response.get_json()["advances"]
    assert [(item["id"], item["name"]) for item in advances] == [(10, "Sudhanshu")]


def test_non_owner_cannot_view_or_decide_advances(owner_client):
    client, _connection = owner_client

    listing = client.get("/api/owner/advances", headers={"X-Test-Role": "user"})
    decision = client.post(
        "/api/owner/advances/approve", json={"advance_id": 10},
        headers={"X-Test-Role": "vendor_admin"},
    )

    assert listing.status_code == 403
    assert decision.status_code == 403


def test_owner_can_approve_without_bearer_header_when_authenticated_by_cookie_context(owner_client):
    client, connection = owner_client

    response = client.post(
        "/api/owner/advances/approve", json={"advance_id": 10},
        headers={"X-Test-Role": "owner"},
    )

    assert response.status_code == 200
    assert response.get_json()["email_queued"] is True
    conn = connection()
    row = conn.execute("SELECT status, approved_by FROM advances WHERE id = 10").fetchone()
    conn.close()
    assert tuple(row) == ("approved", "business-owner")
