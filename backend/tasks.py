try:
    from celery_app import celery
    from celery.signals import task_prerun, task_postrun, task_failure, task_retry, task_received, task_revoked
except Exception:
    celery = None
    class _DummySignal:
        def connect(self, func):
            return func
    task_prerun = task_postrun = task_failure = task_retry = task_received = task_revoked = _DummySignal()

try:
    from backend.utils import get_db_connection, log_audit, BUNDLE_FEATURES, redis_client
except Exception:
    from utils import get_db_connection, log_audit, BUNDLE_FEATURES, redis_client

def _get_socketio():
    """Lazy-load socketio so the Celery worker doesn't bootstrap the full Flask app on import."""
    try:
        from app import socketio as _sio
        return _sio
    except Exception:
        try:
            from backend.app import socketio as _sio
            return _sio
        except Exception:
            return None
import json
from datetime import date, timedelta, datetime
import sqlite3
import os
import base64
import hashlib

TASK_EVENTS_MAX = int(os.environ.get("TASK_EVENTS_MAX", "50000"))
TASK_EVENT_VALUE_MAX = int(os.environ.get("TASK_EVENT_VALUE_MAX", "2048"))


def _event_json(value):
    """Serialize task metadata without persisting images, tokens, or huge payloads."""
    def summarize(item, depth=0):
        if depth > 4:
            return "<max-depth>"
        if isinstance(item, str):
            if item.startswith("data:image/") or len(item) > TASK_EVENT_VALUE_MAX:
                return f"<redacted-string length={len(item)}>"
            return item
        if isinstance(item, dict):
            return {
                str(key): ("<redacted>" if any(secret in str(key).lower() for secret in
                    ("password", "secret", "token", "authorization", "image", "apk"))
                    else summarize(val, depth + 1))
                for key, val in list(item.items())[:100]
            }
        if isinstance(item, (list, tuple)):
            return [summarize(val, depth + 1) for val in list(item)[:100]]
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return str(item)[:TASK_EVENT_VALUE_MAX]

    try:
        return json.dumps(summarize(value), default=str)
    except Exception:
        return '"<unserializable>"'

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
        try:
            max_web_sessions = int(payload.get("max_web_sessions") or 1)
        except Exception:
            max_web_sessions = 1
        if max_web_sessions < 1:
            max_web_sessions = 1
        cost_per_user = payload.get("cost_per_user") or 0
        cost_per_employee = payload.get("cost_per_employee") or 0
        features = payload.get("features") or BUNDLE_FEATURES.get(frontend_bundle_id, [])
        features_json = json.dumps(features)
        try:
            # Use INSERT OR IGNORE for all three to ensure task is re-runnable/robust
            c2.execute("""INSERT OR IGNORE INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, setup_fee, features)
                          VALUES (?, 'custom', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                       (vendor_id, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, features_json))
            
            c2.execute("""INSERT OR IGNORE INTO system_users (username, password, role, vendor_id)
                          VALUES (?, ?, 'vendor_admin', ?)""",
                       (admin_username, admin_password, vendor_id))
            
            c2.execute("""INSERT OR IGNORE INTO system_users (username, password, role, vendor_id)
                          VALUES (?, ?, 'user', ?)""",
                       (user_username, user_password, vendor_id))
            
            c2.execute("INSERT OR IGNORE INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)", 
                       (company_name, '[]', '[]', '[]', vendor_id))
            
            conn2.commit()
            log_audit('create_vendor', details={'company_name': company_name}, target_vendor_id=vendor_id, actor="system")
            _sio = _get_socketio()
            if _sio:
                _sio.emit('force_logout', {'vendor_id': vendor_id, 'reason': 'Vendor account deleted'}, room=f"vendor_{vendor_id}")
                _sio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
        except Exception as e:
            if conn2: conn2.rollback()
            print(f"Error in process_vendor_creation_task: {e}")
            raise e
        finally:
            if conn2: conn2.close()

def process_delete_vendor_task(vendor_id):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        placeholder = "%s" if is_pg else "?"
        
        def safe_delete(table, key="vendor_id"):
            try:
                if is_pg:
                    c.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)", (table,))
                    row = c.fetchone()
                    if not row or not row[0]: return
                else:
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    if not c.fetchone(): return
                
                c.execute(f"DELETE FROM {table} WHERE {key} = {placeholder}", (vendor_id,))
            except Exception as e:
                print(f"Error deleting from {table}: {e}")

        delete_steps = [
            # 1. Sub-child items
            ("class_batch_items", f"DELETE FROM class_batch_items WHERE batch_id IN (SELECT id FROM class_batches WHERE vendor_id = {placeholder})", (vendor_id,)),
            ("registration_batch_items", f"DELETE FROM registration_batch_items WHERE batch_id IN (SELECT id FROM registration_batches WHERE vendor_id = {placeholder})", (vendor_id,)),
            ("lecture_attendance", f"DELETE FROM lecture_attendance WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("automated_report_deliveries", f"DELETE FROM automated_report_deliveries WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("xchat_messages", f"DELETE FROM xchat_messages WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("xchat_token_usage", f"DELETE FROM xchat_token_usage WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("advance_revisions", f"DELETE FROM advance_revisions WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 2. Tables referencing faces or parent_users
            ("advances", f"DELETE FROM advances WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("leave_requests", f"DELETE FROM leave_requests WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("person_embeddings", f"DELETE FROM person_embeddings WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("attendance", f"DELETE FROM attendance WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("student_parents", f"DELETE FROM student_parents WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("face_reset_requests", f"DELETE FROM face_reset_requests WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 3. Parent user tokens & users
            ("parent_tokens", f"DELETE FROM parent_tokens WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("parent_users", f"DELETE FROM parent_users WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 4. System users
            ("system_users", f"DELETE FROM system_users WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 5. Faces (all tables referencing faces are deleted!)
            ("faces", f"DELETE FROM faces WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 6. Intermediate parent tables
            ("class_batches", f"DELETE FROM class_batches WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("registration_batches", f"DELETE FROM registration_batches WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("lectures", f"DELETE FROM lectures WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("automated_report_schedules", f"DELETE FROM automated_report_schedules WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("xchat_conversations", f"DELETE FROM xchat_conversations WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 7. Remaining vendor-direct tables
            ("classes", f"DELETE FROM classes WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("subject_master", f"DELETE FROM subject_master WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("class_thresholds", f"DELETE FROM class_thresholds WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("bulk_attendance_config", f"DELETE FROM bulk_attendance_config WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("leave_staff", f"DELETE FROM leave_staff WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("vendor_device_slots", f"DELETE FROM vendor_device_slots WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("vendor_devices", f"DELETE FROM vendor_devices WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("active_sessions", f"DELETE FROM active_sessions WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("invoices", f"DELETE FROM invoices WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("subscriptions", f"DELETE FROM subscriptions WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("companies", f"DELETE FROM companies WHERE vendor_id = {placeholder}", (vendor_id,)),
            ("audit_logs", f"DELETE FROM audit_logs WHERE target_vendor_id = {placeholder}", (vendor_id,)),
            ("archive_objects", f"DELETE FROM archive_objects WHERE vendor_id = {placeholder}", (vendor_id,)),

            # 8. Finally, the vendor itself
            ("vendors", f"DELETE FROM vendors WHERE id = {placeholder}", (vendor_id,)),
        ]

        for table_name, sql, params in delete_steps:
            try:
                if is_pg:
                    c.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)", (table_name,))
                    row = c.fetchone()
                    if not row or not row[0]:
                        continue
                else:
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                    if not c.fetchone():
                        continue

                c.execute(sql, params)
            except Exception as e:
                print(f"Error deleting from {table_name}: {e}")
                if table_name == "vendors":
                    raise e

        # 8. Commit the deletion FIRST so it's permanent
        conn.commit()
        
        # 9. Invalidate admin stats cache so the numbers update immediately
        from utils import cache_delete
        cache_delete("admin_stats")
        
        # 10. Reset sequences if no vendors left
        try:
            c.execute("SELECT COUNT(*) FROM vendors")
            row = c.fetchone()
            count = row[0] if row else 0
            if count == 0:
                is_pg = getattr(conn, "_is_pg", False)
                tables = [
                    "class_batches", "attendance", "leave_requests", "student_parents", 
                    "person_embeddings", "system_users", "parent_tokens", "parent_users", 
                    "faces", "leave_staff", "xchat_messages", "xchat_conversations", "vendor_device_slots", "vendor_devices",
                    "active_sessions", "invoices", "subscriptions", "companies", "audit_logs", "vendors"
                ]
                for t in tables:
                    try:
                        if is_pg:
                            # Postgres: Check if 'id' column exists first
                            c.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}' AND column_name='id'")
                            if c.fetchone():
                                c.execute(f"SELECT pg_get_serial_sequence('{t}', 'id')")
                                seq_row = c.fetchone()
                                if seq_row and seq_row[0]:
                                    seq_name = seq_row[0]
                                    c.execute(f"ALTER SEQUENCE {seq_name} RESTART WITH 1")
                                    conn.commit()
                        else:
                            # SQLite
                            c.execute(f"DELETE FROM sqlite_sequence WHERE name='{t}'")
                            conn.commit()
                    except Exception:
                        if conn: conn.rollback()
                        pass
        except Exception:
            pass

        # No audit log for the vendor deletion itself as we've deleted all logs for this vendor!
        # Actually, maybe we should log it but without target_vendor_id?
        # Let's log it globally.
        _sio = _get_socketio()
        if _sio:
            _sio.emit('force_logout', {'vendor_id': vendor_id, 'reason': 'Vendor account deleted'}, room=f"vendor_{vendor_id}")
            _sio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
            _sio.emit('admin_stats_updated', room='super_admin')
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error in delete_vendor_task: {e}")
    finally:
        if conn: conn.close()

if celery:
    process_delete_vendor_task = celery.task(name="tasks.process_delete_vendor")(process_delete_vendor_task)


if celery:
    @celery.task(name="tasks.dispatch_automated_reports")
    def dispatch_automated_reports_task():
        """Beat entrypoint. Claim due delivery rows before queueing to stay idempotent."""
        from services.automated_reports_service import dispatch_due_reports
        delivery_ids = dispatch_due_reports()
        for delivery_id in delivery_ids:
            send_automated_report_task.apply_async(args=[delivery_id], queue="reports")
        return {"queued": len(delivery_ids), "delivery_ids": delivery_ids}


    @celery.task(name="tasks.send_employee_monthly_reports")
    def send_employee_monthly_reports_task(vendor_id, month, person_type=None, filters=None):
        from services.employee_email_reports_service import send_employee_monthly_reports
        return send_employee_monthly_reports(vendor_id, month, person_type, filters=filters)


    @celery.task(name="tasks.send_advance_notification")
    def send_advance_notification_task(advance_id, event):
        from services.employee_email_reports_service import send_advance_notification
        return send_advance_notification(advance_id, event)


    @celery.task(bind=True, name="tasks.deliver_parent_notification", max_retries=3)
    def deliver_parent_notification_task(self, person_id, vendor_id, title, body, data=None):
        from notifications import notify_parent_async
        try:
            return notify_parent_async(
                person_id, vendor_id, title, body, data or {},
                _local=True, _wait=True,
            )
        except Exception as exc:
            raise self.retry(exc=exc, countdown=min(300, 5 * (2 ** self.request.retries)))


    @celery.task(bind=True, name="tasks.send_automated_report", max_retries=3)
    def send_automated_report_task(self, delivery_id):
        from services.automated_reports_service import build_report_attachments, _json_list
        from services.email_service import send_email

        conn = get_db_connection()
        c = conn.cursor()
        try:
            c.execute("""
                SELECT d.*, ars.operational_day_cutoff, ars.report_types,
                       ars.enabled AS schedule_enabled, v.company_name, v.status AS vendor_status,
                       s.features
                FROM automated_report_deliveries d
                JOIN automated_report_schedules ars ON ars.id = d.schedule_id
                JOIN vendors v ON v.id = d.vendor_id
                LEFT JOIN subscriptions s ON s.vendor_id = d.vendor_id
                WHERE d.id = ?
            """, (delivery_id,))
            raw = c.fetchone()
            if not raw:
                return {"status": "missing"}
            delivery = dict(raw)
            if delivery.get("status") == "sent":
                return {"status": "already_sent"}
            features = _json_list(delivery.get("features"))
            is_test = str(delivery.get("frequency") or "").startswith("test-")
            if (not delivery.get("schedule_enabled") and not is_test) or delivery.get("vendor_status") != "active" or "automated_email_reports" not in features:
                c.execute("UPDATE automated_report_deliveries SET status = 'skipped', error = ? WHERE id = ?", ("Schedule, vendor, or feature is inactive", delivery_id))
                conn.commit()
                return {"status": "skipped"}
            c.execute("UPDATE automated_report_deliveries SET status = 'sending', attempts = COALESCE(attempts, 0) + 1, error = NULL WHERE id = ?", (delivery_id,))
            conn.commit()
        finally:
            conn.close()

        try:
            start = datetime.fromisoformat(str(delivery["period_start"])).date()
            end = datetime.fromisoformat(str(delivery["period_end"])).date()
            vendor_name, attachments, event_count = build_report_attachments(
                delivery["vendor_id"], start, end,
                delivery.get("operational_day_cutoff") or "07:00",
                _json_list(delivery.get("report_types")),
            )
            frequency_label = "Test" if str(delivery["frequency"]).startswith("test-") else str(delivery["frequency"]).title()
            subject = f"{vendor_name} — {frequency_label} attendance report ({start} to {end})"
            body = (
                f"Hello {vendor_name},\n\n"
                f"Your automated {frequency_label.lower()} attendance report for {start} to {end} is attached.\n"
                f"The report contains {event_count} attendance events and uses your operational-day cutoff, so overnight shifts remain together.\n\n"
                "Regards,\nOpenVisionX Reports"
            )
            message_id = send_email(subject, body, delivery["recipient_email"], attachments)
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE automated_report_deliveries SET status = 'sent', sent_at = CURRENT_TIMESTAMP, message_id = ?, error = NULL WHERE id = ?", (message_id, delivery_id))
            conn.commit()
            conn.close()
            return {"status": "sent", "message_id": message_id, "event_count": event_count}
        except Exception as exc:
            conn = get_db_connection()
            c = conn.cursor()
            final_attempt = self.request.retries >= self.max_retries
            c.execute("UPDATE automated_report_deliveries SET status = ?, error = ? WHERE id = ?", ("failed" if final_attempt else "queued", str(exc)[:2000], delivery_id))
            conn.commit()
            conn.close()
            if final_attempt:
                raise
            raise self.retry(exc=exc, countdown=min(900, 60 * (2 ** self.request.retries)))

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
        # Stringify all payload fields to avoid adapt issues with complex objects (like Celery's Consumer)
        task_id = str(payload.get("task_id")) if payload.get("task_id") is not None else None
        name = str(payload.get("name")) if payload.get("name") is not None else None
        queue = str(payload.get("queue")) if payload.get("queue") is not None else None
        worker = str(payload.get("worker")) if payload.get("worker") is not None else None
        status = str(payload.get("status")) if payload.get("status") is not None else None
        args = str(payload.get("args")) if payload.get("args") is not None else None
        kwargs = str(payload.get("kwargs")) if payload.get("kwargs") is not None else None
        result = str(payload.get("result")) if payload.get("result") is not None else None
        error = str(payload.get("error")) if payload.get("error") is not None else None
        trace = str(payload.get("trace")) if payload.get("trace") is not None else None
        
        c.execute("""INSERT INTO task_events (task_id, name, queue, worker, status, received_at, started_at, finished_at, runtime, retries, eta, args, kwargs, result, error, trace)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            task_id, name, queue, worker, status, 
            payload.get("received_at"), payload.get("started_at"), payload.get("finished_at"),
            payload.get("runtime"), payload.get("retries"), payload.get("eta"), 
            args, kwargs, result, error, trace
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
            "worker": str(sender),
            "status": "received",
            "received_at": datetime.utcnow().isoformat(),
            "retries": headers.get("retries", 0) if headers else 0,
            "eta": headers.get("eta") if headers else None,
            "args": _event_json(body.get("args", [])) if body else None,
            "kwargs": _event_json(body.get("kwargs", {})) if body else None
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
            "args": _event_json(getattr(task.request, "args", [])),
            "kwargs": _event_json(getattr(task.request, "kwargs", {}))
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
            "result": _event_json(retval) if retval is not None else None
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


def _reconcile_class_batch_identities(batch_id, vendor_id, params):
    """Aggregate repeated faces across every completed image in a class batch."""
    import base64
    import os
    import numpy as np
    from services.batch_recognition import (
        classify_face_decision,
        complete_linkage_clusters,
        enforce_unique_predictions,
    )
    from services.face_service import _ensure_vendor_emb_cache, _suggest_from_cache

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, faces_json FROM class_batch_items WHERE batch_id = ? AND status = 'done' ORDER BY seq ASC",
        (batch_id,),
    )
    rows = c.fetchall() or []
    item_faces = []
    records = []
    for row in rows:
        item_id = str(row[0])
        try:
            faces = json.loads(row[1] or "[]")
        except Exception:
            faces = []
        item_faces.append((item_id, faces))
        for face in faces:
            try:
                encoded = face.get("emb_vec") or ""
                raw = base64.b64decode(encoded, validate=True)
                embedding = np.frombuffer(raw, dtype=np.float32).copy()
                if embedding.size == 0:
                    continue
                records.append({
                    "item_id": item_id,
                    "face_index": int(face.get("index", 0)),
                    "embedding": embedding,
                    "sharpness": face.get("sharpness"),
                    "score": face.get("score"),
                    "pose_yaw": face.get("pose_yaw"),
                    "face": face,
                })
            except Exception:
                continue

    if not records:
        conn.close()
        return

    try:
        cluster_threshold = float(os.environ.get("BATCH_CLUSTER_THRESHOLD", "0.86"))
    except (TypeError, ValueError):
        cluster_threshold = 0.86
    cluster_threshold = min(0.99, max(0.50, cluster_threshold))
    clusters = complete_linkage_clusters(records, threshold=cluster_threshold)

    class_year = params.get("class_year")
    division = params.get("division")
    branch = params.get("branch")
    cache = _ensure_vendor_emb_cache(
        vendor_id,
        class_year=class_year,
        division=division,
        branch=branch,
        person_type="student",
    )

    all_faces = []
    for cluster in clusters:
        suggestions = _suggest_from_cache(
            cluster["centroid"], cache, topk=3,
            class_year=class_year, division=division, branch=branch,
        )
        for member in cluster["members"]:
            face = member["face"]
            min_sim = float(face.get("min_sim") or 0.0)
            face_suggestions = [dict(candidate) for candidate in suggestions
                                if float(candidate.get("similarity", 0.0)) >= min_sim]
            face["suggestions"] = face_suggestions
            face["cluster_id"] = cluster["cluster_id"]
            face["cluster_observations"] = cluster["observations"]
            face["recognition_decision"] = classify_face_decision(face, face_suggestions)
            face["item_id"] = member["item_id"]
            all_faces.append(face)

    enforce_unique_predictions(all_faces)
    for face in all_faces:
        face.pop("item_id", None)

    for item_id, faces in item_faces:
        c.execute(
            "UPDATE class_batch_items SET faces_json = ? WHERE id = ? AND batch_id = ?",
            (json.dumps(faces), item_id, batch_id),
        )
    conn.commit()
    conn.close()


