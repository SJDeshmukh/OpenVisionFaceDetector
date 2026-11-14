const fs = require('fs');

const path = 'c:/OpenVisionX/backend/routes/leave_routes.py';
let code = fs.readFileSync(path, 'utf8');

function replaceBlock(oldBlock, newBlock) {
    if (code.includes(oldBlock.replace(/\n/g, '\r\n'))) {
        code = code.replace(oldBlock.replace(/\n/g, '\r\n'), newBlock.replace(/\n/g, '\r\n'));
        return true;
    }
    if (code.includes(oldBlock)) {
        code = code.replace(oldBlock, newBlock);
        return true;
    }
    return false;
}

// 1. Role check in create_leave_request
const oldRoleCheck = 'role_error = _require_role("user", "student")\n    if role_error: return role_error';
const newRoleCheck = 'role_error = _require_role("user", "student", "parent")\n    if role_error: return role_error';
if (!replaceBlock(oldRoleCheck, newRoleCheck)) {
    console.log('Role check already updated or not found');
}

// 2. Resolve block in create_leave_request
const oldResolveBlock = `# Never trust a body-supplied student ID. Resolve the student from the
        # authenticated account and only use the body field as a consistency check.
        if is_pg:
            c.execute(
                "SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s AND role IN ('user', 'student')",
                (vendor_id, g.username),
            )
        else:
            c.execute(
                "SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ? AND role IN ('user', 'student')",
                (vendor_id, g.username),
            )
        authenticated_student = c.fetchone()
        authenticated_person_id = authenticated_student[0] if authenticated_student else None
        if authenticated_person_id is not None:
            student_id = authenticated_person_id
        elif isinstance(student_id, str) and student_id.strip().lower() == str(g.username).strip().lower():
            # Compatibility fallback for older student accounts without person_id.
            student_id = g.username
        else:
            return jsonify({"error": "Student account is not linked to a face record"}), 409`;

const newResolveBlock = `# Authenticate and resolve caller identity (parent vs student/user)
        is_parent_caller = getattr(g, "user_role", None) == "parent"
        parent_account = None

        if is_parent_caller:
            parent_account = _authenticated_parent(c, vendor_id)
            if not parent_account:
                return jsonify({"error": "Parent account not found or session invalid"}), 403

            # Parent must only submit leave for students linked to their account
            linked_person_ids = set()
            if parent_account.get("selected_person_id"):
                linked_person_ids.add(int(parent_account["selected_person_id"]))
            try:
                c.execute(
                    "SELECT person_id FROM student_parents WHERE vendor_id = ? AND parent_id = ?",
                    (vendor_id, parent_account["id"]),
                )
                for r in c.fetchall() or []:
                    pid_val = r[0] if not hasattr(r, "keys") else r["person_id"]
                    if pid_val is not None:
                        linked_person_ids.add(int(pid_val))
            except Exception:
                pass

            resolved_student_id = None
            if student_id:
                if str(student_id).isdigit() and int(student_id) in linked_person_ids:
                    resolved_student_id = int(student_id)
                elif str(student_id).strip().lower() == str(parent_account.get("student_number", "")).strip().lower():
                    resolved_student_id = parent_account.get("selected_person_id")
                else:
                    c.execute("""SELECT id FROM faces WHERE vendor_id = ? AND (
                                    CAST(id AS TEXT) = ? OR
                                    LOWER(TRIM(json_extract(custom_data, '$.student_id'))) = LOWER(TRIM(?)) OR
                                    LOWER(TRIM(json_extract(custom_data, '$.id_number'))) = LOWER(TRIM(?))
                                 )""", (vendor_id, str(student_id), str(student_id), str(student_id)))
                    row = c.fetchone()
                    if row:
                        cand_id = int(row[0] if not hasattr(row, "keys") else row["id"])
                        if cand_id in linked_person_ids:
                            resolved_student_id = cand_id

            if resolved_student_id is None:
                resolved_student_id = parent_account.get("selected_person_id")

            if not resolved_student_id or (linked_person_ids and resolved_student_id not in linked_person_ids):
                return jsonify({"error": "This parent account is not linked to that student"}), 403
            student_id = resolved_student_id
        else:
            # Never trust a body-supplied student ID. Resolve the student from the
            # authenticated account and only use the body field as a consistency check.
            if is_pg:
                c.execute(
                    "SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s AND role IN ('user', 'student')",
                    (vendor_id, g.username),
                )
            else:
                c.execute(
                    "SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ? AND role IN ('user', 'student')",
                    (vendor_id, g.username),
                )
            authenticated_student = c.fetchone()
            authenticated_person_id = authenticated_student[0] if authenticated_student else None
            if authenticated_person_id is not None:
                student_id = authenticated_person_id
            elif isinstance(student_id, str) and student_id.strip().lower() == str(g.username).strip().lower():
                # Compatibility fallback for older student accounts without person_id.
                student_id = g.username
            else:
                return jsonify({"error": "Student account is not linked to a face record"}), 409`;

