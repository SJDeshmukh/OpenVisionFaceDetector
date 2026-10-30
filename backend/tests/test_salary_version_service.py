import importlib.util
import sqlite3
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def salary_service(monkeypatch):
    auth_stub = types.ModuleType("services.auth_service")
    auth_stub.verify_password = lambda raw, stored: (
        raw == "correct-password" and stored == "hashed-password"
    )
    monkeypatch.setitem(sys.modules, "services.auth_service", auth_stub)
    spec = importlib.util.spec_from_file_location(
        "salary_version_service_under_test",
        BACKEND / "services" / "salary_version_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def salary_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            daily_wage REAL DEFAULT 0,
            basic_salary REAL DEFAULT 0,
            hra REAL DEFAULT 0,
            conveyance REAL DEFAULT 0,
            special_allowance REAL DEFAULT 0,
            pf_enabled INTEGER DEFAULT 0,
            esi_enabled INTEGER DEFAULT 0,
            gratuity_enabled INTEGER DEFAULT 0,
            professional_tax REAL DEFAULT 0,
            late_allowance_days INTEGER,
            late_deduction_amount REAL,
            joining_date DATE,
            registered_at DATETIME
        );
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            vendor_id INTEGER
        );
        CREATE TABLE employee_salary_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            effective_from DATE NOT NULL,
            effective_to DATE,
            daily_wage NUMERIC NOT NULL,
            basic_salary NUMERIC NOT NULL,
            hra NUMERIC NOT NULL,
            conveyance NUMERIC NOT NULL,
            special_allowance NUMERIC NOT NULL,
            pf_enabled INTEGER NOT NULL,
            esi_enabled INTEGER NOT NULL,
            gratuity_enabled INTEGER NOT NULL,
            professional_tax NUMERIC NOT NULL,
            late_allowance_days INTEGER,
            late_deduction_amount NUMERIC,
            changed_by TEXT NOT NULL,
            change_reason TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vendor_id, person_id, version_number)
        );
        CREATE TABLE salary_reauth_tokens (
            token_hash TEXT PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            purpose TEXT NOT NULL,
            expires_at DATETIME NOT NULL,
            used_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO faces (
            id, vendor_id, daily_wage, basic_salary, hra, conveyance,
            special_allowance, pf_enabled, esi_enabled, gratuity_enabled,
            professional_tax, late_allowance_days, late_deduction_amount, registered_at
        ) VALUES (10, 8, 100, 0, 0, 0, 0, 0, 0, 0, 0, NULL, NULL, '2026-01-15 09:00:00');
    """)
    conn.execute(
        "INSERT INTO system_users VALUES (?, ?, ?)",
        ("manager@example.com", "hashed-password", 8),
    )
    conn.commit()
    return conn


def _confirmed_token(service, conn):
    cursor = conn.cursor()
    token, _ = service.issue_reauth_token(
        cursor,
        8,
        "manager@example.com",
        "vendor_admin",
        "correct-password",
        "salary_change",
    )
    conn.commit()
    return token


def test_salary_change_creates_audited_version_and_single_use_confirmation(
    salary_service, salary_db
):
    effective_day = date.today() - timedelta(days=5)
    token = _confirmed_token(salary_service, salary_db)
    cursor = salary_db.cursor()
    changed = salary_service.apply_salary_updates(
        salary_db,
        cursor,
        vendor_id=8,
        username="manager@example.com",
        updates=[{"person_id": 10, "daily_wage": 200}],
        effective_from=effective_day,
        reason="Annual revision",
        reauth_token=token,
    )
    salary_db.commit()

    assert changed[0]["salary_version"] == 2
    rows = salary_db.execute(
        """SELECT version_number, effective_from, effective_to, daily_wage,
                  changed_by, change_reason
             FROM employee_salary_versions ORDER BY version_number"""
    ).fetchall()
    assert [(row[0], row[3]) for row in rows] == [(1, 100), (2, 200)]
    assert rows[0][1] == "2026-01-15"
    assert rows[0][5] == "Initial salary"
    assert rows[0][2] == effective_day.isoformat()
    assert rows[1][1] == effective_day.isoformat()
    assert rows[1][4:] == ("manager@example.com", "Annual revision")
    assert salary_db.execute("SELECT daily_wage FROM faces WHERE id = 10").fetchone()[0] == 200

    with pytest.raises(salary_service.ReauthenticationError):
        salary_service.consume_reauth_token(
            salary_db.cursor(), 8, "manager@example.com", token, "salary_change"
        )


def test_historical_payroll_uses_each_effective_salary_version(salary_service, salary_db):
    raise_day = date.today() - timedelta(days=5)
    token = _confirmed_token(salary_service, salary_db)
    salary_service.apply_salary_updates(
        salary_db,
        salary_db.cursor(),
        vendor_id=8,
        username="manager@example.com",
        updates=[{"person_id": 10, "daily_wage": 200}],
        effective_from=raise_day,
        reason="Approved raise",
        reauth_token=token,
    )
    salary_db.commit()

    versions = salary_service.load_salary_versions(salary_db.cursor(), 8, [10])[10]
    result = salary_service.calculate_versioned_shift_wage(
        versions,
        {"daily_wage": 999},
        {
            raise_day - timedelta(days=1): 8 * 3600,
            raise_day: 8 * 3600,
        },
        8,
    )
    assert result["gross_wage"] == 300
    assert result["regular_hours"] == 16
    assert len(result["salary_version_ids"]) == 2


def test_retroactive_change_keeps_later_current_salary(salary_service, salary_db):
    later_day = date.today() - timedelta(days=5)
    token = _confirmed_token(salary_service, salary_db)
    salary_service.apply_salary_updates(
        salary_db,
        salary_db.cursor(),
        vendor_id=8,
        username="manager@example.com",
        updates=[{"person_id": 10, "daily_wage": 200}],
        effective_from=later_day,
        reason="Current salary",
        reauth_token=token,
    )
    salary_db.commit()

    earlier_day = date.today() - timedelta(days=10)
    second_token = _confirmed_token(salary_service, salary_db)
    salary_service.apply_salary_updates(
        salary_db,
        salary_db.cursor(),
        vendor_id=8,
        username="manager@example.com",
        updates=[{
            "person_id": 10,
            "daily_wage": 150,
            "expected_salary_version": 2,
        }],
        effective_from=earlier_day,
        reason="Historical correction",
        reauth_token=second_token,
    )
    salary_db.commit()

    versions = salary_service.load_salary_versions(salary_db.cursor(), 8, [10])[10]
    assert salary_service.resolve_salary_version(versions, earlier_day)["daily_wage"] == 150
    assert salary_service.resolve_salary_version(versions, later_day)["daily_wage"] == 200
    assert salary_db.execute("SELECT daily_wage FROM faces WHERE id = 10").fetchone()[0] == 200
