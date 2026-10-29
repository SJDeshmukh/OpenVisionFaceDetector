import sqlite3

from services.person_image_cache_service import (
    PRIVATE_IMAGE_CACHE_CONTROL,
    PRIVATE_IMAGE_REDIRECT_CACHE_CONTROL,
    load_person_image_versions,
)


def test_person_image_versions_change_only_for_updated_person():
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE face_sync_changes (
               seq INTEGER PRIMARY KEY AUTOINCREMENT,
               vendor_id INTEGER NOT NULL,
               person_id INTEGER NOT NULL,
               operation TEXT NOT NULL
           )"""
    )
    cursor.executemany(
        "INSERT INTO face_sync_changes(vendor_id, person_id, operation) VALUES (?, ?, ?)",
        [(7, 101, "INSERT"), (7, 102, "INSERT"), (8, 101, "UPDATE")],
    )

    before = load_person_image_versions(conn, cursor, 7, [101, 102])
    cursor.execute(
        "INSERT INTO face_sync_changes(vendor_id, person_id, operation) VALUES (?, ?, ?)",
        (7, 101, "UPDATE"),
    )
    after = load_person_image_versions(conn, cursor, 7, [101, 102])

    assert after[101] > before[101]
    assert after[102] == before[102]
    assert before[101] != load_person_image_versions(conn, cursor, 8, [101])[101]


def test_image_version_lookup_falls_back_on_legacy_schema():
    conn = sqlite3.connect(":memory:")
    assert load_person_image_versions(conn, conn.cursor(), 7, [101]) == {}


def test_successful_image_cache_headers_are_private():
    assert PRIVATE_IMAGE_CACHE_CONTROL == (
        "private, max-age=86400, stale-while-revalidate=604800"
    )
    assert PRIVATE_IMAGE_REDIRECT_CACHE_CONTROL == "private, max-age=300"