if (!replaceBlock(oldResolveBlock, newResolveBlock)) {
    console.log('Resolve block already updated or not found');
}

// 3. Auto-approve parent stage on parent submission
const oldNotifyBlock = `conn.commit()
        steps = snapshot_request(conn, vendor_id, request_id) if request_id else []
        if request_id:
            _notify_parent_when_current(conn, vendor_id, {
                "id": request_id,
                "vendor_id": vendor_id,
                "student_id": student_id,
            })
        return jsonify({"status": "success", "request_id": request_id, "approval_steps": steps})`;

const newNotifyBlock = `conn.commit()
        steps = snapshot_request(conn, vendor_id, request_id) if request_id else []
        if request_id:
            if is_parent_caller:
                # The parent initiated this leave request, so the parent stage is
                # approved by definition. Advance to the administrative stage immediately.
                for stage in steps:
                    if stage.get("actor_type") == "parent":
                        decide_current_stage(
                            conn,
                            vendor_id,
                            {"id": request_id, "vendor_id": vendor_id, "student_id": student_id, "final_status": "pending"},
                            "approved",
                            actor_type="parent",
                            role_key="parent",
                            actor_id=parent_account["id"],
                            actor_name=parent_account.get("student_number") or g.username,
                            metadata={"source": "parent_submission", "ip": request.remote_addr},
                        )
                        break
                steps = snapshot_request(conn, vendor_id, request_id)
            else:
                _notify_parent_when_current(conn, vendor_id, {
                    "id": request_id,
                    "vendor_id": vendor_id,
                    "student_id": student_id,
                })
        return jsonify({"status": "success", "request_id": request_id, "approval_steps": steps})`;

if (!replaceBlock(oldNotifyBlock, newNotifyBlock)) {
    console.log('Notify block already updated or not found');
}

// 4. Update get_parent_pending_requests and add routes /parent/requests, /parent/history
const oldParentPending = `@leave_bp.route("/parent/pending", methods=["GET"])
def get_parent_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        parent = _authenticated_parent(c, vendor_id)
        if not parent:
            return jsonify({"error": "Parent access required"}), 403

        requested_student = request.args.get("student_number")
        if requested_student and requested_student.strip().lower() != str(parent["student_number"]).strip().lower():
            return jsonify({"error": "This parent account is not linked to that student"}), 403

        student_id = parent.get("selected_person_id")
        if student_id is None:
            # Compatibility for old parent rows created before selected_person_id.
            if is_pg:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s", (vendor_id, parent["student_number"]))
            else:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ?", (vendor_id, parent["student_number"]))
            row = c.fetchone()
            student_id = row[0] if row else None
        if student_id is None:
            return jsonify({"requests": []})

        c.execute("""SELECT * FROM leave_requests
                     WHERE student_id = ? AND vendor_id = ? AND final_status = 'pending'
                     ORDER BY created_at DESC""", (student_id, vendor_id))
        rows = [get_row_dict(r) for r in c.fetchall()]
        attach_approval_steps(conn, rows)
        pending = [
            row for row in rows
            if row.get("current_stage") and row["current_stage"].get("actor_type") == "parent"
        ]
        return jsonify({"requests": pending})`;

