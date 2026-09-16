import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.login_identity_service import (
    is_valid_login_email,
    login_email_from_profile,
    normalize_login_email,
)


def test_login_identity_requires_and_normalizes_email():
    assert normalize_login_email("  PERSON@Example.COM ") == "person@example.com"
    assert is_valid_login_email("person@example.com") is True
    assert is_valid_login_email("EMP-1001") is False


def test_profile_email_aliases_are_normalized():
    assert login_email_from_profile({"employee_email": " Staff@Example.com "}) == "staff@example.com"
    assert login_email_from_profile('{"student_email":"student@example.com"}') == "student@example.com"
    assert login_email_from_profile({"email": "employee-id"}) == ""
