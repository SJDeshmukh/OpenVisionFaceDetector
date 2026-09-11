import pytest
import sqlite3

from services.employee_email_reports_service import _load_people, employee_email, month_period


def test_employee_email_accepts_configured_custom_field():
    assert employee_email({"custom_data": '{"employee_email":"Worker@Example.com"}'}) == "worker@example.com"


def test_employee_email_accepts_uploaded_header_variants():
    assert employee_email({"custom_data": '{"Email Address":"Worker@Example.com"}'}) == "worker@example.com"


def test_employee_email_rejects_invalid_values():
    assert employee_email({"custom_data": '{"email":"not-an-email"}'}) is None


def test_month_period_covers_the_complete_selected_month():
    start, end = month_period("2026-02")
    assert start.isoformat() == "2026-02-01"
    assert end.isoformat() == "2026-02-28"


def test_month_period_rejects_non_month_input():
    with pytest.raises(ValueError, match="YYYY-MM"):
        month_period("2026-02-15")


def test_load_people_does_not_lose_rows_when_resolving_vendor_vertical():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, vertical TEXT);
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, custom_data TEXT
        );
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY, vendor_id INTEGER, person_id INTEGER, role TEXT
        );
        INSERT INTO vendors (id, vertical) VALUES (1, 'daily_wages');
        INSERT INTO faces (id, vendor_id, name, custom_data)
        VALUES (10, 1, 'Test Employee', '{"email":"employee@example.com","person_type":"employee"}');
        """
    )

    people = _load_people(conn.cursor(), 1)
    conn.close()

    assert len(people) == 1
    assert people[0]["name"] == "Test Employee"
    assert people[0]["email"] == "employee@example.com"