const newParentPending = `@leave_bp.route("/parent/pending", methods=["GET"])
@leave_bp.route("/parent/requests", methods=["GET"])
@leave_bp.route("/parent/history", methods=["GET"])
def get_parent_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    c = conn.cursor()
    try:
        is_pg = getattr(conn, "_is_pg", False)
        parent = _authenticated_parent(c, vendor_id)
        if not parent:
            return jsonify({"error": "Parent access required"}), 403

        requested_student = request.args.get("student_number")
        if requested_student and requested_student.strip().lower() != str(parent["student_number"]).strip().lower():
            return jsonify({"error": "This parent account is not linked to that student"}), 403

        student_id = parent.get("selected_person_id")
        if student_id is None:
            # Compatibility for old parent rows created before selected_person_id.
            if is_pg:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = %s AND username = %s", (vendor_id, parent["student_number"]))
            else:
                c.execute("SELECT person_id FROM system_users WHERE vendor_id = ? AND username = ?", (vendor_id, parent["student_number"]))
            row = c.fetchone()
            student_id = row[0] if row else None
        if student_id is None:
            return jsonify({"requests": []})

        status_param = request.args.get("status")
        include_all = request.args.get("all") in ("1", "true") or request.path.endswith(("/requests", "/history"))

        if include_all or status_param:
            if status_param and status_param != "all":
                c.execute("""SELECT * FROM leave_requests
                             WHERE student_id = ? AND vendor_id = ? AND final_status = ?
                             ORDER BY created_at DESC""", (student_id, vendor_id, status_param))
            else:
                c.execute("""SELECT * FROM leave_requests
                             WHERE student_id = ? AND vendor_id = ?
                             ORDER BY created_at DESC""", (student_id, vendor_id))
            rows = [get_row_dict(r) for r in c.fetchall()]
            attach_approval_steps(conn, rows)
            return jsonify({"requests": rows, "history": rows})

        c.execute("""SELECT * FROM leave_requests
                     WHERE student_id = ? AND vendor_id = ? AND final_status = 'pending'
                     ORDER BY created_at DESC""", (student_id, vendor_id))
        rows = [get_row_dict(r) for r in c.fetchall()]
        attach_approval_steps(conn, rows)
        pending = [
            row for row in rows
            if row.get("current_stage") and row["current_stage"].get("actor_type") == "parent"
        ]
        return jsonify({"requests": pending})`;

if (!replaceBlock(oldParentPending, newParentPending)) {
    console.log('Parent pending block already updated or not found');
}

// 5. In get_leave_tracking: allow vendor admin
const oldTrackingFunc = `def get_leave_tracking():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role", "rector")
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")`;

const newTrackingFunc = `def get_leave_tracking():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role", "rector")
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
            return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")`;

if (!replaceBlock(oldTrackingFunc, newTrackingFunc)) {
    console.log('Tracking func already updated or not found');
}

// 6. In get_admin_pending_requests
const oldPendingFunc = `def get_admin_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role", "rector")
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")`;

const newPendingFunc = `def get_admin_pending_requests():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role", "rector")
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
            return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")`;

if (!replaceBlock(oldPendingFunc, newPendingFunc)) {
    console.log('Pending func already updated or not found');
}

// 7. In get_admin_pending_requests: match role check
const oldPendingFilter = `pending = []
        for row in rows:
            stage = row.get("current_stage")
            if not stage or stage.get("actor_type") != "staff" or stage.get("role_key") != role:
                continue
            if stage.get("department_scoped") and not _student_matches_department(row, dept):
                continue
            pending.append(row)`;

