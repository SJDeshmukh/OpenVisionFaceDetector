"""Stable, per-person cache versions for authenticated profile images."""


PRIVATE_IMAGE_CACHE_CONTROL = "private, max-age=86400, stale-while-revalidate=604800"
PRIVATE_IMAGE_REDIRECT_CACHE_CONTROL = "private, max-age=300"


def load_person_image_versions(conn, cursor, vendor_id, person_ids):
    """Return the latest sync-ledger sequence for each requested person.

    The faces change trigger already writes one ledger row for every insert or
    update. Reusing it avoids adding another migration or reading large image
    blobs merely to calculate a cache key. On an older database without the
    ledger, callers receive an empty mapping and continue with unversioned URLs.
    """
    ids = sorted({int(person_id) for person_id in person_ids if person_id is not None})
    if not ids:
        return {}

    placeholders = ",".join(["?"] * len(ids))
    where_vendor = "vendor_id = ? AND " if vendor_id is not None else ""
    params = ([int(vendor_id)] if vendor_id is not None else []) + ids
    savepoint = bool(getattr(conn, "_is_pg", False))

    try:
        if savepoint:
            cursor.execute("SAVEPOINT person_image_versions")
        cursor.execute(
            f"SELECT person_id, MAX(seq) AS image_version "
            f"FROM face_sync_changes WHERE {where_vendor}person_id IN ({placeholders}) "
            "GROUP BY person_id",
            params,
        )
        versions = {person_id: 0 for person_id in ids}
        for row in cursor.fetchall() or []:
            person_id = row["person_id"] if hasattr(row, "keys") else row[0]
            version = row["image_version"] if hasattr(row, "keys") else row[1]
            versions[int(person_id)] = int(version or 0)
        if savepoint:
            cursor.execute("RELEASE SAVEPOINT person_image_versions")
        return versions
    except Exception:
        if savepoint:
            try:
                cursor.execute("ROLLBACK TO SAVEPOINT person_image_versions")
                cursor.execute("RELEASE SAVEPOINT person_image_versions")
            except Exception:
                pass
        return {}
