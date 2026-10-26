import sqlite3
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.display_id_service import (  # noqa: E402
    compact_all_vendor_display_ids,
    compact_vendor_display_ids,
)


def _database():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            display_id INTEGER
        );
        CREATE TABLE face_sync_changes (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            operation TEXT NOT NULL
        );
        CREATE TRIGGER faces_changed AFTER UPDATE ON faces BEGIN
            INSERT INTO face_sync_changes(vendor_id, person_id, operation)
            VALUES (NEW.vendor_id, NEW.id, 'UPDATE');
        END;
    """)
    return conn


def test_compaction_closes_gap_and_records_changed_people_for_sync():
    conn = _database()
    conn.executemany(
        "INSERT INTO faces(id, vendor_id, display_id) VALUES (?, 7, ?)",
        [(101, 2), (102, 3), (103, 4)],
    )

    changed = compact_vendor_display_ids(conn, 7)
    conn.commit()

    assert changed == [
        {"person_id": 101, "display_id": 1},
        {"person_id": 102, "display_id": 2},
        {"person_id": 103, "display_id": 3},
    ]
    assert conn.execute(
        "SELECT id, display_id FROM faces WHERE vendor_id = 7 ORDER BY display_id"
    ).fetchall() == [(101, 1), (102, 2), (103, 3)]
    assert conn.execute(
        "SELECT person_id, operation FROM face_sync_changes ORDER BY seq"
    ).fetchall() == [(101, "UPDATE"), (102, "UPDATE"), (103, "UPDATE")]

    assert compact_vendor_display_ids(conn, 7) == []
    assert conn.execute("SELECT COUNT(*) FROM face_sync_changes").fetchone()[0] == 3
    conn.close()


def test_compaction_is_vendor_scoped_and_repairs_null_or_duplicate_ids():
    conn = _database()
    conn.executemany(
        "INSERT INTO faces(id, vendor_id, display_id) VALUES (?, ?, ?)",
        [(1, 7, 1), (2, 7, 3), (3, 7, 3), (4, 8, 9), (5, 7, None)],
    )

    changed = compact_all_vendor_display_ids(conn)
    conn.commit()

    assert changed == {
        7: [
            {"person_id": 2, "display_id": 2},
            {"person_id": 5, "display_id": 4},
        ],
        8: [{"person_id": 4, "display_id": 1}],
    }
    assert conn.execute(
        "SELECT display_id FROM faces WHERE vendor_id = 7 ORDER BY display_id"
    ).fetchall() == [(1,), (2,), (3,), (4,)]
    assert conn.execute(
        "SELECT display_id FROM faces WHERE vendor_id = 8"
    ).fetchone()[0] == 1
    conn.close()
