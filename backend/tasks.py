from celery_app import celery
from app import get_db_connection, socketio, log_audit, BUNDLE_FEATURES
import json
from datetime import date, timedelta, datetime
import sqlite3

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
