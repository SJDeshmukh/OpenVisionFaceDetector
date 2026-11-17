"""Canonical email identities used by every non-super-admin account."""

import json
import re


LOGIN_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginIdentityConflictError(ValueError):
    """Raised when a profile email is already owned by another login."""


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


def is_student_profile(designation, profile):
    """Identify student/resident records without relying on the system login role."""
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except (TypeError, ValueError):
            profile = {}
    if not isinstance(profile, dict):
        profile = {}

    person_type = str(profile.get("person_type") or "").strip().lower()
    designation = str(designation or "").strip().lower()
    student_types = {"student", "resident", "hosteller", "hostel resident"}
    return person_type in student_types or designation in student_types


def is_designated_kiosk_account(user, kiosk_username=None):
    """Only the vendor's unlinked kiosk user may activate kiosk mode."""
    if str(user.get("role") or "").strip().lower() != "user":
        return False
    if user.get("person_id") not in (None, "", 0, "0"):
        return False

    username = normalize_login_email(user.get("username"))
    designated_username = normalize_login_email(kiosk_username)
    if designated_username:
        return username == designated_username
    return bool(user.get("is_kiosk"))


def _table_exists(conn, table_name):
    cursor = conn.cursor()
    if getattr(conn, "_is_pg", False):
        cursor.execute("SELECT to_regclass(?)", (table_name,))
        row = cursor.fetchone()
        return bool(row and row[0])
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def sync_person_login_identity(
    conn,
    *,
    person_id,
    vendor_id,
    profile,
    phone,
    old_phone="",
    phone_changed=False,
    student_account=False,
    password_hasher,
):
    """Keep a person's login aligned with their current profile email.

    Email-only profile edits must rename the linked login as well. Existing
    Google links are deliberately removed when the email changes so the old
    Google account cannot continue authenticating as the renamed person.
    """
    login_email = login_email_from_profile(profile)
    normalized_phone = str(phone or "").strip()
    if not login_email:
        return "skipped"

    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, password_plain, has_set_password FROM system_users "
        "WHERE person_id = ? AND vendor_id = ? LIMIT 1",
        (person_id, vendor_id),
    )
    login_row = cursor.fetchone()
    if login_row:
        old_username = str(login_row[0] or "")
        old_plain = login_row[1]
        has_set_password = int(login_row[2] or 0)
        renamed = normalize_login_email(old_username) != login_email

        if renamed:
            cursor.execute(
                "SELECT username FROM system_users WHERE LOWER(username) = LOWER(?) "
                "AND (person_id IS NULL OR person_id <> ?) LIMIT 1",
                (login_email, person_id),
            )
            if cursor.fetchone():
                raise LoginIdentityConflictError(
                    "This email address is already used by another login"
                )

            if _table_exists(conn, "external_auth_identities"):
                cursor.execute(
                    "DELETE FROM external_auth_identities WHERE LOWER(username) = LOWER(?)",
                    (old_username,),
                )
            cursor.execute(
                "UPDATE system_users SET username = ? WHERE person_id = ? AND vendor_id = ?",
                (login_email, person_id, vendor_id),
            )
            cursor.execute(
                "DELETE FROM active_sessions WHERE username = ?",
                (old_username,),
            )

        if normalized_phone and phone_changed and (
            has_set_password == 0 or old_plain == str(old_phone or "").strip()
        ):
            cursor.execute(
                "UPDATE system_users SET password = ?, password_plain = NULL "
                "WHERE person_id = ? AND vendor_id = ?",
                (password_hasher(normalized_phone), person_id, vendor_id),
            )
        return "renamed" if renamed else "unchanged"

    if not normalized_phone:
        return "skipped"

    role = "student" if student_account else "user"
    cursor.execute(
        "INSERT INTO system_users "
        "(username, password, password_plain, role, vendor_id, person_id) "
        "VALUES (?, ?, NULL, ?, ?, ?)",
        (
            login_email,
            password_hasher(normalized_phone),
            role,
            vendor_id,
            person_id,
        ),
    )
    return "created"


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

        # A linked person's current profile email is authoritative. This also
        # repairs older email-only edits that changed faces.custom_data but left
        # system_users.username on the previous address.
        target_email = login_email_from_profile(custom_data) or (
            normalize_login_email(username) if is_valid_login_email(username) else ""
        )
        if not target_email or target_email == username:
            continue

        cursor.execute(
            "SELECT username FROM system_users WHERE LOWER(username) = LOWER(?) AND username <> ? LIMIT 1",
            (target_email, username),
        )
        if cursor.fetchone():
            continue

        if _table_exists(conn, "external_auth_identities"):
            cursor.execute(
                "DELETE FROM external_auth_identities WHERE LOWER(username) = LOWER(?)",
                (username,),
            )
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
