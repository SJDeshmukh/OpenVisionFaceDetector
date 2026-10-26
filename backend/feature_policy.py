"""Canonical feature catalogue and dependency rules.

This module intentionally has no Flask or database imports so the policy can be
validated without booting the application.
"""

import json


ALL_FEATURES = [
    "reports", "report_detailed", "report_payroll", "automated_email_reports",
    "employee_reports", "xchat_ai", "mobile_app", "payroll", "shifts",
    "live_attendance", "cameras", "add_shift", "payable_hours",
    "enable_attendance", "night_shift_logic", "geofencing", "whatsapp_alerts",
    "hostel_attendance_alerts", "hostel_allocation", "api_access",
    "white_labeling", "late_mark", "bulk_image_attendance", "classes",
    "leave_management", "parent_login", "lecture_wise_reports",
    "parent_alerts", "checkin_checkout",
]


# Selecting a feature also selects everything it needs to work. Keeping this
# server-side prevents older dashboard builds from saving broken combinations.
FEATURE_DEPENDENCIES = {
    "report_detailed": ("reports",),
    "report_payroll": ("reports",),
    "automated_email_reports": ("reports", "report_detailed"),
    "employee_reports": ("reports", "report_detailed"),
    "payroll": ("reports", "report_payroll"),
    "payable_hours": ("payroll",),
    "add_shift": ("shifts",),
    "night_shift_logic": ("shifts",),
    "geofencing": ("mobile_app",),
    "whatsapp_alerts": ("reports",),
    "hostel_attendance_alerts": ("whatsapp_alerts",),
    "late_mark": ("enable_attendance",),
    "lecture_wise_reports": ("reports", "classes"),
    "parent_alerts": ("parent_login",),
    "checkin_checkout": ("enable_attendance", "mobile_app"),
}


def normalize_features(raw_features, *, reject_unknown=True):
    """Return a stable, de-duplicated feature list with dependencies included."""
    if raw_features is None:
        values = []
    elif isinstance(raw_features, str):
        try:
            values = json.loads(raw_features)
        except (TypeError, ValueError) as exc:
            raise ValueError("features must be a JSON array") from exc
    else:
        values = raw_features

    if not isinstance(values, (list, tuple, set)):
        raise ValueError("features must be an array")

    selected = {str(value).strip() for value in values if str(value).strip()}
    unknown = sorted(selected.difference(ALL_FEATURES))
    if reject_unknown and unknown:
        raise ValueError(f"Unknown feature(s): {', '.join(unknown)}")
    selected.difference_update(unknown)

    pending = list(selected)
    while pending:
        feature = pending.pop()
        for dependency in FEATURE_DEPENDENCIES.get(feature, ()):
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)

    return [feature for feature in ALL_FEATURES if feature in selected]


def remove_feature_and_dependents(raw_features, feature):
    """Remove a feature and every enabled feature that requires it."""
    selected = set(normalize_features(raw_features))
    removed = {feature}
    changed = True
    while changed:
        changed = False
        for candidate in tuple(selected):
            if candidate in removed:
                continue
            if any(dependency in removed for dependency in FEATURE_DEPENDENCIES.get(candidate, ())):
                removed.add(candidate)
                changed = True
    return [item for item in ALL_FEATURES if item in selected and item not in removed]
