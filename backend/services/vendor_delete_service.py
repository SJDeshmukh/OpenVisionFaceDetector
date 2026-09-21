"""Transactional removal of all database data owned by one vendor."""


DIRECT_DELETE_ORDER = (
    # Records that reference faces, shifts, locations, or other tenant rows.
    "attendance_events",
    "person_organization_assignments",
    "shift_segments",
    "shift_assignments",
    "holidays",
    "lecture_attendance",
    "face_reset_requests",
    "student_parents",
    "advance_revisions",
    "advances",
    "leave_request_stages",
    "leave_requests",
    "person_embeddings",
    "report_delivery_jobs",
    "automated_report_deliveries",
    "hostel_alert_deliveries",
    "xchat_messages",
    "xchat_token_usage",
    "attendance",
    "parent_tokens",
    "parent_users",
    "active_sessions",
    "system_users",
    "faces",
    # Parent/configuration records.
    "class_batches",
    "registration_batches",
    "lectures",
    "automated_report_schedules",
    "hostel_alert_settings",
    "xchat_conversations",
    "weekly_off_patterns",
    "shift_versions",
    "shifts",
    "holiday_calendars",
    "organization_units",
    "locations",
    "classes",
    "subject_master",
    "class_thresholds",
    "bulk_attendance_config",
    "leave_staff",
    "leave_workflows",
    "vendor_whatsapp_settings",
    "app_update_device_status",
    "vendor_device_slots",
    "vendor_devices",
    "invoices",
    "subscriptions",
    "companies",
    "backup_metadata",
    "archive_objects",
)


def _database_table_columns(conn):
    cursor = conn.cursor()
    if getattr(conn, "_is_pg", False):
        cursor.execute(
            """SELECT table_name, column_name
               FROM information_schema.columns
               WHERE table_schema = 'public'"""
        )
        rows = cursor.fetchall() or []
        result = {}
        for row in rows:
            table = row["table_name"] if hasattr(row, "keys") else row[0]
            column = row["column_name"] if hasattr(row, "keys") else row[1]
            result.setdefault(str(table), set()).add(str(column))
        return result

    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    result = {}
    for row in cursor.fetchall() or []:
        table = row["name"] if hasattr(row, "keys") else row[0]
        if str(table).startswith("sqlite_"):
            continue
        cursor.execute(f'PRAGMA table_info("{table}")')
        result[str(table)] = {
            str(column["name"] if hasattr(column, "keys") else column[1])
            for column in (cursor.fetchall() or [])
        }
    return result


def _delete_batch_items(cursor, tables, child_table, parent_table, vendor_id):
    if child_table not in tables or parent_table not in tables:
        return 0
    cursor.execute(
        f"DELETE FROM {child_table} WHERE batch_id IN "
        f"(SELECT id FROM {parent_table} WHERE vendor_id = ?)",
        (vendor_id,),
    )
    return max(0, int(cursor.rowcount or 0))


def purge_vendor_database(conn, vendor_id):
    """Remove a vendor and every vendor-owned row using the caller's transaction.

    The caller must commit. Any exception is intentionally propagated so a partial
    purge can be rolled back instead of being reported as a successful deletion.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM vendors WHERE id = ?", (vendor_id,))
    if not cursor.fetchone():
        raise LookupError("Vendor not found")

    table_columns = _database_table_columns(conn)
    tables = set(table_columns)
    deleted = {}

    deleted["class_batch_items"] = _delete_batch_items(
        cursor, tables, "class_batch_items", "class_batches", vendor_id
    )
    deleted["registration_batch_items"] = _delete_batch_items(
        cursor, tables, "registration_batch_items", "registration_batches", vendor_id
    )
    if "leave_workflow_stages" in tables and "leave_workflows" in tables:
        cursor.execute(
            "DELETE FROM leave_workflow_stages WHERE workflow_id IN "
            "(SELECT id FROM leave_workflows WHERE vendor_id = ?)",
            (vendor_id,),
        )
        deleted["leave_workflow_stages"] = max(0, int(cursor.rowcount or 0))

    vendor_tables = {
        table: "target_vendor_id" if "target_vendor_id" in columns else "vendor_id"
        for table, columns in table_columns.items()
        if table != "vendors" and ("vendor_id" in columns or "target_vendor_id" in columns)
    }

    processed = set()
    for table in DIRECT_DELETE_ORDER:
        key = vendor_tables.get(table)
        if not key or table in processed:
            continue
        cursor.execute(f"DELETE FROM {table} WHERE {key} = ?", (vendor_id,))
        deleted[table] = max(0, int(cursor.rowcount or 0))
        processed.add(table)

    # Future tables with a vendor ownership column are purged automatically.
    # Known dependency tables were already handled above, so these are direct
    # tenant tables and any constraint failure aborts the whole transaction.
    for table in sorted(set(vendor_tables) - processed):
        key = vendor_tables[table]
        cursor.execute(f"DELETE FROM {table} WHERE {key} = ?", (vendor_id,))
        deleted[table] = max(0, int(cursor.rowcount or 0))

    if "system_settings" in tables and "key" in table_columns["system_settings"]:
        cursor.execute("SELECT key FROM system_settings")
        owned_keys = []
        suffix = f"_vendor_{vendor_id}"
        for row in cursor.fetchall() or []:
            key = row["key"] if hasattr(row, "keys") else row[0]
            if str(key).endswith(suffix):
                owned_keys.append(str(key))
        for key in owned_keys:
            cursor.execute("DELETE FROM system_settings WHERE key = ?", (key,))
        deleted["system_settings"] = len(owned_keys)

    cursor.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
    if cursor.rowcount != 1:
        raise RuntimeError("Vendor record could not be deleted")
    deleted["vendors"] = 1
    return deleted


def purge_vendor_archive_database(conn, vendor_id):
    """Remove retained/archived rows for a vendor using the caller's transaction."""
    cursor = conn.cursor()
    table_columns = _database_table_columns(conn)
    deleted = {}

    for table, columns in sorted(table_columns.items()):
        if "vendor_id" not in columns:
            continue
        cursor.execute(f"DELETE FROM {table} WHERE vendor_id = ?", (vendor_id,))
        deleted[table] = max(0, int(cursor.rowcount or 0))

    return deleted
