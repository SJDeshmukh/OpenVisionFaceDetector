"""Canonical email identities used by every non-super-admin account."""

import json
import re


LOGIN_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_login_email(value):
    return str(value or "").strip().lower()


def is_valid_login_email(value):
    return bool(LOGIN_EMAIL_PATTERN.fullmatch(normalize_login_email(value)))


def login_email_from_profile(profile):
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except (TypeError, ValueError):
            return ""
    if not isinstance(profile, dict):
        return ""
    for key in ("email", "Email", "employee_email", "student_email", "faculty_email"):
        candidate = normalize_login_email(profile.get(key))
        if is_valid_login_email(candidate):
            return candidate
    return ""


def migrate_legacy_login_identities(conn):
    """Replace legacy ID-based usernames with their registered profile email.

    Existing email usernames are normalized to lowercase. Accounts without a
    linked, valid email and collisions are deliberately left unchanged for an
    administrator to resolve from System Access.
    """
    cursor = conn.cursor()
    cursor.execute(
        """SELECT su.username, su.role, su.person_id, su.vendor_id, f.custom_data
           FROM system_users su
           LEFT JOIN faces f ON f.id = su.person_id AND f.vendor_id = su.vendor_id"""
    )
    rows = cursor.fetchall() or []
    migrated = 0

    for row in rows:
        if hasattr(row, "keys"):
            username = str(row["username"] or "")
            role = str(row["role"] or "")
            vendor_id = row["vendor_id"]
            custom_data = row["custom_data"]
        else:
            username = str(row[0] or "")
            role = str(row[1] or "")
            vendor_id = row[3]
            custom_data = row[4]

        if role == "super_admin":
            continue

        target_email = (
            normalize_login_email(username)
            if is_valid_login_email(username)
            else login_email_from_profile(custom_data)
        )
        if not target_email or target_email == username:
            continue

        cursor.execute(
            "SELECT username FROM system_users WHERE LOWER(username) = LOWER(?) AND username <> ? LIMIT 1",
            (target_email, username),
        )
        if cursor.fetchone():
            continue

        cursor.execute(
            "UPDATE system_users SET username = ? WHERE username = ?",
            (target_email, username),
        )
        if cursor.rowcount != 1:
            continue
        cursor.execute("DELETE FROM active_sessions WHERE username = ?", (username,))
        cursor.execute(
            "UPDATE vendors SET kiosk_username = ? WHERE id = ? AND kiosk_username = ?",
            (target_email, vendor_id, username),
        )
        migrated += 1

    return migrated
