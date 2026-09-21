import sqlite3
import unittest

from services.leave_workflow_service import (
    current_stage,
    decide_current_stage,
    get_active_workflow,
    replace_workflow,
    snapshot_request,
)


class LeaveWorkflowServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE leave_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER NOT NULL,
                name TEXT NOT NULL, version INTEGER NOT NULL, is_active INTEGER NOT NULL,
                created_by TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(vendor_id, version)
            );
            CREATE TABLE leave_workflow_stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id INTEGER NOT NULL,
                stage_key TEXT NOT NULL, display_name TEXT NOT NULL, actor_type TEXT NOT NULL,
                role_key TEXT, sequence INTEGER NOT NULL, department_scoped INTEGER NOT NULL,
                auth_method TEXT NOT NULL, UNIQUE(workflow_id, sequence), UNIQUE(workflow_id, stage_key)
            );
            CREATE TABLE leave_requests (
                id INTEGER PRIMARY KEY, vendor_id INTEGER, rector_status TEXT DEFAULT 'pending',
                hod_status TEXT DEFAULT 'pending', parent_status TEXT DEFAULT 'pending',
                final_status TEXT DEFAULT 'pending'
            );
            CREATE TABLE leave_request_stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
                vendor_id INTEGER NOT NULL, workflow_id INTEGER, workflow_version INTEGER NOT NULL,
                stage_key TEXT NOT NULL, display_name TEXT NOT NULL, actor_type TEXT NOT NULL,
                role_key TEXT, sequence INTEGER NOT NULL, department_scoped INTEGER NOT NULL,
                auth_method TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', actor_id TEXT,
                actor_name TEXT, decided_at DATETIME, decision_metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(request_id, sequence)
            );
            INSERT INTO leave_requests (id, vendor_id) VALUES (10, 1);
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_default_workflow_and_snapshot(self):
        workflow = get_active_workflow(self.conn, 1)
        self.assertEqual([s["role_key"] for s in workflow["stages"]], ["rector", "hod", "parent"])
        stages = snapshot_request(self.conn, 1, 10)
        self.assertEqual(current_stage(stages)["display_name"], "Rector")

    def test_custom_flow_is_versioned_and_request_snapshot_does_not_change(self):
        replace_workflow(self.conn, 1, "Short", [
            {"display_name": "Warden", "actor_type": "staff", "role_key": "warden"},
            {"display_name": "Parent", "actor_type": "parent"},
        ], "admin")
        original = snapshot_request(self.conn, 1, 10)
        replace_workflow(self.conn, 1, "Changed", [
            {"display_name": "HOD", "actor_type": "staff", "role_key": "hod"},
        ], "admin")
        preserved = snapshot_request(self.conn, 1, 10)
        self.assertEqual([s["display_name"] for s in original], ["Warden", "Parent"])
        self.assertEqual([s["display_name"] for s in preserved], ["Warden", "Parent"])

    def test_decisions_advance_and_finalise(self):
        replace_workflow(self.conn, 1, "Short", [
            {"display_name": "Warden", "actor_type": "staff", "role_key": "warden"},
            {"display_name": "Parent", "actor_type": "parent"},
        ], "admin")
        request_row = dict(self.conn.execute("SELECT * FROM leave_requests WHERE id = 10").fetchone())
        decide_current_stage(
            self.conn, 1, request_row, "approved", actor_type="staff",
            role_key="warden", actor_id=4, actor_name="A Warden",
        )
        self.assertEqual(current_stage(snapshot_request(self.conn, 1, 10))["actor_type"], "parent")
        request_row = dict(self.conn.execute("SELECT * FROM leave_requests WHERE id = 10").fetchone())
        decide_current_stage(
            self.conn, 1, request_row, "approved", actor_type="parent",
            role_key="parent", actor_id=8, actor_name="Parent",
        )
        status = self.conn.execute("SELECT final_status FROM leave_requests WHERE id = 10").fetchone()[0]
        self.assertEqual(status, "approved")

    def test_legacy_statuses_are_preserved_in_snapshot(self):
        self.conn.execute(
            "UPDATE leave_requests SET rector_status = 'approved', hod_status = 'pending' WHERE id = 10"
        )
        self.conn.commit()
        request_row = dict(self.conn.execute("SELECT * FROM leave_requests WHERE id = 10").fetchone())
        stages = snapshot_request(self.conn, 1, 10, request_row)
        self.assertEqual([stage["status"] for stage in stages], ["approved", "pending", "pending"])
        self.assertEqual(current_stage(stages)["role_key"], "hod")


if __name__ == "__main__":
    unittest.main()
