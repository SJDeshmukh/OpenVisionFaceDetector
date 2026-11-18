import pytest

from services.config_utils import normalize_registration_config


def test_normalizes_editable_spreadsheet_types_and_options():
    config = normalize_registration_config([
        {
            "field": "plant",
            "label": "Plant",
            "type": "dropdown",
            "required": True,
            "options": ["A", " a ", "B", "", None],
        },
        {
            "field": "daily_wage",
            "label": "Daily wage",
            "type": "number",
            "options": ["must not be retained"],
        },
    ])

    assert config[0]["type"] == "select"
    assert config[0]["options"] == ["A", "B"]
    assert config[0]["required"] is True
    assert config[1]["type"] == "number"
    assert config[1]["options"] == []


@pytest.mark.parametrize("field", ["__proto__", "prototype", "constructor"])
def test_rejects_object_prototype_field_names(field):
    with pytest.raises(ValueError, match="unsupported registration field name"):
        normalize_registration_config([{"field": field, "type": "text"}])


def test_rejects_unsupported_dynamic_input_types():
    with pytest.raises(ValueError, match="unsupported registration field type"):
        normalize_registration_config([{"field": "unsafe", "type": "button"}])


def test_identity_and_phone_fields_remain_text():
    config = normalize_registration_config([
        {"field": "EmployeeName", "type": "number", "is_name": True},
        {"field": "phone", "type": "number", "is_phone": True},
        {"field": "student_id", "type": "number", "is_id": True},
    ])

    assert [field["type"] for field in config] == ["text", "text", "text"]