def process_class_batch_items(batch_id, vendor_id, params):
    from services.face_service import _detect_faces_from_bytes
    from utils import get_db_connection
    from concurrent.futures import ThreadPoolExecutor
    import base64
    import time
    import os

    # Batch attendance always uses fast mode — skip GFPGAN/RealESRGAN enhancement
    params = dict(params or {})
    params['fast'] = True

    # Read all pending items up-front with one connection
    _conn = get_db_connection()
    _c = _conn.cursor()
    _c.execute(
        "SELECT id, image_b64 FROM class_batch_items WHERE batch_id = ? AND status = 'pending' ORDER BY seq ASC",
        (batch_id,)
    )
    items = _c.fetchall()
    _conn.close()

    total = len(items)
    print(f"[CELERY] process_class_batch_items: batch {batch_id} has {total} items pending.", flush=True)

    def _process_item(item):
        """Runs in its own thread with its own DB connection."""
        item_id, img_b64 = item[0], item[1]
        iconn = get_db_connection()
        ic = iconn.cursor()
        try:
            ic.execute("UPDATE class_batch_items SET status = 'processing' WHERE id = ?", (item_id,))
            iconn.commit()
            header, encoded = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
            raw = base64.b64decode(encoded)
            t0 = time.time()
            faces, annotated_b64 = _detect_faces_from_bytes(raw, params, vendor_id)
            t1 = time.time()
            print(
                f"[CELERY] batch {batch_id} item {item_id} done in {t1-t0:.3f}s "
                f"({len(faces)} faces)", flush=True
            )
            del raw; import gc; gc.collect()
            ic.execute(
                "UPDATE class_batch_items SET faces_json = ?, annotated_b64 = ?, status = 'done' WHERE id = ?",
                (json.dumps(faces), annotated_b64, item_id)
            )
            iconn.commit()
        except Exception as exc:
            print(f"[CELERY] batch {batch_id} item {item_id} FAILED: {exc}", flush=True)
            try:
                ic.execute(
                    "UPDATE class_batch_items SET status = 'failed', faces_json = '[]', annotated_b64 = ? WHERE id = ?",
                    (f"Error: {exc}", item_id)
                )
                iconn.commit()
            except Exception:
                pass
        finally:
            iconn.close()

    # 2 workers on 2-vCPU box: model locks serialize inference, I/O runs in parallel
    _workers = min(total, int(os.environ.get("BATCH_WORKERS", "2")))
    if _workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=_workers) as pool:
            list(pool.map(_process_item, items))
    else:
        for item in items:
            _process_item(item)

    # Recognition is deliberately reconciled after all image workers finish.
    # This lets repeated appearances contribute one quality-weighted identity
    # decision instead of treating each uploaded photograph in isolation.
    try:
        _reconcile_class_batch_identities(batch_id, vendor_id, params)
    except Exception as exc:
        print(f"[BATCH_RECOGNITION] batch {batch_id} reconciliation failed: {exc}", flush=True)

    # Mark batch completed if nothing is left pending/processing
    _conn2 = get_db_connection()
    _c2 = _conn2.cursor()
    _c2.execute(
        "SELECT COUNT(*) FROM class_batch_items WHERE batch_id = ? AND status IN ('pending', 'processing')",
        (batch_id,)
    )
    remaining = _c2.fetchone()[0]
    if remaining == 0:
        _c2.execute("UPDATE class_batches SET status = 'completed' WHERE id = ?", (batch_id,))
        _conn2.commit()
    _conn2.close()

