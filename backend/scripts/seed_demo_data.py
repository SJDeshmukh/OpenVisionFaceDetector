import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set


ONE_BY_ONE_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6q0wN8AAAAASUVORK5CYII="
)


def _as_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _table_columns(conn, table: str) -> Set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}


def _safe_exec(conn, sql: str, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or [])


def _safe_delete_all(conn, table: str):
    try:
        _safe_exec(conn, f"DELETE FROM {table}")
    except Exception:
        return


def _safe_reset_sequence(conn, table: str):
    try:
        _safe_exec(conn, "DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    except Exception:
        return


def _insert_row(conn, table: str, values: Dict[str, Any]):
    cols = _table_columns(conn, table)
    filtered = {k: v for k, v in values.items() if k in cols}
    if not filtered:
        return
    keys = list(filtered.keys())
    placeholders = ",".join(["?"] * len(keys))
    sql = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({placeholders})"
    _safe_exec(conn, sql, [filtered[k] for k in keys])


def _upsert_user(conn, username: str, password: str, role: str, vendor_id: Optional[int]):
    cols = _table_columns(conn, "system_users")
    if "vendor_id" in cols:
        _safe_exec(
            conn,
            "INSERT OR REPLACE INTO system_users (username, password, role, vendor_id) VALUES (?, ?, ?, ?)",
            (username, password, role, vendor_id),
        )
    else:
        _safe_exec(
            conn,
            "INSERT OR REPLACE INTO system_users (username, password, role) VALUES (?, ?, ?)",
            (username, password, role),
        )


def _ensure_vendor_and_subscription(conn, backend_app):
    today = datetime.now().date()
    vendor_id = 1
    reg_config = [
        {"field": "employee_id", "label": "Employee ID", "enabled": True},
        {"field": "site", "label": "Site", "enabled": True},
        {"field": "team", "label": "Team", "enabled": True},
    ]
    _insert_row(
        conn,
        "vendors",
        {
            "id": vendor_id,
            "company_name": "Demo Vendor Co",
            "contact_person": "Demo Admin",
            "phone": "+1-555-0100",
            "email": "demo@example.com",
            "status": "active",
            "web_login_enabled": 1,
            "frontend_bundle_id": "attendance_payroll_ui",
            "backend_service_id": "default_api",
            "config": json.dumps({}),
            "registration_config": json.dumps(reg_config),
            "vertical": "factory",
        },
    )

    features = backend_app.BUNDLE_FEATURES.get("attendance_payroll_ui") or backend_app.BUNDLE_FEATURES.get("default_attendance") or []
    subs_cols = _table_columns(conn, "subscriptions")
    if not subs_cols:
        raise RuntimeError("subscriptions table not found in DB. Importing backend app should have created it.")
    base_sub = {
        "vendor_id": vendor_id,
        "plan_type": "pro",
        "start_date": today.strftime("%Y-%m-%d"),
        "end_date": (today + timedelta(days=365)).strftime("%Y-%m-%d"),
        "grace_period_days": 7,
        "max_users": 50,
        "max_employees": 500,
        "max_mobile_devices": 10,
        "max_web_sessions": 5,
        "cost_per_user": 199.0,
        "cost_per_employee": 50.0,
        "setup_fee": 0.0,
        "setup_fee_paid": 1,
        "features": json.dumps(features),
    }
    filtered = {k: v for k, v in base_sub.items() if k in subs_cols}
    keys = list(filtered.keys())
    if not keys:
        raise RuntimeError("No compatible columns found for subscriptions insert.")
    placeholders = ",".join(["?"] * len(keys))
    _safe_exec(conn, "DELETE FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
    _safe_exec(
        conn,
        f"INSERT INTO subscriptions ({','.join(keys)}) VALUES ({placeholders})",
        [filtered[k] for k in keys],
    )

    _upsert_user(conn, "superadmin", "super123", "super_admin", None)
    _upsert_user(conn, "demo_admin", "demo123", "vendor_admin", vendor_id)
    _upsert_user(conn, "admin", "admin123", "admin", None)

    return vendor_id, reg_config


def _ensure_company(conn, vendor_id: int):
    shifts = [
        {"id": 1, "name": "Day Shift", "start_time": "09:00", "end_time": "18:00", "active": True, "description": "Standard"},
        {"id": 2, "name": "Night Shift", "start_time": "21:00", "end_time": "06:00", "active": True, "description": "Overnight"},
    ]
    timetable = [
        {
            "id": 1,
            "name": "Work",
            "shift_id": 1,
            "start_time": "09:00",
            "end_time": "18:00",
            "type": "Work",
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
            "enabled": True,
            "is_payable": True,
            "rules": {"attendance_enabled": True, "grace_period": 15, "greeting": "Hello"},
        },
        {
            "id": 2,
            "name": "Overtime",
            "shift_id": 1,
            "start_time": "18:00",
            "end_time": "20:00",
            "type": "Work",
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
            "enabled": True,
            "is_payable": True,
            "rules": {"attendance_enabled": True, "grace_period": 0, "greeting": "Good job"},
        },
    ]
    _insert_row(
        conn,
        "companies",
        {
            "id": 1,
            "name": "Demo Company",
            "vendor_id": vendor_id,
            "working_hours": 8.0,
            "shifts": json.dumps(shifts),
            "draft_timetable": json.dumps(timetable),
            "live_timetable": json.dumps(timetable),
            "last_modified_by": "seed_demo_data",
            "last_modified_at": _as_iso(datetime.now()),
            "published_by": "seed_demo_data",
            "published_at": _as_iso(datetime.now()),
        },
    )


def _ensure_faces_and_attendance(conn, vendor_id: int, reg_config: List[Dict[str, Any]]):
    faces_cols = _table_columns(conn, "faces")
    has_id = "id" in faces_cols
    has_custom = "custom_data" in faces_cols
    people = [
        {"name": "Ava Johnson", "department": "Engineering", "designation": "Technician", "shift": "Day Shift", "daily_wage": 120.0},
        {"name": "Noah Patel", "department": "Operations", "designation": "Supervisor", "shift": "Day Shift", "daily_wage": 180.0},
        {"name": "Mia Chen", "department": "Quality", "designation": "Inspector", "shift": "Day Shift", "daily_wage": 150.0},
        {"name": "Liam Garcia", "department": "Security", "designation": "Guard", "shift": "Night Shift", "daily_wage": 140.0},
        {"name": "Sophia Kim", "department": "HR", "designation": "Coordinator", "shift": "Day Shift", "daily_wage": 160.0},
    ]

    inserted = []
    for i, p in enumerate(people, start=1):
        custom_data = {
            "employee_id": f"EMP-{1000+i}",
            "site": random.choice(["Plant A", "Plant B"]),
            "team": random.choice(["Alpha", "Beta", "Gamma"]),
        }
        row = {
            "name": p["name"],
            "templates": json.dumps([f"template_{i}_a", f"template_{i}_b"]),
            "face_image": ONE_BY_ONE_PNG_DATA_URL,
            "department": p["department"],
            "designation": p["designation"],
            "phone": f"+1-555-01{10+i:02d}",
            "shift": p["shift"],
            "daily_wage": p["daily_wage"],
            "late_allowance_days": 2,
            "late_deduction_amount": 10.0,
            "vendor_id": vendor_id,
        }
        if has_custom:
            row["custom_data"] = json.dumps(custom_data)

        if has_id:
            row["id"] = i
            _insert_row(conn, "faces", row)
            inserted.append({"id": i, "name": p["name"], "shift": p["shift"]})
        else:
            _insert_row(conn, "faces", row)
            inserted.append({"id": None, "name": p["name"], "shift": p["shift"]})

    cur = conn.cursor()
    if has_id:
        cur.execute("SELECT id, name FROM faces WHERE vendor_id = ? ORDER BY id ASC", (vendor_id,))
    else:
        cur.execute("SELECT NULL as id, name FROM faces WHERE vendor_id = ? ORDER BY name ASC", (vendor_id,))
    id_by_name = {r[1]: r[0] for r in cur.fetchall()}

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    days = [now.date() - timedelta(days=d) for d in range(0, 14)]
    for day_idx, day in enumerate(days):
        day_start = datetime.combine(day, datetime.min.time()).replace(hour=9)
        for p_idx, p in enumerate(people):
            base = day_start + timedelta(minutes=5 * p_idx)
            is_late = 1 if (day_idx % 4 == 0 and p_idx % 2 == 1) else 0
            check_in = base + timedelta(minutes=40 if is_late else 0)
            check_out = check_in + timedelta(hours=7, minutes=random.choice([10, 25, 40]))
            if p["shift"] == "Night Shift":
                check_in = datetime.combine(day, datetime.min.time()).replace(hour=21, minute=0) + timedelta(minutes=7 * p_idx)
                check_out = check_in + timedelta(hours=8, minutes=random.choice([0, 15, 30]))

            person_id = id_by_name.get(p["name"])
            _insert_row(
                conn,
                "attendance",
                {
                    "name": p["name"],
                    "timestamp": _as_iso(check_in),
                    "status": "CHECK_IN",
                    "activity": "Work",
                    "is_late": is_late,
                    "vendor_id": vendor_id,
                    "person_id": person_id,
                },
            )
            _insert_row(
                conn,
                "attendance",
                {
                    "name": p["name"],
                    "timestamp": _as_iso(check_out),
                    "status": "CHECK_OUT",
                    "activity": "Work",
                    "is_late": 0,
                    "vendor_id": vendor_id,
                    "person_id": person_id,
                },
            )


def _ensure_audit_and_jobs(conn, vendor_id: int):
    for action, details in [
        ("vendor_created", {"seed": True}),
        ("subscription_updated", {"plan_type": "pro"}),
        ("vendor_registration_config_update", {"count": 3}),
    ]:
        _insert_row(
            conn,
            "audit_logs",
            {
                "actor_username": "superadmin",
                "action": action,
                "target_vendor_id": vendor_id,
                "details": json.dumps(details),
                "timestamp": _as_iso(datetime.now()),
            },
        )

    for i, st in enumerate(["SUCCESS", "FAILURE", "STARTED", "SUCCESS", "RETRY"], start=1):
        received = datetime.now(timezone.utc) - timedelta(minutes=30 - (i * 4))
        started = received + timedelta(seconds=5)
        finished = started + timedelta(seconds=random.randint(1, 6)) if st in ("SUCCESS", "FAILURE") else None
        _insert_row(
            conn,
            "task_events",
            {
                "task_id": f"demo-task-{i}",
                "name": random.choice(["sync_faces", "generate_reports", "cleanup_sessions"]),
                "queue": random.choice(["default", "high", "low"]),
                "worker": "seed",
                "status": st,
                "received_at": received.isoformat(),
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat() if finished else None,
                "runtime": (finished - started).total_seconds() if finished else None,
                "retries": 1 if st == "RETRY" else 0,
                "eta": None,
                "args": json.dumps([]),
                "kwargs": json.dumps({}),
                "result": json.dumps({"ok": st == "SUCCESS"}) if st in ("SUCCESS", "FAILURE") else None,
                "error": "demo error" if st == "FAILURE" else None,
            },
        )


def seed(db_path: str, reset: bool):
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, backend_dir)
    os.environ["DB_PATH"] = db_path
    if "app" in sys.modules:
        del sys.modules["app"]
    import importlib
    backend_app = importlib.import_module("app")

    is_pg = bool(backend_app.DATABASE_URL and backend_app.DATABASE_URL.startswith(("postgres://", "postgresql://")))
    if is_pg:
        raise RuntimeError("seed_demo_data.py currently supports SQLite only. Unset DATABASE_URL or set DB_PATH.")

    conn = backend_app.get_db_connection()
    try:
        if hasattr(conn, "row_factory"):
            conn.row_factory = None

        backend_app.ensure_task_events_table()
        try:
            backend_app.add_vendor_devices_table()
        except Exception:
            pass

        if reset:
            for table in [
                "attendance",
                "faces",
                "companies",
                "subscriptions",
                "vendors",
                "vendor_devices",
                "active_sessions",
                "invoices",
                "audit_logs",
                "archive_objects",
                "task_events",
            ]:
                _safe_delete_all(conn, table)
                _safe_reset_sequence(conn, table)

        vendor_id, reg_config = _ensure_vendor_and_subscription(conn, backend_app)
        _ensure_company(conn, vendor_id)
        _ensure_faces_and_attendance(conn, vendor_id, reg_config)
        _ensure_audit_and_jobs(conn, vendor_id)

        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {
        "db_path": db_path,
        "vendor_login": {"username": "demo_admin", "password": "demo123"},
        "superadmin_login": {"username": "superadmin", "password": "super123"},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args()

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = args.db or os.environ.get("DB_PATH") or os.path.join(backend_dir, "face_db.sqlite")
    result = seed(db_path=db_path, reset=not args.no_reset)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
