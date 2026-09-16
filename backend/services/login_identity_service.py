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

