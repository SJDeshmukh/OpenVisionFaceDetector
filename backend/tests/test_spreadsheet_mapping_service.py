import json
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import spreadsheet_mapping_service as mapping_service


class FakeProvider:
    model = "nvidia.nemotron-nano-3-30b"
    usage_totals = {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}

    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return {"role": "assistant", "content": self.response}


def test_deterministic_mapping_understands_common_business_headers(monkeypatch):
    monkeypatch.setenv("SPREADSHEET_LLM_MAPPING_ENABLED", "false")
    headers = ["Employee Code", "Employee Name", "Mobile Number", "Job Title", "Branch", "Work Shift"]
    result = mapping_service.map_spreadsheet_headers(headers, [], context="employee")
    assert result["method"] == "deterministic"
    assert result["mapping"] == {
        "name": "Employee Name",
        "phone": "Mobile Number",
        "person_id": "Employee Code",
        "department": "Branch",
        "designation": "Job Title",
        "shift": "Work Shift",
    }


def test_student_mapping_keeps_parent_identity_separate(monkeypatch):
    monkeypatch.setenv("SPREADSHEET_LLM_MAPPING_ENABLED", "false")
    result = mapping_service.map_spreadsheet_headers(
        ["Student Name", "Student Mobile", "Guardian Name", "Parent WhatsApp"],
        [],
        context="student",
    )
    assert result["mapping"] == {
        "name": "Student Name",
        "parent_name": "Guardian Name",
        "parent_phone": "Parent WhatsApp",
    }


def test_llm_maps_custom_headers_in_one_call_without_receiving_row_values(monkeypatch):
    monkeypatch.setenv("SPREADSHEET_LLM_MAPPING_ENABLED", "true")
    provider = FakeProvider('```json\n{"mapping":{"name":"Associate","phone":"Reach No","person_id":"Badge Ref","email":"invented"}}\n```')
    rows = [{"Associate": "Private Person", "Reach No": "+91 9999999999", "Badge Ref": "EMP-77"}]

    result = mapping_service.map_spreadsheet_headers(
        list(rows[0]), rows, context="employee", provider=provider,
    )

    assert result["method"] == "llm_assisted"
    assert result["mapping"] == {
        "name": "Associate", "phone": "Reach No", "person_id": "Badge Ref",
    }
    assert len(provider.calls) == 1
    prompt = json.dumps(provider.calls[0][0])
    assert "Private Person" not in prompt
    assert "9999999999" not in prompt
    assert "EMP-77" not in prompt
    assert provider.calls[0][1] == []


def test_invalid_model_headers_are_ignored_and_known_aliases_win(monkeypatch):
    monkeypatch.setenv("SPREADSHEET_LLM_MAPPING_ENABLED", "true")
    provider = FakeProvider('{"mapping":{"name":"Guardian Name","phone":"Not A Header","email":"Email Address"}}')
    headers = ["Student Name", "Guardian Name", "Email Address"]
    result = mapping_service.map_spreadsheet_headers(headers, [], context="student", provider=provider)
    assert result["mapping"]["name"] == "Student Name"
    assert result["mapping"]["email"] == "Email Address"
    assert "phone" not in result["mapping"]


def test_manual_mapping_is_validated_and_skips_llm(monkeypatch):
    monkeypatch.setenv("SPREADSHEET_LLM_MAPPING_ENABLED", "true")
    provider = FakeProvider("should not be called")
    result = mapping_service.map_spreadsheet_headers(
        ["Col A", "Col B"], [], provider=provider,
        manual_mapping={"name": "Col B", "phone": "missing", "unknown": "Col A"},
    )
    assert result == {"mapping": {"name": "Col B"}, "method": "manual", "warning": None}
    assert provider.calls == []


def test_provider_failure_uses_safe_deterministic_fallback(monkeypatch):
    monkeypatch.setenv("SPREADSHEET_LLM_MAPPING_ENABLED", "true")

    class FailingProvider:
        def complete(self, messages, tools):
            raise RuntimeError("offline")

    result = mapping_service.map_spreadsheet_headers(
        ["Full Name", "Phone Number"], [], provider=FailingProvider(),
    )
    assert result["method"] == "deterministic"
    assert result["mapping"] == {"name": "Full Name", "phone": "Phone Number"}
    assert result["warning"]
