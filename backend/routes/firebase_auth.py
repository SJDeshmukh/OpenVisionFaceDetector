"""Google sign-in through Firebase Authentication for the TapInX web portal."""

import json
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime

from flask import Blueprint, jsonify, make_response, request

from db_factory import get_db_connection, get_table_columns
from middleware.handlers import get_client_ip, rate_limit
from services.auth_service import (
    WEB_TOKEN_TTL,
    check_vendor_status,
    generate_token,
    generate_token_with_claims,
    hash_password,
)
from services.firebase_auth_service import (
    FirebaseAuthConfigurationError,
    FirebaseAuthTokenError,
    verify_google_firebase_token,
)
from services.login_identity_service import (
    is_student_profile,
    is_valid_login_email,
    normalize_login_email,
)
from services.staff_navigation_service import load_staff_nav_items_for_features


logger = logging.getLogger(__name__)
firebase_auth_bp = Blueprint("firebase_auth_bp", __name__)
PROVIDER = "firebase_google"


def _row_dict(row, columns=None):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(columns or [], row))


def _json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _profile_email(custom_data):
    profile = _json_object(custom_data)
    for key in (
        "email", "Email", "employee_email", "student_email", "faculty_email",
        "login_email", "username",
    ):
        value = normalize_login_email(profile.get(key))
        if is_valid_login_email(value):
            return value
    return ""


def _find_face_matches(cursor, conn, email):
    face_columns = get_table_columns(conn, "faces")
    student_status = (
        "student_status" if "student_status" in face_columns
        else "'active' AS student_status"
    )
    login_enabled = (
        "login_enabled" if "login_enabled" in face_columns
        else "1 AS login_enabled"
    )
    # Candidate filtering avoids database JSON casts so one malformed legacy
    # custom_data value cannot break Google login for every registered user.
    cursor.execute(
        f"""SELECT id, name, vendor_id, custom_data, designation,
                   {student_status}, {login_enabled}
              FROM faces
             WHERE LOWER(COALESCE(custom_data, '')) LIKE LOWER(?)""",
        (f"%{email}%",),
    )
    columns = [
        "id", "name", "vendor_id", "custom_data", "designation",
        "student_status", "login_enabled",
    ]
    return [
        item
        for item in (_row_dict(row, columns) for row in (cursor.fetchall() or []))
        if _profile_email(item.get("custom_data")) == email
    ]


def _find_staff_matches(cursor, email):
    cursor.execute(
        """SELECT id, vendor_id, name, email, role, department, navbar_items
             FROM leave_staff
            WHERE LOWER(TRIM(email)) = LOWER(TRIM(?))""",
        (email,),
    )
    columns = ["id", "vendor_id", "name", "email", "role", "department", "navbar_items"]
    return [_row_dict(row, columns) for row in (cursor.fetchall() or [])]


def _find_system_user(cursor, username):
    cursor.execute("SELECT * FROM system_users WHERE LOWER(username) = LOWER(?)", (username,))
    return _row_dict(cursor.fetchone())


