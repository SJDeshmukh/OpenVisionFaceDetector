import json
import os
import sys


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.person_scope_service import (  # noqa: E402
    apply_class_mapping,
    class_scope_matches,
    has_class_allocation,
    person_type_for,
    requested_person_type,
)


def test_linked_faculty_role_wins_over_conflicting_custom_type():
    custom = {"person_type": "student", "class_id": "12"}

    assert person_type_for(custom, system_role="faculty", vertical="school") == "faculty"


def test_school_legacy_non_faculty_defaults_to_student():
    assert person_type_for({}, vertical="school") == "student"
    assert person_type_for({}, system_role="user", vertical="hostel") == "student"
    assert requested_person_type(None, "school") == "student"
    assert requested_person_type(None, "factory") is None


def test_class_mapping_uses_class_id_and_exact_legacy_scope():
    mapped = apply_class_mapping(
        {"person_type": "student"}, 7, class_year="10", division="A", branch="Science",
    )

    assert has_class_allocation(mapped)
    assert class_scope_matches(mapped, class_id=7, class_year="ignored")
    assert not class_scope_matches(mapped, class_id=8, class_year="10", division="A")
    assert class_scope_matches(
        json.dumps({"class_year": "10", "division": "A", "branch": "Science"}),
        class_year="10", division="a", branch="science",
    )
    assert not class_scope_matches(
        {"class_year": "10", "division": "AB"}, class_year="10", division="A",
    )
    assert not class_scope_matches(
        {"class_year": "10", "division": "A"}, class_id=7,
    )
    assert class_scope_matches(
        {"class_year": "10", "division": "A"},
        class_id=7,
        class_year="10",
        division="A",
    )