if celery:
    process_class_batch_items = celery.task(name="tasks.process_class_batch_items")(process_class_batch_items)

def process_registration_batch_items(batch_id, vendor_id, params):
    from services.face_service import _detect_faces_from_bytes
    from utils import get_db_connection
    from concurrent.futures import ThreadPoolExecutor
    import base64
    import time
    import os

    _conn = get_db_connection()
    _c = _conn.cursor()
    _c.execute(
        "SELECT id, image_b64 FROM registration_batch_items WHERE batch_id = ? AND status = 'pending' ORDER BY seq ASC",
        (batch_id,)
    )
    items = _c.fetchall()
    _conn.close()

    total = len(items)
    print(f"[CELERY] process_registration_batch_items: batch {batch_id} has {total} items pending.", flush=True)

    def _process_item(item):
        item_id, img_b64 = item[0], item[1]
        iconn = get_db_connection()
        ic = iconn.cursor()
        try:
            ic.execute("UPDATE registration_batch_items SET status = 'processing' WHERE id = ?", (item_id,))
            iconn.commit()
            header, encoded = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
            raw = base64.b64decode(encoded)
            t0 = time.time()
            faces, annotated_b64 = _detect_faces_from_bytes(raw, params, vendor_id)
            t1 = time.time()
            print(
                f"[CELERY] reg batch {batch_id} item {item_id} done in {t1-t0:.3f}s "
                f"({len(faces)} faces)", flush=True
            )
            del raw; import gc; gc.collect()
            ic.execute(
                "UPDATE registration_batch_items SET faces_json = ?, annotated_b64 = ?, status = 'done' WHERE id = ?",
                (json.dumps(faces), annotated_b64, item_id)
            )
            iconn.commit()
        except Exception as exc:
            print(f"[CELERY] reg batch {batch_id} item {item_id} FAILED: {exc}", flush=True)
            try:
                ic.execute(
                    "UPDATE registration_batch_items SET status = 'failed', faces_json = '[]', annotated_b64 = ? WHERE id = ?",
                    (f"Error: {exc}", item_id)
                )
                iconn.commit()
            except Exception:
                pass
        finally:
            iconn.close()

    _workers = min(total, int(os.environ.get("BATCH_WORKERS", "2")))
    if _workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=_workers) as pool:
            list(pool.map(_process_item, items))
    else:
        for item in items:
            _process_item(item)

    _conn2 = get_db_connection()
    _c2 = _conn2.cursor()
    _c2.execute(
        "SELECT COUNT(*) FROM registration_batch_items WHERE batch_id = ? AND status IN ('pending', 'processing')",
        (batch_id,)
    )
    remaining = _c2.fetchone()[0]
    if remaining == 0:
        _c2.execute("UPDATE registration_batches SET status = 'completed' WHERE id = ?", (batch_id,))
        _conn2.commit()
    _conn2.close()

