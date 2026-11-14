"""Ordered cleanup of records that reference a person in ``faces``."""


def delete_person_dependencies(execute, person_id, vendor_id=None, name=None):
    """Delete direct person dependencies before the parent ``faces`` row.

    ``execute`` accepts ``(sql, parameters)`` and may provide savepoint-based
    compatibility handling for deployments upgraded from older schemas.
    """
    clean_name = str(name).strip().lower() if name else None

    if vendor_id is None:
        statements = [
            (
                "DELETE FROM advance_revisions WHERE person_id = ? OR advance_id IN (SELECT id FROM advances WHERE person_id = ?)",
                (person_id, person_id),
            ),
            ("DELETE FROM advances WHERE person_id = ?", (person_id,)),
            ("DELETE FROM attendance_events WHERE person_id = ? OR legacy_attendance_id IN (SELECT id FROM attendance WHERE person_id = ?)", (person_id, person_id)),
            ("DELETE FROM attendance WHERE person_id = ?", (person_id,)),
            ("DELETE FROM student_parents WHERE person_id = ?", (person_id,)),
            ("UPDATE parent_users SET selected_person_id = NULL WHERE selected_person_id = ?", (person_id,)),
            ("DELETE FROM leave_requests WHERE student_id = ?", (person_id,)),
            ("DELETE FROM lecture_attendance WHERE person_id = ?", (person_id,)),
            ("DELETE FROM person_embeddings WHERE person_id = ?", (person_id,)),
            ("DELETE FROM hostel_allocations WHERE person_id = ?", (person_id,)),
            ("UPDATE hostel_beds SET reserved_for_person_id = NULL WHERE reserved_for_person_id = ?", (person_id,)),
            ("DELETE FROM shift_assignments WHERE person_id = ?", (person_id,)),
            ("DELETE FROM person_organization_assignments WHERE person_id = ?", (person_id,)),
            ("DELETE FROM student_enrollments WHERE person_id = ?", (person_id,)),
            ("DELETE FROM employee_salary_versions WHERE person_id = ?", (person_id,)),
            (
                "DELETE FROM active_sessions WHERE username IN (SELECT username FROM system_users WHERE person_id = ?)",
                (person_id,),
            ),
            ("DELETE FROM system_users WHERE person_id = ?", (person_id,)),
        ]
        if clean_name:
            statements.append(("DELETE FROM attendance WHERE LOWER(TRIM(name)) = ?", (clean_name,)))
    else:
        statements = [
            (
                "DELETE FROM advance_revisions WHERE vendor_id = ? AND (person_id = ? OR advance_id IN (SELECT id FROM advances WHERE vendor_id = ? AND person_id = ?))",
                (vendor_id, person_id, vendor_id, person_id),
            ),
            ("DELETE FROM advances WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM attendance_events WHERE vendor_id = ? AND (person_id = ? OR legacy_attendance_id IN (SELECT id FROM attendance WHERE vendor_id = ? AND person_id = ?))", (vendor_id, person_id, vendor_id, person_id)),
            ("DELETE FROM attendance WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM student_parents WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            (
                "UPDATE parent_users SET selected_person_id = NULL WHERE vendor_id = ? AND selected_person_id = ?",
                (vendor_id, person_id),
            ),
            ("DELETE FROM leave_requests WHERE vendor_id = ? AND student_id = ?", (vendor_id, person_id)),
            ("DELETE FROM lecture_attendance WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM person_embeddings WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM hostel_allocations WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("UPDATE hostel_beds SET reserved_for_person_id = NULL WHERE vendor_id = ? AND reserved_for_person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM shift_assignments WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM person_organization_assignments WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM student_enrollments WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            ("DELETE FROM employee_salary_versions WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
            (
                "DELETE FROM active_sessions WHERE vendor_id = ? AND username IN (SELECT username FROM system_users WHERE vendor_id = ? AND person_id = ?)",
                (vendor_id, vendor_id, person_id),
            ),
            ("DELETE FROM system_users WHERE vendor_id = ? AND person_id = ?", (vendor_id, person_id)),
        ]
        if clean_name:
            statements.append(("DELETE FROM attendance WHERE vendor_id = ? AND LOWER(TRIM(name)) = ?", (vendor_id, clean_name)))

    for sql, parameters in statements:
        execute(sql, parameters)
