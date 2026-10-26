"""Authoritative allocation repair for vendor-visible person serial numbers."""


def _is_postgres_connection(conn):
    if getattr(conn, "_is_pg", False):
        return True
    module_name = getattr(type(conn), "__module__", "")
    return module_name.startswith("psycopg")


def compact_vendor_display_ids(conn, vendor_id):
    """Make one vendor's display IDs gapless while preserving current order.

    The caller owns the transaction. Updating only changed rows is important:
    the faces update trigger records those rows in ``face_sync_changes``, which
    lets every kiosk receive the new numbers through its normal delta sync.
    """
    if vendor_id is None:
        return []

    is_pg = _is_postgres_connection(conn)
    placeholder = "%s" if is_pg else "?"
    cursor = conn.cursor()

    # Use the same per-vendor transaction lock as face registration so an
    # enrollment cannot allocate MAX(display_id)+1 during compaction.
    if is_pg:
        cursor.execute(
            f"SELECT pg_advisory_xact_lock({placeholder})",
            (int(vendor_id),),
        )

        # PostgreSQL can rank and update the whole vendor roster in one
        # statement.  The previous row-by-row loop added one database round
        # trip per employee, which made deleting an early serial increasingly
        # slow as a vendor's roster grew.
        cursor.execute(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           ORDER BY CASE WHEN display_id IS NULL THEN 1 ELSE 0 END,
                                    display_id ASC,
                                    id ASC
                       )::integer AS expected_display_id
                FROM faces
                WHERE vendor_id = %s
            ), updated AS (
                UPDATE faces AS f
                   SET display_id = ranked.expected_display_id
                  FROM ranked
                 WHERE f.id = ranked.id
                   AND f.vendor_id = %s
                   AND f.display_id IS DISTINCT FROM ranked.expected_display_id
                RETURNING f.id, f.display_id
            )
            SELECT id, display_id FROM updated ORDER BY display_id ASC, id ASC
            """,
            (vendor_id, vendor_id),
        )
        changed = [
            {"person_id": int(row[0]), "display_id": int(row[1])}
            for row in (cursor.fetchall() or [])
        ]
        cursor.close()
        return changed

    cursor.execute(
        "SELECT id, display_id FROM faces "
        f"WHERE vendor_id = {placeholder} "
        "ORDER BY CASE WHEN display_id IS NULL THEN 1 ELSE 0 END, display_id ASC, id ASC",
        (vendor_id,),
    )
    rows = cursor.fetchall() or []
    changed = []
    for expected_display_id, row in enumerate(rows, start=1):
        person_id = int(row[0])
        current_display_id = row[1]
        try:
            current_display_id = int(current_display_id) if current_display_id is not None else None
        except (TypeError, ValueError):
            current_display_id = None
        if current_display_id == expected_display_id:
            continue
        cursor.execute(
            f"UPDATE faces SET display_id = {placeholder} WHERE id = {placeholder} AND vendor_id = {placeholder}",
            (expected_display_id, person_id, vendor_id),
        )
        changed.append({"person_id": person_id, "display_id": expected_display_id})
    cursor.close()
    return changed


def compact_all_vendor_display_ids(conn):
    """Repair existing gaps for every vendor and return changed assignments."""
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT vendor_id FROM faces WHERE vendor_id IS NOT NULL ORDER BY vendor_id")
    vendor_ids = [row[0] for row in (cursor.fetchall() or [])]
    cursor.close()

    changed = {}
    for vendor_id in vendor_ids:
        vendor_changes = compact_vendor_display_ids(conn, vendor_id)
        if vendor_changes:
            changed[int(vendor_id)] = vendor_changes
    return changed
