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


def remove_shift(shifts_value, activities_value, shift_id):
    """Remove one shift and unlink it from draft activities."""
    target = str(shift_id)
    shifts = json_list(shifts_value)
    activities = json_list(activities_value)
    remaining = [item for item in shifts if str(item.get("id")) != target]
    if len(remaining) == len(shifts):
        return None, activities

    unlinked = []
    for activity in activities:
        item = dict(activity)
        if str(item.get("shift_id")) == target:
            item["shift_id"] = ""
        unlinked.append(item)
    return remaining, unlinked


def remove_activity(activities_value, activity_id):
    """Remove one activity from a draft timetable."""
    target = str(activity_id)
    activities = json_list(activities_value)
    remaining = [item for item in activities if str(item.get("id")) != target]
    return None if len(remaining) == len(activities) else remaining