const newPendingFilter = `pending = []
        for row in rows:
            stage = row.get("current_stage")
            if not stage or stage.get("actor_type") != "staff":
                continue
            if not is_vendor_admin or (role and role not in ("vendor_admin", "admin", "owner", "all")):
                if stage.get("role_key") != role:
                    continue
            if stage.get("department_scoped") and dept and not _student_matches_department(row, dept):
                continue
            pending.append(row)`;

if (!replaceBlock(oldPendingFilter, newPendingFilter)) {
    console.log('Pending filter already updated or not found');
}

// 8. In get_admin_leave_history: allow vendor admin
const oldHistoryFunc = `def get_admin_leave_history():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role")
    status = request.args.get("status", "all")
    
    if not role:
        return jsonify({"error": "Role required"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")`;

const newHistoryFunc = `def get_admin_leave_history():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    role = request.args.get("role")
    status = request.args.get("status", "all")
    
    if not role:
        return jsonify({"error": "Role required"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
            return jsonify({"error": "A valid staff PIN session is required"}), 403
    dept = staff.get("department")`;

if (!replaceBlock(oldHistoryFunc, newHistoryFunc)) {
    console.log('History func already updated or not found');
}

// 9. In admin_approve_request: allow vendor admin
const oldApproveFunc = `def admin_approve_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    data = request.json
    request_id = data.get("request_id")
    role = data.get("role")
    action = data.get("action")
    
    if not all([request_id, role, action]):
        return jsonify({"error": "Missing fields"}), 400
    if action not in ALLOWED_LEAVE_ACTIONS:
        return jsonify({"error": "Action must be approved or rejected"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    if not staff:
        return jsonify({"error": "A valid staff PIN session is required"}), 403`;

const newApproveFunc = `def admin_approve_request():
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    role_error = _require_role("vendor_admin", "admin", "owner", "super_admin")
    if role_error: return role_error
    
    data = request.json
    request_id = data.get("request_id")
    role = data.get("role")
    action = data.get("action")
    
    if not all([request_id, role, action]):
        return jsonify({"error": "Missing fields"}), 400
    if action not in ALLOWED_LEAVE_ACTIONS:
        return jsonify({"error": "Action must be approved or rejected"}), 400
    staff = _authenticated_leave_staff(vendor_id, role)
    caller_role = getattr(g, "user_role", None)
    is_vendor_admin = caller_role in ("vendor_admin", "admin", "owner", "super_admin")
    if not staff:
        if is_vendor_admin:
            staff = {"id": None, "name": getattr(g, "username", "Admin"), "role": role or "admin", "department": None}
        else:
            return jsonify({"error": "A valid staff PIN session is required"}), 403`;

if (!replaceBlock(oldApproveFunc, newApproveFunc)) {
    console.log('Approve func already updated or not found');
}

// 10. In admin_approve_request: allow vendor admin stage approval
const oldApproveStageCheck = `if not stage or stage.get("actor_type") != "staff" or stage.get("role_key") != role:
            waiting_for = stage.get("display_name") if stage else "another stage"
            return jsonify({"error": f"Leave request is awaiting {waiting_for} approval"}), 409
        if stage.get("department_scoped") and not _student_matches_department(request_row, staff.get("department")):
            return jsonify({"error": "This request is outside your assigned department"}), 403`;

const newApproveStageCheck = `if not stage or stage.get("actor_type") != "staff":
            waiting_for = stage.get("display_name") if stage else "another stage"
            return jsonify({"error": f"Leave request is awaiting {waiting_for} approval"}), 409
        if not is_vendor_admin and stage.get("role_key") != role:
            waiting_for = stage.get("display_name") if stage else "another stage"
            return jsonify({"error": f"Leave request is awaiting {waiting_for} approval"}), 409
        if stage.get("department_scoped") and staff.get("department") and not _student_matches_department(request_row, staff.get("department")):
            return jsonify({"error": "This request is outside your assigned department"}), 403`;

if (!replaceBlock(oldApproveStageCheck, newApproveStageCheck)) {
    console.log('Approve stage check already updated or not found');
}

fs.writeFileSync(path, code, 'utf8');
console.log('SUCCESS: leave_routes.py completely updated');
