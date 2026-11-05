import sqlite3
import unittest

from services.config_utils import canonical_registration_field, validate_registration_values


class RegistrationValidationTests(unittest.TestCase):
    def test_aliases_satisfy_required_core_fields(self):
        config = [
            {"field": "full_name", "label": "Employee Name", "required": True},
            {"field": "mobile_number", "label": "Mobile Number", "required": True},
            {"field": "work_shift", "label": "Assigned Shift", "required": True},
        ]
        error = validate_registration_values(
            config,
            core_values={"name": "Anant", "phone": "9999999999", "shift": "Work"},
        )
        self.assertIsNone(error)

    def test_exact_missing_field_is_returned(self):
        config = [
            {"field": "employee_code", "label": "Employee Code", "required": True},
            {"field": "blood_group", "label": "Blood Group", "required": False},
        ]
        error = validate_registration_values(config, core_values={"name": "Anant"})
        self.assertEqual(error, {
            "error": "Employee Code is required",
            "field": "employee_code",
        })

    def test_disabled_and_optional_fields_do_not_block(self):
        config = [
            {"field": "disabled_field", "required": True, "enabled": False},
            {"field": "optional_field", "required": False, "enabled": True},
        ]
        self.assertIsNone(validate_registration_values(config, core_values={"name": "Anant"}))

    def test_no_shift_is_missing_when_shift_is_required(self):
        config = [{"field": "shift", "label": "Shift", "required": True}]
        error = validate_registration_values(config, core_values={"shift": "No Shift"})
        self.assertEqual(error["field"], "shift")

    def test_canonical_field_normalizes_labels_and_aliases(self):
        self.assertEqual(canonical_registration_field(" Mobile Number "), "phone")
        self.assertEqual(canonical_registration_field("Employee Code"), "employee_code")
        self.assertEqual(canonical_registration_field("EmployeeName"), "name")
        self.assertEqual(canonical_registration_field("employeeName"), "name")
        self.assertEqual(canonical_registration_field("phoneNumber"), "phone")
        self.assertEqual(canonical_registration_field("WorkShift"), "shift")

    def test_pascal_case_name_config_accepts_core_name(self):
        config = [
            {"field": "EmployeeName", "label": "Employee name", "required": True},
            {"field": "Plant", "label": "Plant", "required": True},
        ]
        error = validate_registration_values(
            config,
            core_values={"name": "Sudha"},
            custom_values={"Plant": "A"},
        )
        self.assertIsNone(error)


class LocalUidUpsertCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE faces (id INTEGER PRIMARY KEY, vendor_id INTEGER, local_uid TEXT, name TEXT)"
        )
        self.conn.execute(
            "CREATE UNIQUE INDEX idx_faces_vendor_local_uid "
            "ON faces(vendor_id, local_uid) WHERE local_uid IS NOT NULL"
        )

    def tearDown(self):
        self.conn.close()

    def test_partial_conflict_target_updates_non_null_key(self):
        sql = (
            "INSERT INTO faces(vendor_id, local_uid, name) VALUES (?, ?, ?) "
            "ON CONFLICT(vendor_id, local_uid) WHERE local_uid IS NOT NULL "
            "DO UPDATE SET name = excluded.name"
        )
        self.conn.execute(sql, (8, "device-1", "First"))
        self.conn.execute(sql, (8, "device-1", "Updated"))
        rows = self.conn.execute("SELECT name FROM faces").fetchall()
        self.assertEqual(rows, [("Updated",)])

    def test_null_key_uses_plain_insert(self):
        sql = "INSERT INTO faces(vendor_id, local_uid, name) VALUES (?, ?, ?)"
        self.conn.execute(sql, (8, None, "First"))
        self.conn.execute(sql, (8, None, "Second"))
        count = self.conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
