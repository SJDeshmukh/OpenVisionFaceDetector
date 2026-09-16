import importlib.util
import json
import logging
import sqlite3
import sys
from pathlib import Path
from types import ModuleType


BOOTSTRAP_PATH = Path(__file__).resolve().parents[1] / "database" / "bootstrap.py"


def _load_bootstrap(connection_factory, monkeypatch):
    utils_stub = ModuleType("utils")
    utils_stub.get_db_connection = connection_factory
    utils_stub._run = lambda conn, query, params: conn.execute(query, params)
    utils_stub.ensure_audit_logs_table = lambda: None
    utils_stub.logger = logging.getLogger("bootstrap-test")

    db_factory_stub = ModuleType("db_factory")
    monkeypatch.setitem(sys.modules, "utils", utils_stub)
    monkeypatch.setitem(sys.modules, "db_factory", db_factory_stub)

    spec = importlib.util.spec_from_file_location("bootstrap_under_test", BOOTSTRAP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_preserves_existing_vendor_features(tmp_path, monkeypatch):
    db_path = tmp_path / "bootstrap.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, company_name TEXT);
        CREATE TABLE companies (
            id INTEGER PRIMARY KEY, name TEXT, shifts TEXT,
            draft_timetable TEXT, live_timetable TEXT, vendor_id INTEGER
        );
        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, plan_type TEXT,
            start_date TEXT, end_date TEXT, grace_period_days INTEGER,
            features TEXT
        );
        INSERT INTO vendors VALUES (1, 'Configured Vendor'), (2, 'Recovered Vendor');
        INSERT INTO subscriptions (vendor_id, features) VALUES (1, '["reports"]');
    """)
    conn.commit()
    conn.close()

    bootstrap = _load_bootstrap(lambda: sqlite3.connect(db_path), monkeypatch)
    bootstrap.ensure_vendor_companies_and_subscription_features()

    conn = sqlite3.connect(db_path)
    existing = json.loads(conn.execute(
        "SELECT features FROM subscriptions WHERE vendor_id = 1"
    ).fetchone()[0])
    recovered = json.loads(conn.execute(
        "SELECT features FROM subscriptions WHERE vendor_id = 2"
    ).fetchone()[0])
    company_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    conn.close()

    assert existing == ["reports"]
    assert recovered == ["mobile_app", "shifts"]
    assert "late_mark" not in recovered
    assert company_count == 2
