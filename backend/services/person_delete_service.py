"""Ordered cleanup of records that reference a person in ``faces``."""


def delete_person_dependencies(execute, person_id, vendor_id=None):
    """Delete direct person dependencies before the parent ``faces`` row.

    ``execute`` accepts ``(sql, parameters)`` and may provide savepoint-based
    compatibility handling for deployments upgraded from older schemas.
    """
    if vendor_id is None:
        statements = [
            (
                "DELETE FROM advance_revisions WHERE person_id = ? OR advance_id IN (SELECT id FROM advances WHERE person_id = ?)",
                (person_id, person_id),
            ),
            ("DELETE FROM advances WHERE person_id = ?", (person_id,)),
            ("DELETE FROM attendance WHERE person_id = ?", (person_id,)),
            ("DELETE FROM student_parents WHERE person_id = ?", (person_id,)),
            ("UPDATE parent_users SET selected_person_id = NULL WHERE selected_person_id = ?", (person_id,)),
            ("DELETE FROM leave_requests WHERE student_id = ?", (person_id,)),
            ("DELETE FROM lecture_attendance WHERE person_id = ?", (person_id,)),
            ("DELETE FROM person_embeddings WHERE person_id = ?", (person_id,)),
            (
                "DELETE FROM active_sessions WHERE username IN (SELECT username FROM system_users WHERE person_id = ?)",
                (person_id,),
            ),
            ("DELETE FROM system_users WHERE person_id = ?", (person_id,)),
        ]
    else:
        statements = [
            (
                "DELETE FROM advance_revisions WHERE vendor_id = ? AND (person_id = ? OR advance_id IN (SELECT id FROM advances WHERE vendor_id = ? AND person_id = ?))",
                (vendor_id, person_id, vendor_id, person_id),
            ),
            ("DELETE FROM advances WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM attendance WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM student_parents WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            (
                "UPDATE parent_users SET selected_person_id = NULL WHERE vendor_id = ? AND selected_person_id = ?",
                (vendor_id, person_id),
            ),
            ("DELETE FROM leave_requests WHERE vendor_id = ? AND student_id = ?", (vendor_id, person_id)),
            ("DELETE FROM lecture_attendance WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM person_embeddings WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            (
                "DELETE FROM active_sessions WHERE vendor_id = ? AND username IN (SELECT username FROM system_users WHERE vendor_id = ? AND person_id = ?)",
                (vendor_id, vendor_id, person_id),
            ),
            ("DELETE FROM system_users WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
        ]

    for sql, parameters in statements:
        execute(sql, parameters)