if celery:
    process_registration_batch_items = celery.task(name="tasks.process_registration_batch_items")(process_registration_batch_items)

def refresh_class_batch_items(batch_id, vendor_id, params):
    from services.face_service import _detect_faces_from_bytes
    from utils import get_db_connection
    import base64
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, image_b64 FROM class_batch_items WHERE batch_id = ? ORDER BY seq ASC", (batch_id,))
    items = c.fetchall()
    for item in items:
        item_id, img_b64 = item[0], item[1]
        try:
            c.execute("UPDATE class_batch_items SET status = 'processing' WHERE id = ?", (item_id,))
            conn.commit()
            header, encoded = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
            raw = base64.b64decode(encoded)
            faces, annotated_b64 = _detect_faces_from_bytes(raw, params, vendor_id)
            c.execute(
                "UPDATE class_batch_items SET faces_json = ?, annotated_b64 = ?, status = 'done' WHERE id = ?",
                (json.dumps(faces), annotated_b64, item_id)
            )
            conn.commit()
        except Exception as e:
            c.execute(
                "UPDATE class_batch_items SET status = 'failed', faces_json = '[]', annotated_b64 = ? WHERE id = ?",
                (f"Error: {str(e)}", item_id)
            )
            conn.commit()
    conn.close()

if celery:
    refresh_class_batch_items = celery.task(name="tasks.refresh_class_batch_items")(refresh_class_batch_items)

