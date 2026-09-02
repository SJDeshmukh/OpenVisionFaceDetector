import os
import sys
from getpass import getpass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from app import app as _app  # ensures .env is loaded
from db_factory import get_db_connection
from services.auth_service import hash_password


def read_password():
    """Read the new password without silently falling back to a shared default."""
    password = os.environ.get("NEW_SUPERADMIN_PASSWORD")
    if password:
        return password
    if not sys.stdin.isatty():
        raise RuntimeError(
            "NEW_SUPERADMIN_PASSWORD is required when running non-interactively"
        )

    password = getpass("New Super Admin password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise RuntimeError("Passwords do not match")
    return password


def main():
    new_pwd = read_password()
    if len(new_pwd) < 8:
        raise RuntimeError("Password must contain at least 8 characters")

    encoded_password = hash_password(new_pwd)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT username FROM system_users WHERE username = ? LIMIT 1",
            ("superadmin",),
        )
        exists = c.fetchone() is not None
        if exists:
            c.execute(
                """UPDATE system_users
                   SET password = ?, password_plain = NULL,
                       role = 'super_admin', vendor_id = NULL
                   WHERE username = ?""",
                (encoded_password, "superadmin"),
            )
            action = "updated"
        else:
            c.execute(
                """INSERT INTO system_users
                   (username, password, password_plain, role, vendor_id)
                   VALUES (?, ?, NULL, 'super_admin', NULL)""",
                ("superadmin", encoded_password),
            )
            action = "created"
        conn.commit()
        print(f"Super Admin account {action} successfully.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
