import json
import sqlite3

from services.config_utils import hydrate_registration_config


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE companies (id INTEGER PRIMARY KEY, vendor_id INTEGER, shifts TEXT)"
    )
    return conn


def test_company_shift_is_added_to_registration_config():
    conn = _connection()
    conn.execute(
        "INSERT INTO companies (id, vendor_id, shifts) VALUES (?, ?, ?)",
        (1, 8, json.dumps([
            {"id": 10, "name": "Work", "active": True},
            {"id": 11, "name": "Disabled", "active": False},
        ])),
    )

    config = hydrate_registration_config(
        8,
        [{"field": "name", "label": "Name", "type": "text"}],
        conn=conn,
    )

    assert [field["field"] for field in config] == ["name", "shift"]
    assert config[-1]["type"] == "select"
    assert config[-1]["options"] == ["Work"]
    assert config[-1]["options_source"] == "company_shifts"


def test_existing_shift_field_uses_current_timetable_options():
    conn = _connection()
    conn.execute(
        "INSERT INTO companies (id, vendor_id, shifts) VALUES (?, ?, ?)",
        (1, 8, json.dumps([
            {"id": 10, "name": "Day"},
            {"id": 11, "name": "Night"},
        ])),
    )

    config = hydrate_registration_config(
        8,
        [{
            "field": "shift",
            "label": "Assigned Shift",
            "type": "text",
            "options": ["Stale"],
            "required": True,
        }],
        conn=conn,
    )

    assert len(config) == 1
    assert config[0]["label"] == "Assigned Shift"
    assert config[0]["required"] is True
    assert config[0]["type"] == "select"
    assert config[0]["options"] == ["Day", "Night"]


def test_shift_options_are_vendor_scoped_and_not_injected_when_empty():
    conn = _connection()
    conn.execute(
        "INSERT INTO companies (id, vendor_id, shifts) VALUES (?, ?, ?)",
        (1, 9, json.dumps([{"name": "Other Vendor Shift"}])),
    )

    config = hydrate_registration_config(
        8,
        [{"field": "name", "label": "Name"}],
        conn=conn,
    )

    assert [field["field"] for field in config] == ["name"]
