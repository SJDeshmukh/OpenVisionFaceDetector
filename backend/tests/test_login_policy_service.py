import pytest

from services.login_policy_service import can_use_password_login


@pytest.mark.parametrize("role", ["super_admin", "vendor_admin", "admin", "owner"])
def test_admin_roles_can_use_web_password_login(role):
    assert can_use_password_login(role, "web") is True


@pytest.mark.parametrize("role", ["student", "resident", "faculty", "staff", "user", "leave_staff"])
def test_non_admin_roles_cannot_use_web_password_login(role):
    assert can_use_password_login(role, "web") is False


@pytest.mark.parametrize("platform", ["mobile", "kiosk"])
def test_non_admin_password_login_remains_available_outside_web(platform):
    assert can_use_password_login("user", platform) is True
