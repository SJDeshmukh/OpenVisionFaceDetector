"""Canonical navigation permissions for PIN-based staff sessions."""

import json

from feature_policy import normalize_features


STAFF_NAV_ITEMS = (
    "dashboard",
    "people",
    "faces",
    "classes",
    "timetable",
    "wages",
    "attendance",
    "bulk_image_attendance",
    "live_attendance",
    "cameras",
    "reports",
    "settings",
    "leave_management",
    "face_reset_requests",
    "hostel_alerts",
    "hostel_allocation",
)

# PIN staff accounts are created as leave approvers. Existing rows have no saved
# navigation value, so keep their safe, useful landing pages during migration.
DEFAULT_STAFF_NAV_ITEMS = ("dashboard", "leave_management")
REQUIRED_STAFF_NAV_ITEMS = ("leave_management",)

# Base pages exist for every vendor. Every other page requires at least one of
# the listed subscription features before SuperAdmin may assign it to staff.
BASE_STAFF_NAV_ITEMS = ("dashboard", "people", "settings", "attendance")
STAFF_NAV_FEATURE_REQUIREMENTS = {
    "faces": ("classes", "bulk_image_attendance"),
    "classes": ("classes", "bulk_image_attendance", "lecture_wise_reports"),
    "timetable": ("shifts", "add_shift"),
    "wages": ("payroll", "report_payroll"),
    "bulk_image_attendance": ("bulk_image_attendance",),
    "live_attendance": ("live_attendance",),
    "cameras": ("cameras",),
    "reports": ("reports", "report_detailed", "report_payroll", "lecture_wise_reports"),
    "leave_management": ("leave_management",),
    "face_reset_requests": ("parent_login",),
    "hostel_alerts": ("hostel_attendance_alerts",),
    "hostel_allocation": ("hostel_allocation",),
}


def normalize_staff_nav_items(value, *, use_default=True):
    """Return a stable list of known staff navigation keys.

    ``None`` represents a legacy row and receives the safe default. Explicit
    values are validated so a misspelled key cannot silently grant or hide a
    different module.
    """
    if value is None or value == "":
        items = list(DEFAULT_STAFF_NAV_ITEMS) if use_default else []
    elif isinstance(value, str):
        try:
            items = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("navbar_items must be a JSON array") from exc
    else:
        items = value

    if not isinstance(items, (list, tuple, set)):
        raise ValueError("navbar_items must be an array")

    requested = {str(item).strip() for item in items if str(item).strip()}
    unknown = sorted(requested.difference(STAFF_NAV_ITEMS))
    if unknown:
        raise ValueError(f"Unknown navigation item(s): {', '.join(unknown)}")

    requested.update(REQUIRED_STAFF_NAV_ITEMS)
    return [item for item in STAFF_NAV_ITEMS if item in requested]


def serialize_staff_nav_items(value):
    return json.dumps(normalize_staff_nav_items(value), separators=(",", ":"))


def available_staff_nav_items(features):
    """Return navigation keys supported by a vendor's enabled features."""
    try:
        selected_features = set(normalize_features(features, reject_unknown=False))
    except ValueError:
        selected_features = set()
    allowed = set(BASE_STAFF_NAV_ITEMS)
    for item, requirements in STAFF_NAV_FEATURE_REQUIREMENTS.items():
        if selected_features.intersection(requirements):
            allowed.add(item)
    return [item for item in STAFF_NAV_ITEMS if item in allowed]


def normalize_staff_nav_items_for_features(value, features):
    """Validate an assignment against the vendor's current subscription."""
    normalized = normalize_staff_nav_items(value)
    allowed = set(available_staff_nav_items(features))
    unavailable = [item for item in normalized if item not in allowed]
    if unavailable:
        raise ValueError(
            "Navigation item(s) not enabled for this vendor: " + ", ".join(unavailable)
        )
    return normalized


def serialize_staff_nav_items_for_features(value, features):
    return json.dumps(
        normalize_staff_nav_items_for_features(value, features),
        separators=(",", ":"),
    )


def load_staff_nav_items(value):
    """Read a persisted value and fail closed to the legacy staff default."""
    try:
        return normalize_staff_nav_items(value)
    except ValueError:
        return list(DEFAULT_STAFF_NAV_ITEMS)


def load_staff_nav_items_for_features(value, features):
    """Read persisted access and immediately remove features since disabled."""
    allowed = set(available_staff_nav_items(features))
    return [item for item in load_staff_nav_items(value) if item in allowed]


def staff_can_access(value, item):
    if item not in STAFF_NAV_ITEMS:
        return False
    return item in load_staff_nav_items(value)