def detect_faces_task(img_b64, params, vendor_id):
    from services.face_service import _detect_faces_from_bytes
    from services.task_payload_service import resolve_image_payload
    if not img_b64:
        return {"faces": [], "annotated_b64": ""}
    img_b64, cleanup_payload = resolve_image_payload(img_b64)
    header, encoded = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
    raw = base64.b64decode(encoded)
    # Cache key materials
    enhancer = (params or {}).get('enhancer') or "GFPGAN"
    crop_mode = (params or {}).get('crop_mode') or "Portrait"
    gfp_up = int((params or {}).get('gfpgan_upscale') or 1)
    preclean_whole = bool((params or {}).get('preclean_whole') or False)
    preclean_level = float((params or {}).get('preclean_level') or 0.2)
    img_hash = hashlib.sha256(raw).hexdigest()
    cache_key = f"detect:v1:{vendor_id}:{enhancer}:{gfp_up}:{crop_mode}:{int(preclean_whole)}:{preclean_level}:{img_hash}"
    cache_ttl = int(os.environ.get("DETECT_CACHE_TTL", "300"))
    # Try cache hit in worker (optional second chance)
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                if cleanup_payload:
                    cleanup_payload()
                return json.loads(cached)
        except Exception:
            pass
    faces, annotated_b64 = _detect_faces_from_bytes(raw, params or {}, vendor_id)
    resp = {"faces": faces, "annotated_b64": annotated_b64}
    if redis_client:
        try:
            redis_client.setex(cache_key, cache_ttl, json.dumps(resp))
        except Exception:
            pass
    if cleanup_payload:
        cleanup_payload()
    return resp

