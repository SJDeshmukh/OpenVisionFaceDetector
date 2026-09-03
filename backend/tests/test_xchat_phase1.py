import json
import sqlite3
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import xchat_service, xchat_tools
from services.xchat_presenter import build_presentation


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def xchat_db(tmp_path, monkeypatch):
    path = tmp_path / "xchat.sqlite"
    conn = _connection(path)
    conn.executescript("""
        CREATE TABLE vendors (id INTEGER PRIMARY KEY, company_name TEXT, status TEXT);
        CREATE TABLE subscriptions (vendor_id INTEGER, features TEXT);
        CREATE TABLE companies (vendor_id INTEGER, live_timetable TEXT, working_hours REAL);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, name TEXT, department TEXT, designation TEXT, daily_wage REAL, face_image TEXT, display_id INTEGER, shift TEXT);
        CREATE TABLE attendance (id INTEGER PRIMARY KEY, vendor_id INTEGER, person_id INTEGER, name TEXT, timestamp TEXT, status TEXT, activity TEXT, is_late INTEGER, captured_image TEXT);
        CREATE TABLE xchat_conversations (id TEXT PRIMARY KEY, vendor_id INTEGER, username TEXT, title TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE xchat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, vendor_id INTEGER, username TEXT, role TEXT, content TEXT, tool_name TEXT, message_metadata TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_username TEXT, actor_role TEXT, target_vendor_id INTEGER, action TEXT, details TEXT, ip TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.executemany("INSERT INTO vendors VALUES (?, ?, 'active')", [(1, "Alpha"), (2, "Beta")])
    conn.executemany("INSERT INTO subscriptions VALUES (?, ?)", [
        (1, json.dumps(["xchat_ai", "payroll"])), (2, json.dumps(["xchat_ai", "payroll"])),
    ])
    conn.executemany("INSERT INTO companies VALUES (?, '[]', 8)", [(1,), (2,)])
    conn.executemany("INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (11, 1, "Alice", "Ops", "Worker", 800, "alice-photo", 101, "Day"),
        (12, 1, "Aaron", "Sales", "Worker", 400, None, 102, "Night"),
        (21, 2, "Bob", "Ops", "Worker", 5000, "bob-photo", 201, "Day"),
    ])
    conn.executemany("INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 1, 11, "Alice", "2026-08-01 09:00:00", "CHECK_IN", "Work", 0, "alice-capture"),
        (2, 1, 11, "Alice", "2026-08-01 17:00:00", "CHECK_OUT", "Work", 0, None),
        (3, 1, 12, "Aaron", "2026-08-01 22:00:00", "CHECK_IN", "Work", 1, None),
        (4, 1, 12, "Aaron", "2026-08-02 06:00:00", "CHECK_OUT", "Work", 0, None),
        (5, 2, 21, "Bob", "2026-08-01 09:00:00", "CHECK_IN", "Work", 0, "bob-capture"),
        (6, 2, 21, "Bob", "2026-08-01 21:00:00", "CHECK_OUT", "Work", 0, None),
    ])
    conn.commit()
    conn.close()
    monkeypatch.setattr(xchat_tools, "_db", lambda: _connection(path))
    monkeypatch.setattr(xchat_service, "_db", lambda: _connection(path))
    def calculate_daily_hours(records, _timetable):
        checkin = None
        sessions = []
        for record in records:
            timestamp = datetime.fromisoformat(str(record["timestamp"]))
            if record["status"] == "CHECK_IN":
                checkin = timestamp
            elif record["status"] == "CHECK_OUT" and checkin:
                sessions.append({
                    "start_ts": checkin.isoformat(),
                    "duration_mins": (timestamp - checkin).total_seconds() / 60,
                    "is_payable": True,
                })
                checkin = None
        return {"sessions": sessions}
    monkeypatch.setitem(sys.modules, "services.attendance_service", types.SimpleNamespace(calculate_daily_hours=calculate_daily_hours))
    return path


def test_tool_schemas_never_expose_tenant_identity():
    assert len(xchat_tools.TOOL_SCHEMAS) == 15
    for tool in xchat_tools.TOOL_SCHEMAS:
        properties = tool["function"]["parameters"]["properties"]
        assert "vendor_id" not in properties


def test_attendance_tool_is_strictly_vendor_scoped(xchat_db):
    alpha = xchat_tools.get_attendance_summary(1, "2026-08-01", "2026-08-01")
    beta = xchat_tools.get_attendance_summary(2, "2026-08-01", "2026-08-01")
    assert alpha["employees"] == 2
    assert alpha["present_person_days"] == 2
    assert beta["employees"] == 1
    assert beta["present_person_days"] == 1


def test_absent_people_lists_registered_people_without_attendance(xchat_db):
    result = xchat_tools.get_absent_people(1, "2026-08-02")
    assert result["absent_count"] == 1
    assert [person["name"] for person in result["people"]] == ["Alice"]
    assert xchat_tools.get_absent_people(1, "2026-08-01")["absent_count"] == 0
    assert xchat_tools.get_absent_people(2, "2026-08-02")["people"][0]["name"] == "Bob"


def test_person_image_lookup_is_name_searchable_and_vendor_scoped(xchat_db):
    result = xchat_tools.get_person_images(1, "ali")
    assert result["matched_people"] == 1
    assert result["image_count"] == 2
    assert {item["image"] for item in result["images"]} == {"alice-photo", "alice-capture"}
    assert xchat_tools.get_person_images(1, "Bob")["matched_people"] == 0


def test_individual_payroll_lookup_is_name_searchable_and_vendor_scoped(xchat_db):
    result = xchat_tools.get_person_payroll(1, "ali", "2026-08-01", "2026-08-01")
    assert result["matched_people"] == 1
    assert result["people"][0]["name"] == "Alice"
    assert result["total_payable_hours"] == 8
    assert result["estimated_wages"] == 800
    assert xchat_tools.get_person_payroll(1, "Bob", "2026-08-01", "2026-08-01")["matched_people"] == 0


def test_model_cannot_override_injected_vendor(xchat_db, monkeypatch):
    observed = {}
    monkeypatch.setitem(xchat_tools.TOOL_REGISTRY, "get_attendance_summary", lambda vendor_id, **kwargs: observed.setdefault("vendor_id", vendor_id) or {})
    xchat_tools.execute_tool(
        "get_attendance_summary",
        {"vendor_id": 2, "start_date": "2026-08-01", "end_date": "2026-08-01"},
        vendor_id=1,
        features=["xchat_ai", "reports"],
    )
    assert observed["vendor_id"] == 1


def test_payroll_tool_requires_entitlement(xchat_db):
    with pytest.raises(PermissionError):
        xchat_tools.execute_tool(
            "get_payroll_summary",
            {"start_date": "2026-08-01", "end_date": "2026-08-01"},
            vendor_id=1,
            features=["xchat_ai"],
        )


def test_only_enabled_feature_tools_are_exposed():
    payroll_tools = {
        item["function"]["name"]
        for item in xchat_tools.available_tool_schemas(["xchat_ai", "payroll"])
    }
    assert {"get_people_summary", "get_payroll_summary", "compare_payroll_periods", "get_employee_hours_ranking"} <= payroll_tools
    assert "get_leave_summary" not in payroll_tools
    assert "get_device_status" not in payroll_tools

    leave_tools = {
        item["function"]["name"]
        for item in xchat_tools.available_tool_schemas(["xchat_ai", "leave_management"])
    }
    assert leave_tools == {"get_people_summary", "get_person_images", "get_leave_summary"}


def test_orchestrator_sends_only_entitled_tools_to_mistral():
    captured = {}

    class CaptureProvider:
        def complete(self, messages, tools):
            captured["prompt"] = messages[0]["content"]
            captured["tools"] = {item["function"]["name"] for item in tools}
            return {"role": "assistant", "content": "Leave management is enabled."}

    result = xchat_service.answer_question(
        "What can I ask about leave?", [], 1, ["xchat_ai", "leave_management"], provider=CaptureProvider(),
    )
    assert result["answer"] == "Leave management is enabled."
    assert captured["tools"] == {"get_people_summary", "get_person_images", "get_leave_summary"}
    assert "leave_management" in captured["prompt"]
    assert "- payroll:" not in captured["prompt"]


def test_disabled_feature_tool_cannot_be_called_directly(xchat_db):
    with pytest.raises(PermissionError):
        xchat_tools.execute_tool("get_device_status", {}, vendor_id=1, features=["xchat_ai"])


def test_payroll_calculation_and_overnight_pairing_are_scoped(xchat_db):
    summary = xchat_tools.get_payroll_summary(1, "2026-08-01", "2026-08-01")
    assert summary["total_payable_hours"] == 16
    assert summary["estimated_wages"] == 1200
    incomplete = xchat_tools.get_incomplete_attendance(1, "2026-08-01", "2026-08-01")
    assert incomplete["count"] == 0


def test_date_ranges_are_bounded():
    with pytest.raises(ValueError, match="366"):
        xchat_tools.get_attendance_summary(1, "2025-01-01", "2026-12-31")


def test_conversation_history_is_vendor_and_user_scoped(xchat_db):
    alpha_id = xchat_service.create_conversation(1, "alpha-admin", "Alpha only")
    xchat_service.save_exchange(alpha_id, 1, "alpha-admin", "question", "answer")
    assert len(xchat_service.get_messages(alpha_id, 1, "alpha-admin")) == 2
    with pytest.raises(xchat_service.XChatNotFoundError):
        xchat_service.get_messages(alpha_id, 2, "beta-admin")
    with pytest.raises(xchat_service.XChatNotFoundError):
        xchat_service.get_messages(alpha_id, 1, "another-alpha-user")


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call-1", "function": {"name": "get_attendance_summary", "arguments": json.dumps({
                    "vendor_id": 2, "start_date": "2026-08-01", "end_date": "2026-08-01",
                })},
            }]}
        tool_data = json.loads(messages[-1]["content"])["data"]
        return {"role": "assistant", "content": f"There are {tool_data['employees']} employees for 2026-08-01."}


def test_orchestrator_executes_tool_and_audits_metadata_only(xchat_db):
    result = xchat_service.process_message(
        "How was attendance on 2026-08-01?", None, 1, "alpha-admin", "admin",
        ["xchat_ai", "payroll", "reports"], provider=FakeProvider(), ip_address="127.0.0.1",
    )
    assert "2 employees" in result["answer"]
    assert result["tools_used"] == ["get_attendance_summary"]
    conn = _connection(xchat_db)
    audit = conn.execute("SELECT details FROM audit_logs WHERE action = 'xchat_query'").fetchone()
    stored_messages = conn.execute("SELECT content FROM xchat_messages WHERE conversation_id = ?", (result["conversation_id"],)).fetchall()
    conn.close()
    assert audit is not None
    assert "How was attendance" not in audit["details"]
    assert "get_attendance_summary" in audit["details"]
    assert len(stored_messages) == 2


def test_failed_new_chat_leaves_audit_but_no_empty_history(xchat_db):
    class FailingProvider:
        def complete(self, _messages, _tools):
            raise xchat_service.XChatProviderError("unavailable")

    with pytest.raises(xchat_service.XChatProviderError):
        xchat_service.process_message(
            "Attendance today?", None, 1, "alpha-admin", "admin", ["xchat_ai"], provider=FailingProvider(),
        )
    conn = _connection(xchat_db)
    conversations = conn.execute("SELECT COUNT(*) FROM xchat_conversations").fetchone()[0]
    audit = conn.execute("SELECT details FROM audit_logs WHERE action = 'xchat_query'").fetchone()
    conn.close()
    assert conversations == 0
    assert json.loads(audit["details"])["status"] == "error"


def test_page_context_is_allow_listed():
    assert xchat_service._sanitize_context({"page": "/admin/secrets", "filters": {"vendor_id": "2"}}) == {}
    assert xchat_service._sanitize_context({"page": "/reports", "filters": {"department": "Ops", "vendor_id": "2"}}) == {
        "page": "/reports", "filters": {"department": "Ops"},
    }
    assert xchat_service._sanitize_context({"page": "/classes", "filters": {"class_year": "FY", "division": "A"}}) == {
        "page": "/classes", "filters": {"class_year": "FY", "division": "A"},
    }


def test_presenter_builds_indexed_table_and_requested_chart():
    result = {
        "period": {"start": "2026-08-01", "end": "2026-08-02"},
        "employees": 2, "present_person_days": 3, "late_person_days": 1, "attendance_rate_percent": 75,
        "daily_breakdown": [
            {"date": "2026-08-01", "present_employees": 2, "late_employees": 1, "attendance_events": 4},
            {"date": "2026-08-02", "present_employees": 1, "late_employees": 0, "attendance_events": 2},
        ],
    }
    presentation = build_presentation("Show an attendance line chart and list", [{"name": "get_attendance_summary", "result": result}])
    assert presentation["charts"][0]["type"] == "line"
    assert presentation["charts"][0]["data"][0]["index"] == 1
    assert presentation["tables"][0]["rows"][1]["index"] == 2


def test_presenter_builds_multi_period_payroll_trend():
    results = [
        {"name": "get_payroll_summary", "result": {"period": {"start": "2026-07-01", "end": "2026-07-31"}, "estimated_wages": 100, "total_payable_hours": 10}},
        {"name": "get_payroll_summary", "result": {"period": {"start": "2026-08-01", "end": "2026-08-31"}, "estimated_wages": 150, "total_payable_hours": 14}},
    ]
    presentation = build_presentation("Give me a monthly payroll trend chart", results)
    chart = next(chart for chart in presentation["charts"] if chart["id"] == "payroll-multi-period-trend")
    assert chart["type"] == "line"
    assert [row["estimated_wages"] for row in chart["data"]] == [100, 150]


def test_structured_presentation_is_persisted_in_history(xchat_db):
    conversation_id = xchat_service.create_conversation(1, "alpha-admin")
    presentation = {"tables": [{"id": "safe", "columns": [], "rows": []}]}
    xchat_service.save_exchange(conversation_id, 1, "alpha-admin", "List attendance", "Here it is.", {"presentation": presentation})
    messages = xchat_service.get_messages(conversation_id, 1, "alpha-admin")
    assert messages[-1]["metadata"]["presentation"] == presentation
