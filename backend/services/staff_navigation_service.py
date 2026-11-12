"""Canonical navigation permissions for PIN-based staff sessions."""

import json


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


def load_staff_nav_items(value):
    """Read a persisted value and fail closed to the legacy staff default."""
    try:
        return normalize_staff_nav_items(value)
    except ValueError:
        return list(DEFAULT_STAFF_NAV_ITEMS)


def staff_can_access(value, item):
    if item not in STAFF_NAV_ITEMS:
        return False
    return item in load_staff_nav_items(value)
