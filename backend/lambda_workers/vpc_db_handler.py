"""VPC-only maintenance worker.

This module intentionally uses only PostgreSQL. Do not add HTTP, SMTP, Bedrock,
or other public-service calls here; doing so would require NAT or paid endpoints.
"""

from __future__ import annotations

import os

from lambda_workers.worker_common import process_sqs_event
from lambda_workers.report_pipeline import (
    dispatch_due,
    prepare_automated,
    prepare_employee_monthly,
    reconcile_delivery,
)


ORPHAN_CLEANUP = (
    ("attendance", "DELETE FROM attendance WHERE person_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM faces WHERE id = attendance.person_id)"),
    ("student_parents", "DELETE FROM student_parents WHERE NOT EXISTS (SELECT 1 FROM faces WHERE id = student_parents.person_id)"),
    ("person_embeddings", "DELETE FROM person_embeddings WHERE NOT EXISTS (SELECT 1 FROM faces WHERE id = person_embeddings.person_id)"),
    ("system_users", "DELETE FROM system_users WHERE person_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM faces WHERE id = system_users.person_id)"),
)


def _connect():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    import psycopg2

    return psycopg2.connect(
        database_url,
        connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5")),
        application_name="tapinx-vpc-maintenance-lambda",
    )


def cleanup_orphans(_payload):
    conn = _connect()
    counts = {}
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '55s'")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            for name, statement in ORPHAN_CLEANUP:
                cursor.execute(statement)
                counts[name] = cursor.rowcount
            cursor.execute("""
                UPDATE parent_users SET selected_person_id = NULL
                WHERE selected_person_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM faces WHERE id = parent_users.selected_person_id)
            """)
            counts["parent_user_selections"] = cursor.rowcount
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def database_health(_payload):
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            return {"ok": cursor.fetchone()[0] == 1}
    finally:
        conn.close()


PROCESSORS = {
    "maintenance.cleanup_orphans": cleanup_orphans,
    "maintenance.database_health": database_health,
    "reports.prepare_employee_monthly": prepare_employee_monthly,
    "reports.prepare_automated": prepare_automated,
    "reports.dispatch_due": dispatch_due,
    "reports.delivery_result": reconcile_delivery,
}


def handler(event, _context):
    return process_sqs_event(event, PROCESSORS)
