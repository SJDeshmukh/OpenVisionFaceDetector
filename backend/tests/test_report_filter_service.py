import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.report_filter_service import (
    custom_value,
    custom_filter_values,
    face_matches,
    facet_options,
    merge_filter_configuration,
)


def test_no_configuration_means_no_implicit_report_filters():
    visible, labels, dynamic = merge_filter_configuration([], [])
    assert not any(visible.values())
    assert dynamic == []
    assert labels["department"] == "Department"


def test_filters_only_merge_superadmin_and_bulk_fields():
    registration = [
        {"field": "department", "label": "Department", "enabled": True},
        {"field": "student_id", "label": "Student ID", "enabled": True},
    ]
    bulk = [
        {"name": "division", "label": "Division / Section"},
        {"name": "name", "label": "Student Name", "is_name": True},
    ]
    visible, _, dynamic = merge_filter_configuration(registration, bulk)
    assert visible["department"] is True
    assert visible["phone"] is False
    assert {field["key"] for field in dynamic} == {"student_id", "division"}
    assert "class_year" not in {field["key"] for field in dynamic}
    assert "branch" not in {field["key"] for field in dynamic}


def test_superadmin_disabled_field_overrides_stale_bulk_field():
    registration = [{"field": "phone", "enabled": False}]
    bulk = [{"name": "phone", "label": "Mobile"}]
    visible, _, dynamic = merge_filter_configuration(registration, bulk)
    assert visible["phone"] is False
    assert dynamic == []


def test_custom_values_are_case_spacing_and_alias_tolerant():
    custom = {"Student ID": "S-10", "Class / Section": "A"}
    assert custom_value(custom, "student_id") == "S-10"
    assert custom_value(custom, "id_number") == "S-10"
    assert custom_value(custom, "class_section") == "A"


def test_multi_select_custom_values_are_individually_filterable():
    custom = {"Skills": ["Welding", "Assembly"]}
    assert custom_filter_values(custom, "skills") == ["Welding", "Assembly"]
    face = {"department": "Ops", "custom": custom}
    assert face_matches(face, {}, {"skills": "Welding"}) is True
    assert face_matches(face, {}, {"skills": "Packing"}) is False


def test_faceting_can_exclude_its_own_filter_but_keep_other_filters():
    face = {"department": "Ops", "designation": "Lead", "shift": "Night", "phone": "1", "custom": {"Site": "A"}}
    selected = {"department": "Sales", "designation": "Lead"}
    assert face_matches(face, selected, {"Site": "A"}, exclude_standard="department") is True
    assert face_matches(face, selected, {"Site": "B"}, exclude_standard="department") is False


def test_selected_report_filters_are_combined_with_and_logic():
    face = {
        "department": "Ops",
        "designation": "Lead",
        "shift": "Night",
        "phone": "999",
        "custom": {"Site": "Plant A", "Skills": ["Welding", "Assembly"]},
    }
    standard = {"department": "Ops", "designation": "Lead", "shift": "Night"}
    assert face_matches(face, standard, {"site": "Plant A", "skills": "Assembly"}) is True
    assert face_matches(face, {**standard, "shift": "Day"}, {"site": "Plant A"}) is False
    assert face_matches(face, standard, {"site": "Plant B"}) is False


def test_configured_dropdown_options_are_narrowed_by_available_employee_values():
    configured = ["Mumbai", "Pune", "Nagpur"]
    assert facet_options({"Pune", "Mumbai"}, configured) == ["Mumbai", "Pune"]
    assert facet_options({"Pune"}, configured) == ["Pune"]
    assert facet_options(set(), configured) == []
