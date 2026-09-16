import sqlite3
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.payroll_service import get_approved_advances, set_vendor_statutory_flags


def test_payroll_advance_query_excludes_pending_and_rejected_requests():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE advances (id INTEGER, person_id INTEGER, amount REAL, deduction_month TEXT, status TEXT)")
    conn.executemany("INSERT INTO advances VALUES (?, ?, ?, ?, ?)", [
        (1, 10, 100, "2026-09", "pending"),
        (2, 10, 200, "2026-09", "approved"),
        (3, 10, 300, "2026-09", "rejected"),
        (4, 10, 400, "2026-10", "approved"),
        (5, 11, 500, "2026-09", "approved"),
    ])

    rows = get_approved_advances(conn, 10, "2026-09")

    assert rows == [(2, 200.0)]
    conn.close()


def test_bulk_statutory_update_is_vendor_scoped():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE faces (id INTEGER, vendor_id INTEGER, pf_enabled INTEGER, esi_enabled INTEGER)"
    )
    conn.executemany("INSERT INTO faces VALUES (?, ?, ?, ?)", [
        (1, 10, 1, 1),
        (2, 10, 1, 1),
        (3, 20, 1, 1),
    ])

    affected = set_vendor_statutory_flags(conn.cursor(), 10, False)
    conn.commit()

    assert affected == 2
    assert conn.execute(
        "SELECT vendor_id, pf_enabled, esi_enabled FROM faces ORDER BY id"
    ).fetchall() == [(10, 0, 0), (10, 0, 0), (20, 1, 1)]
    conn.close()
