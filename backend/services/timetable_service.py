"""Small, database-independent helpers for timetable mutations."""

import json


def json_list(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def remove_activities_for_shift(activities_value, shift_id):
    """Remove every activity associated with a shift."""
    target = str(shift_id)
    activities = json_list(activities_value)
    return [
        item for item in activities
        if not isinstance(item, dict) or str(item.get("shift_id")) != target
    ]


def remove_shift(shifts_value, activities_value, shift_id):
    """Remove one shift and all activities associated with it."""
    target = str(shift_id)
    shifts = json_list(shifts_value)
    remaining = [
        item for item in shifts
        if not isinstance(item, dict) or str(item.get("id")) != target
    ]
    if len(remaining) == len(shifts):
        return None, json_list(activities_value)

    return remaining, remove_activities_for_shift(activities_value, shift_id)


def remove_activity(activities_value, activity_id):
    """Remove one activity from a draft timetable."""
    target = str(activity_id)
    activities = json_list(activities_value)
    remaining = [item for item in activities if str(item.get("id")) != target]
    return None if len(remaining) == len(activities) else remaining