if celery:
    detect_faces_task = celery.task(name="tasks.detect_faces")(detect_faces_task)

def search_embedding_task(img_b64, params, vendor_id):
    from services.face_service import _detect_faces_from_bytes
    from services.task_payload_service import resolve_image_payload
    import base64
    
    if not img_b64:
        return {"faces": [], "annotated_b64": ""}
        
    try:
        img_b64, cleanup_payload = resolve_image_payload(img_b64)
        header, encoded = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
        raw = base64.b64decode(encoded)
        faces, annotated_b64 = _detect_faces_from_bytes(raw, params or {}, vendor_id)
        if cleanup_payload:
            cleanup_payload()
        return {"faces": faces, "annotated_b64": annotated_b64, "status": "done"}
    except Exception as e:
        return {"error": str(e), "status": "failed"}

if celery:
    search_embedding_task = celery.task(name="tasks.search_embedding")(search_embedding_task)


# ── Model pre-warming ────────────────────────────────────────────────────────
# Load all ML models when the worker process starts, BEFORE accepting any task.
# Without this, the first batch task triggers a 14-16s cold-start penalty.
from celery.signals import worker_ready

@worker_ready.connect
def _pre_warm_models(sender=None, **kwargs):
    import time as _t0_mod
    import os as _os
    import sys as _sys
    if _os.environ.get("PREWARM_AI_MODELS", "1").strip().lower() not in {"1", "true", "yes"}:
        print("[WORKER] AI model pre-warming disabled for this worker", flush=True)
        return
    _os.environ.setdefault("FORCE_3D_ENGINE", "1")
    BASE = "/home/ubuntu/OpenVisionFaceDetector"
    for _p in [BASE + "/backend", BASE]:
        if _p not in _sys.path:
            _sys.path.insert(0, _p)
    _t0 = _t0_mod.time()
    print("[WORKER] Pre-warming ML models...", flush=True)
    try:
        from multiple_face_detection.app import get_retina_det, get_realtime_engine, get_embedder
        get_retina_det()
        print(f"[WORKER] RetinaFace ready ({_t0_mod.time()-_t0:.1f}s)", flush=True)
        get_realtime_engine()
        print(f"[WORKER] 3D engine ready ({_t0_mod.time()-_t0:.1f}s)", flush=True)
        get_embedder()._load()
        print(f"[WORKER] All models hot in {_t0_mod.time()-_t0:.1f}s — tasks will start fast", flush=True)
    except Exception:
        import traceback as _tb
        print(f"[WORKER] Pre-warm error:\n{_tb.format_exc()}", flush=True)
