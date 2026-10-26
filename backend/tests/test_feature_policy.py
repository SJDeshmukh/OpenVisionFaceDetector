import unittest

from feature_policy import (
    ALL_FEATURES,
    FEATURE_DEPENDENCIES,
    normalize_features,
    remove_feature_and_dependents,
)


class FeaturePolicyTests(unittest.TestCase):
    def test_catalog_has_no_duplicates(self):
        self.assertEqual(len(ALL_FEATURES), len(set(ALL_FEATURES)))
        for feature, dependencies in FEATURE_DEPENDENCIES.items():
            self.assertIn(feature, ALL_FEATURES)
            self.assertTrue(set(dependencies).issubset(ALL_FEATURES))

    def test_dependencies_are_added_recursively_in_catalog_order(self):
        self.assertEqual(
            normalize_features(["payable_hours"]),
            ["reports", "report_payroll", "payroll", "payable_hours"],
        )
        self.assertEqual(
            normalize_features(["checkin_checkout"]),
            ["mobile_app", "enable_attendance", "checkin_checkout"],
        )

    def test_unknown_features_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown feature"):
            normalize_features(["reports", "made_up_feature"])

    def test_disabling_dependency_removes_dependent_features(self):
        self.assertEqual(
            remove_feature_and_dependents(
                ["reports", "report_payroll", "payroll", "payable_hours"],
                "reports",
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