def _resolve_account(conn, identity):
    """Resolve a verified Google identity to one pre-registered TapInX account."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT su.*
             FROM external_auth_identities e
             JOIN system_users su ON LOWER(su.username) = LOWER(e.username)
            WHERE e.provider = ? AND e.provider_subject = ?""",
        (PROVIDER, identity["subject"]),
    )
    linked = _row_dict(cursor.fetchone())
    if linked:
        cursor.execute(
            """UPDATE external_auth_identities
                  SET email = ?, last_login_at = ?
                WHERE provider = ? AND provider_subject = ?""",
            (identity["email"], datetime.now(), PROVIDER, identity["subject"]),
        )
        return linked

    email = identity["email"]
    account = _find_system_user(cursor, email)
    staff_matches = _find_staff_matches(cursor, email)
    face_matches = _find_face_matches(cursor, conn, email)

    staff_vendor_ids = {int(row["vendor_id"]) for row in staff_matches if row.get("vendor_id") is not None}
    face_vendor_ids = {int(row["vendor_id"]) for row in face_matches if row.get("vendor_id") is not None}
    if len(staff_matches) > 1 or len(face_matches) > 1:
        raise ValueError("This email is assigned to multiple profiles. Contact your administrator.")
    if staff_matches and face_matches:
        raise ValueError(
            "This email is assigned to both a student and a staff profile. "
            "Use separate institutional email addresses."
        )
    if staff_vendor_ids and face_vendor_ids and staff_vendor_ids != face_vendor_ids:
        raise ValueError("This email is assigned across multiple institutions. Contact support.")

    if account:
        account_vendor_id = account.get("vendor_id")
        matching_vendor_ids = staff_vendor_ids | face_vendor_ids
        if matching_vendor_ids and (
            account_vendor_id is None or int(account_vendor_id) not in matching_vendor_ids
        ):
            raise ValueError("This Google email does not match the registered institution account.")
        account_role = str(account.get("role") or "").lower()
        if staff_matches and account_role in {"student", "user", "faculty"}:
            raise ValueError(
                "This email is already used by a non-staff login. Contact your administrator."
            )
        if face_matches and account_role not in {"student", "user", "faculty"}:
            raise ValueError(
                "This email is already used by a staff or administrator login. "
                "Contact your administrator."
            )
    elif staff_matches:
        staff = staff_matches[0]
        cursor.execute(
            """INSERT INTO system_users
                   (username, password, password_plain, role, vendor_id, person_id,
                    has_set_password, force_password_change)
               VALUES (?, ?, NULL, 'staff', ?, NULL, 1, 0)""",
            (email, hash_password(secrets.token_urlsafe(48)), staff["vendor_id"]),
        )
        account = _find_system_user(cursor, email)
    elif face_matches:
        face = face_matches[0]
        role = "student" if is_student_profile(face.get("designation"), face.get("custom_data")) else "user"
        cursor.execute(
            """INSERT INTO system_users
                   (username, password, password_plain, role, vendor_id, person_id,
                    has_set_password, force_password_change)
               VALUES (?, ?, NULL, ?, ?, ?, 1, 0)""",
            (
                email,
                hash_password(secrets.token_urlsafe(48)),
                role,
                face["vendor_id"],
                face["id"],
            ),
        )
        account = _find_system_user(cursor, email)
    else:
        raise LookupError(
            "This Google email is not registered in TapInX. Contact your institution administrator."
        )

    if not account or account.get("role") == "super_admin":
        raise ValueError("This account cannot use Google sign-in here.")

    cursor.execute(
        """SELECT provider_subject FROM external_auth_identities
            WHERE provider = ? AND LOWER(username) = LOWER(?)""",
        (PROVIDER, account["username"]),
    )
    existing_link = cursor.fetchone()
    if existing_link:
        existing_subject = existing_link[0] if not hasattr(existing_link, "keys") else existing_link["provider_subject"]
        if str(existing_subject) != identity["subject"]:
            raise ValueError("This TapInX account is linked to another Google account.")
    else:
        cursor.execute(
            """INSERT INTO external_auth_identities
                   (provider, provider_subject, username, vendor_id, email, last_login_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                PROVIDER,
                identity["subject"],
                account["username"],
                account.get("vendor_id"),
                email,
                datetime.now(),
            ),
        )
    return account


def _subscription_features(cursor, vendor_id):
    cursor.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
    row = cursor.fetchone()
    raw = None if not row else (row["features"] if hasattr(row, "keys") else row[0])
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _staff_session(cursor, account, identity_email, features):
    if account.get("role") in {"student", "user", "faculty"}:
        return None
    cursor.execute(
        """SELECT id, name, email, role, department, navbar_items
             FROM leave_staff
            WHERE vendor_id = ? AND LOWER(TRIM(email)) IN (LOWER(TRIM(?)), LOWER(TRIM(?)))""",
        (account["vendor_id"], account["username"], identity_email),
    )
    rows = cursor.fetchall() or []
    if not rows:
        if account.get("role") == "staff":
            raise ValueError("The linked staff profile no longer exists.")
        return None
    if len(rows) > 1:
        raise ValueError("Multiple staff profiles use this email. Contact your administrator.")
    staff = _row_dict(rows[0], ["id", "name", "email", "role", "department", "navbar_items"])
    staff["navbar_items"] = load_staff_nav_items_for_features(staff.get("navbar_items"), features)
    staff["access_token"] = generate_token_with_claims(
        f"leave_staff_{staff['id']}",
        "leave_staff",
        {
            "vendor_id": account["vendor_id"],
            "staff_id": staff["id"],
            "staff_role": staff["role"],
            "department": staff.get("department"),
        },
        platform="web",
    )
    return staff


@firebase_auth_bp.route("/auth/google", methods=["POST"])
@rate_limit(key_func=lambda: f"google-login:{get_client_ip()}", limit=30, window=60)
def google_login():
    started = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()[:255]
    if not device_id:
        return jsonify({"error": "Browser device identifier is required"}), 400

    try:
        identity = verify_google_firebase_token(payload.get("id_token"))
    except FirebaseAuthConfigurationError:
        logger.exception("Firebase Authentication is not configured")
        return jsonify({"error": "Google sign-in is temporarily unavailable"}), 503
    except FirebaseAuthTokenError as exc:
        return jsonify({"error": str(exc)}), 401

    conn = get_db_connection()
    try:
        try:
            if not getattr(conn, "_is_pg", False):
                conn.row_factory = sqlite3.Row
        except Exception:
            pass
        cursor = conn.cursor()
        try:
            account = _resolve_account(conn, identity)
        except LookupError as exc:
            conn.rollback()
            return jsonify({"error": str(exc), "code": "GOOGLE_ACCOUNT_NOT_REGISTERED"}), 403
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc), "code": "GOOGLE_ACCOUNT_CONFLICT"}), 409

        vendor_id = account.get("vendor_id")
        if not vendor_id:
            conn.rollback()
            return jsonify({"error": "This account has no institution assigned"}), 403

        allowed, reason = check_vendor_status(vendor_id)
        if not allowed:
            conn.rollback()
            return jsonify({"error": f"Access Denied: {reason}"}), 403

        vendor_columns = get_table_columns(conn, "vendors")
        vertical_select = "vertical" if "vertical" in vendor_columns else "NULL AS vertical"
        cursor.execute(
            f"SELECT web_login_enabled, {vertical_select} FROM vendors WHERE id = ?",
            (vendor_id,),
        )
        vendor = cursor.fetchone()
        web_login_enabled = (vendor[0] if not hasattr(vendor, "keys") else vendor["web_login_enabled"]) if vendor else 0
        vertical = (vendor[1] if not hasattr(vendor, "keys") else vendor["vertical"]) if vendor else None
        if int(web_login_enabled or 0) != 1:
            conn.rollback()
            return jsonify({"error": "Web login is disabled for this institution"}), 403
        if str(vertical or "").strip().lower() != "hostel":
            conn.rollback()
            return jsonify({"error": "Google sign-in is currently enabled for hostel accounts only"}), 403

        if account.get("person_id"):
            face_columns = get_table_columns(conn, "faces")
            lifecycle_select = [
                "student_status" if "student_status" in face_columns else "'active' AS student_status",
                "login_enabled" if "login_enabled" in face_columns else "1 AS login_enabled",
            ]
            cursor.execute(
                f"SELECT {', '.join(lifecycle_select)} FROM faces WHERE id = ? AND vendor_id = ?",
                (account["person_id"], vendor_id),
            )
            profile = cursor.fetchone()
            if not profile:
                conn.rollback()
                return jsonify({"error": "The linked student profile no longer exists"}), 403
            student_status = str(profile[0] or "active").lower()
            login_enabled = profile[1] if profile[1] is not None else 1
            if student_status in {"graduated", "left_college", "suspended"} or int(login_enabled) != 1:
                conn.rollback()
                return jsonify({"error": "This account is deactivated. Contact your institution."}), 403

        features = _subscription_features(cursor, vendor_id)
        try:
            staff = _staff_session(cursor, account, identity["email"], features)
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc), "code": "GOOGLE_STAFF_CONFLICT"}), 409

        token = generate_token(account["username"], account["role"], vendor_id, platform="web")
        cursor.execute(
            "DELETE FROM active_sessions WHERE platform = 'web' AND device_id = ?",
            (device_id,),
        )
        if account.get("role") == "faculty":
            cursor.execute("DELETE FROM active_sessions WHERE username = ?", (account["username"],))
        cursor.execute(
            """INSERT INTO active_sessions
                   (token, username, vendor_id, device_id, platform, last_active)
               VALUES (?, ?, ?, ?, 'web', ?)""",
            (token, account["username"], vendor_id, device_id, datetime.now()),
        )
        conn.commit()

        response = make_response(jsonify({
            "status": "success",
            "username": account["username"],
            "role": account["role"],
            "vendor_id": vendor_id,
            "person_id": account.get("person_id"),
            "staff_session": staff,
            "redirect_url": "/leave-management" if account.get("role") in {"student", "user", "staff"} or staff else "/dashboard",
        }))
        response.set_cookie(
            "token",
            token,
            httponly=True,
            secure=os.environ.get("PROTOCOL", "http").lower() == "https",
            samesite="Lax",
            max_age=WEB_TOKEN_TTL,
            path="/",
        )
        response.headers["Server-Timing"] = f"google-login;dur={(time.perf_counter() - started) * 1000:.1f}"
        logger.info(
            "Google login completed username=%s vendor_id=%s role=%s",
            account["username"], vendor_id, account["role"],
        )
        return response
    except Exception:
        conn.rollback()
        logger.exception("Google login failed after token verification")
        return jsonify({"error": "Unable to complete Google sign-in"}), 500
    finally:
        conn.close()
