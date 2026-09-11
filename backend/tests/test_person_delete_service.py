import sqlite3
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.person_delete_service import delete_person_dependencies  # noqa: E402


def test_delete_person_dependencies_removes_advances_before_face():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER);
        CREATE TABLE advances (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER REFERENCES faces(id));
        CREATE TABLE advance_revisions (id INTEGER PRIMARY KEY, advance_id INTEGER, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER REFERENCES faces(id));
        CREATE TABLE student_parents (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER REFERENCES faces(id));
        CREATE TABLE parent_users (id INTEGER PRIMARY KEY, vendor_id INTEGER, selected_person_id INTEGER);
        CREATE TABLE leave_requests (id INTEGER PRIMARY KEY, vendor_id INTEGER, student_id INTEGER REFERENCES faces(id));
        CREATE TABLE lecture_attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER REFERENCES faces(id));
        CREATE TABLE person_embeddings (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER REFERENCES faces(id));
        CREATE TABLE system_users (username TEXT PRIMARY KEY, vendor_id INTEGER, person_id INTEGER REFERENCES faces(id));
        CREATE TABLE active_sessions (token TEXT PRIMARY KEY, vendor_id INTEGER, username TEXT);

        INSERT INTO faces VALUES (1, 7);
        INSERT INTO advances VALUES (11, 7, 1);
        INSERT INTO advance_revisions VALUES (12, 11, 7, 1);
        INSERT INTO attendance VALUES (13, 7, 1);
        INSERT INTO student_parents VALUES (14, 7, 1);
        INSERT INTO parent_users VALUES (15, 7, 1);
        INSERT INTO leave_requests VALUES (16, 7, 1);
        INSERT INTO lecture_attendance VALUES (17, 7, 1);
        INSERT INTO person_embeddings VALUES (18, 7, 1);
        INSERT INTO system_users VALUES ('employee-1', 7, 1);
        INSERT INTO active_sessions VALUES ('session-1', 7, 'employee-1');
    """)

    delete_person_dependencies(connection.execute, 1, 7)
    connection.execute("DELETE FROM faces WHERE id = 1 AND vendor_id = 7")

    for table in (
        "faces", "advances", "advance_revisions", "attendance", "student_parents",
        "leave_requests", "lecture_attendance", "person_embeddings", "system_users", "active_sessions",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert connection.execute("SELECT selected_person_id FROM parent_users").fetchone()[0] is None
    connection.close()


def test_delete_person_dependencies_is_vendor_scoped():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE advances (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE advance_revisions (id INTEGER PRIMARY KEY, advance_id INTEGER, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE student_parents (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE parent_users (id INTEGER PRIMARY KEY, vendor_id INTEGER, selected_person_id INTEGER);
        CREATE TABLE leave_requests (id INTEGER PRIMARY KEY, vendor_id INTEGER, student_id INTEGER);
        CREATE TABLE lecture_attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE person_embeddings (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE system_users (username TEXT PRIMARY KEY, vendor_id INTEGER, person_id INTEGER);
        CREATE TABLE active_sessions (token TEXT PRIMARY KEY, vendor_id INTEGER, username TEXT);

        INSERT INTO advances VALUES (1, 8, 1);
        INSERT INTO advance_revisions VALUES (2, 1, 8, 1);
        INSERT INTO attendance VALUES (3, 8, 1);
        INSERT INTO student_parents VALUES (4, 8, 1);
        INSERT INTO parent_users VALUES (5, 8, 1);
        INSERT INTO leave_requests VALUES (6, 8, 1);
        INSERT INTO lecture_attendance VALUES (7, 8, 1);
        INSERT INTO person_embeddings VALUES (8, 8, 1);
        INSERT INTO system_users VALUES ('other-vendor', 8, 1);
        INSERT INTO active_sessions VALUES ('other-session', 8, 'other-vendor');
    """)

    delete_person_dependencies(connection.execute, 1, 7)

    for table in (
        "advances", "advance_revisions", "attendance", "student_parents", "leave_requests",
        "lecture_attendance", "person_embeddings", "system_users", "active_sessions",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    assert connection.execute("SELECT selected_person_id FROM parent_users").fetchone()[0] == 1
    connection.close()
