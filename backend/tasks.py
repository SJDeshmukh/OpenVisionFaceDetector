from celery_app import celery
from app import get_db_connection, socketio, log_audit, BUNDLE_FEATURES
import json
from datetime import date, timedelta, datetime
import sqlite3
from celery.signals import task_prerun, task_postrun, task_failure, task_retry, task_received, task_revoked
import os
TASK_EVENTS_MAX = int(os.environ.get("TASK_EVENTS_MAX", "50000"))

if celery:
    @celery.task(name="tasks.process_vendor_creation")
    def process_vendor_creation_task(payload):
        vendor_id = payload["vendor_id"]
        company_name = payload["company_name"]
        frontend_bundle_id = payload.get("frontend_bundle_id", "default_attendance")
        admin_username = payload["admin_username"]
        admin_password = payload["admin_password"]
        user_username = payload["user_username"]
        user_password = payload["user_password"]
        conn2 = get_db_connection()
        c2 = conn2.cursor()
        start_date = payload.get("start_date") or date.today().isoformat()
        end_date = payload.get("end_date") or (date.today() + timedelta(days=14)).isoformat()
        max_users = payload.get("max_users") or 5
        max_employees = payload.get("max_employees") or 50
        max_mobile_devices = payload.get("max_mobile_devices") or max_users
        cost_per_user = payload.get("cost_per_user") or 0
        cost_per_employee = payload.get("cost_per_employee") or 0
        features = payload.get("features") or BUNDLE_FEATURES.get(frontend_bundle_id, [])
        features_json = json.dumps(features)
        c2.execute("""INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, setup_fee, features)
                      VALUES (?, 'custom', ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                   (vendor_id, start_date, end_date, max_users, max_employees, max_mobile_devices, cost_per_user, cost_per_employee, features_json))
        try:
            c2.execute("""INSERT INTO system_users (username, password, role, vendor_id)
                          VALUES (?, ?, 'vendor_admin', ?)""",
                       (admin_username, admin_password, vendor_id))
        except sqlite3.IntegrityError:
            pass
        try:
            c2.execute("""INSERT INTO system_users (username, password, role, vendor_id)
                          VALUES (?, ?, 'user', ?)""",
                       (user_username, user_password, vendor_id))
        except sqlite3.IntegrityError:
            pass
        c2.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)", 
                   (company_name, '[]', '[]', '[]', vendor_id))
        conn2.commit()
        conn2.close()
        log_audit("system", 'create_vendor', vendor_id, {'company_name': company_name})
        socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')

def ensure_task_events_table():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                name TEXT,
                queue TEXT,
                worker TEXT,
                status TEXT,
                received_at DATETIME,
                started_at DATETIME,
                finished_at DATETIME,
                runtime REAL,
                retries INTEGER,
                eta DATETIME,
                args TEXT,
                kwargs TEXT,
                result TEXT,
                error TEXT,
                trace TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_status ON task_events(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_name ON task_events(name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_queue ON task_events(queue)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_finished ON task_events(finished_at)")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

def _store_task_event(payload):
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO task_events (task_id, name, queue, worker, status, received_at, started_at, finished_at, runtime, retries, eta, args, kwargs, result, error, trace)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            payload.get("task_id"), payload.get("name"), payload.get("queue"), payload.get("worker"),
            payload.get("status"), payload.get("received_at"), payload.get("started_at"), payload.get("finished_at"),
            payload.get("runtime"), payload.get("retries"), payload.get("eta"), payload.get("args"),
            payload.get("kwargs"), payload.get("result"), payload.get("error"), payload.get("trace")
        ))
        c.execute("SELECT COUNT(*) FROM task_events")
        row = c.fetchone()
        total = row[0] if row else 0
        if total and int(total) > TASK_EVENTS_MAX:
            to_delete = int(total) - TASK_EVENTS_MAX
            c.execute("DELETE FROM task_events WHERE id IN (SELECT id FROM task_events ORDER BY id ASC LIMIT ?)", (to_delete,))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

@task_received.connect
def _on_task_received(sender=None, headers=None, body=None, **kwargs):
    try:
        _store_task_event({
            "task_id": headers.get("id") if headers else None,
            "name": headers.get("task") if headers else None,
            "queue": headers.get("queue") if headers else None,
            "worker": sender,
            "status": "received",
            "received_at": datetime.utcnow().isoformat(),
            "retries": headers.get("retries", 0) if headers else 0,
            "eta": headers.get("eta") if headers else None,
            "args": json.dumps(body.get("args", [])) if body else None,
            "kwargs": json.dumps(body.get("kwargs", {})) if body else None
        })
    except Exception:
        pass

@task_prerun.connect
def _on_task_prerun(task=None, **kwargs):
    try:
        _store_task_event({
            "task_id": getattr(task.request, "id", None),
            "name": task.name,
            "queue": getattr(task.request, "delivery_info", {}).get("queue"),
            "worker": getattr(task.request, "hostname", None),
            "status": "started",
            "started_at": datetime.utcnow().isoformat(),
            "args": json.dumps(getattr(task.request, "args", [])),
            "kwargs": json.dumps(getattr(task.request, "kwargs", {}))
        })
    except Exception:
        pass

@task_postrun.connect
def _on_task_postrun(task=None, retval=None, state=None, **kwargs):
    try:
        _store_task_event({
            "task_id": getattr(task.request, "id", None),
            "name": task.name,
            "queue": getattr(task.request, "delivery_info", {}).get("queue"),
            "worker": getattr(task.request, "hostname", None),
            "status": state or "success",
            "finished_at": datetime.utcnow().isoformat(),
            "runtime": getattr(task.request, "runtime", None),
            "result": json.dumps(retval) if retval is not None else None
        })
    except Exception:
        pass

@task_failure.connect
def _on_task_failure(task_id=None, exception=None, traceback=None, einfo=None, sender=None, **kwargs):
    try:
        _store_task_event({
            "task_id": task_id,
            "name": getattr(sender, "name", None),
            "worker": getattr(sender.request, "hostname", None) if hasattr(sender, "request") else None,
            "status": "failure",
            "finished_at": datetime.utcnow().isoformat(),
            "error": str(exception) if exception else None,
            "trace": str(traceback) if traceback else None
        })
    except Exception:
        pass

@task_retry.connect
def _on_task_retry(request=None, reason=None, einfo=None, **kwargs):
    try:
        _store_task_event({
            "task_id": getattr(request, "id", None),
            "name": getattr(request, "task", None),
            "worker": getattr(request, "hostname", None),
            "status": "retry",
            "finished_at": datetime.utcnow().isoformat(),
            "retries": getattr(request, "retries", 1),
            "error": str(reason) if reason else None
        })
    except Exception:
        pass
