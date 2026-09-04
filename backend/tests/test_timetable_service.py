import json

from services.timetable_service import json_list, remove_activity, remove_shift


def test_json_list_accepts_json_and_rejects_non_lists():
    assert json_list('[{"id": 1}]') == [{"id": 1}]
    assert json_list('{"id": 1}') == []
    assert json_list(None) == []


def test_remove_shift_matches_string_or_numeric_ids_and_unlinks_activities():
    shifts = [{"id": 10, "name": "Day"}, {"id": 20, "name": "Night"}]
    activities = [{"id": 1, "shift_id": "10"}, {"id": 2, "shift_id": 20}]
    remaining, unlinked = remove_shift(json.dumps(shifts), activities, "10")
    assert remaining == [{"id": 20, "name": "Night"}]
    assert unlinked == [{"id": 1, "shift_id": ""}, {"id": 2, "shift_id": 20}]


def test_remove_activity_reports_missing_and_removes_existing():
    activities = [{"id": 1, "name": "Work"}, {"id": "2", "name": "Break"}]
    assert remove_activity(activities, "missing") is None
    assert remove_activity(activities, 2) == [{"id": 1, "name": "Work"}]
