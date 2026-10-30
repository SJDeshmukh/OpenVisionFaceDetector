import importlib.util
import sqlite3
from pathlib import Path
import sys
from types import ModuleType


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DB_FACTORY_PATH = BACKEND / "db_factory.py"


def _load_db_factory(monkeypatch):
    database_stub = ModuleType("database")
    models_stub = ModuleType("database.models")
    models_stub.db = object()
    monkeypatch.setitem(sys.modules, "database", database_stub)
    monkeypatch.setitem(sys.modules, "database.models", models_stub)

    spec = importlib.util.spec_from_file_location("db_factory_schema_test", DB_FACTORY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_faces_table_is_upgraded_before_display_id_index(monkeypatch):
    db_factory = _load_db_factory(monkeypatch)
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE faces ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, templates TEXT, "
        "vendor_id INTEGER, custom_data TEXT)"
    )

    db_factory.init_sqlite_schema(conn)
    db_factory.init_sqlite_schema(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(faces)")}
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(faces)")}
    assert "display_id" in columns
    assert "registered_at" in columns
    assert "idx_faces_vendor_display" in indexes

    conn.execute(
        "INSERT INTO faces (name, vendor_id, registered_at, daily_wage) VALUES (?, ?, ?, ?)",
        ("Registered Employee", 7, "2026-01-15 09:30:00", 750),
    )
    initial_price = conn.execute(
        """SELECT effective_from, daily_wage, change_reason
             FROM employee_salary_versions
            WHERE vendor_id = 7 ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert initial_price == ("2026-01-15", 750, "Initial price")
    conn.close()
