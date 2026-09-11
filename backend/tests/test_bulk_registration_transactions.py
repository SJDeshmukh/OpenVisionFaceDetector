import io
import json
import sqlite3
import sys
from pathlib import Path

from flask import Flask, g
from openpyxl import Workbook


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from routes import bulk_registration


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema(path):
    conn = _connection(path)
    conn.executescript(
        """
        CREATE TABLE vendors (
            id INTEGER PRIMARY KEY,
            vertical TEXT,
            registration_config TEXT
        );
        CREATE TABLE subscriptions (vendor_id INTEGER PRIMARY KEY, features TEXT);
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT UNIQUE,
            department TEXT,
            designation TEXT,
            shift TEXT,
            vendor_id INTEGER,
            custom_data TEXT,
            display_id INTEGER
        );
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY,
            password TEXT,
            password_plain TEXT,
            role TEXT,
            vendor_id INTEGER,
            person_id INTEGER
        );
        CREATE TABLE bulk_attendance_config (
            vendor_id INTEGER PRIMARY KEY,
            fields TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE classes (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER,
            class_year TEXT,
            division TEXT,
            branch TEXT
        );
        INSERT INTO vendors (id, vertical, registration_config)
        VALUES (1, 'daily_wages', '[]');
        INSERT INTO subscriptions (vendor_id, features) VALUES (1, '[]');
        INSERT INTO faces (name, phone, vendor_id, custom_data, display_id)
        VALUES ('Existing Employee', '9000000001', 1, '{}', 1);
        """
    )
    conn.commit()
    conn.close()


def _mapping(*_args, **_kwargs):
    return {
        "mapping": {
            "name": "Employee Name",
            "person_id": "Employee ID",
            "phone": "Mobile Number",
            "department": "Department",
        },
        "method": "deterministic",
        "warning": None,
    }


def _employee_workbook(rows):
    output = io.BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Employees"
    sheet.append(["Employee Name", "Employee ID", "Mobile Number", "Department"])
    for row in rows:
        sheet.append(row)
    workbook.save(output)
    output.seek(0)
    return output


def test_rejected_row_does_not_abort_remaining_employee_import(tmp_path, monkeypatch):
    db_path = tmp_path / "bulk-import.db"
    _create_schema(db_path)
    monkeypatch.setattr(bulk_registration, "get_db_connection", lambda: _connection(db_path))
    monkeypatch.setattr(bulk_registration, "map_spreadsheet_headers", _mapping)
    monkeypatch.setattr(bulk_registration, "log_audit", lambda *_args, **_kwargs: None)

    workbook = _employee_workbook(
        [
            ["Rejected Employee", "EMP001", "9000000001", "Operations"],
            ["Imported Employee", "EMP002", "9000000002", "Finance"],
        ]
    )
    app = Flask(__name__)
    with app.test_request_context(
        "/bulk-registration/upload",
        method="POST",
        data={"file": (workbook, "employees.xlsx")},
        content_type="multipart/form-data",
    ):
        g.vendor_id = 1
        g.username = "owner@example.com"
        response = bulk_registration.bulk_registration_upload.__wrapped__()

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["message"] == "Successfully registered 1 employees."
    assert payload["errors"] and "UNIQUE constraint failed" in payload["errors"][0]

    conn = _connection(db_path)
    imported = conn.execute(
        "SELECT name, custom_data FROM faces WHERE phone = ?", ("9000000002",)
    ).fetchone()
    config = json.loads(
        conn.execute("SELECT registration_config FROM vendors WHERE id = 1").fetchone()[0]
    )
    conn.close()

    assert imported["name"] == "Imported Employee"
    assert json.loads(imported["custom_data"])["person_type"] == "employee"
    assert json.loads(imported["custom_data"])["employee_id"] == "EMP002"
    assert any(field["field"] == "employee_id" for field in config)


def test_all_rejected_rows_return_the_first_real_error(tmp_path, monkeypatch):
    db_path = tmp_path / "bulk-import.db"
    _create_schema(db_path)
    monkeypatch.setattr(bulk_registration, "get_db_connection", lambda: _connection(db_path))
    monkeypatch.setattr(bulk_registration, "map_spreadsheet_headers", _mapping)
    monkeypatch.setattr(bulk_registration, "log_audit", lambda *_args, **_kwargs: None)

    app = Flask(__name__)
    with app.test_request_context(
        "/bulk-registration/upload",
        method="POST",
        data={
            "file": (
                io.BytesIO(
                    b"Employee Name,Employee ID,Mobile Number,Department\n"
                    b"Rejected Employee,EMP001,9000000001,Operations\n"
                ),
                "employees.csv",
            )
        },
        content_type="multipart/form-data",
    ):
        g.vendor_id = 1
        g.username = "owner@example.com"
        response, status = bulk_registration.bulk_registration_upload.__wrapped__()

    payload = response.get_json()
    assert status == 400
    assert payload["error"].startswith("No employees were imported. Row 2:")
    assert "current transaction is aborted" not in payload["error"].lower()
