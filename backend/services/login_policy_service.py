WEB_PASSWORD_ADMIN_ROLES = frozenset({
    "super_admin",
    "vendor_admin",
    "admin",
    "owner",
})


def can_use_password_login(role, platform):
    """Allow non-admin credentials on mobile/kiosk, but never on the web app."""
    normalized_platform = str(platform or "web").strip().lower()
    normalized_role = str(role or "").strip().lower()
    return normalized_platform != "web" or normalized_role in WEB_PASSWORD_ADMIN_ROLES
