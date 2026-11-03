from services.report_export_service import PAYROLL_EXPORT_HEADERS, payroll_export_values


def test_payroll_export_is_one_period_row_with_complete_calculation():
    item = {
        "person_id": 7,
        "display_id": 3,
        "name": "Anant Batre",
        "department": "Production",
        "designation": "Operator",
        "shift": "Work",
        "days_present": 2,
        "scheduled_hours_per_day": 8,
        "total_hours": 17,
        "regular_hours": 16,
        "overtime_hours": 1,
        "salary_rates_applied": [1000, 1200],
        "late_deduction": 25,
        "advance_deduction": 100,
        "final_payout": 2075,
        "breakdown": {
            "gross": 2300,
            "components": {
                "basic": 1150,
                "hra": 460,
                "conveyance": 0,
                "special_allowance": 690,
            },
            "deductions": {
                "pf": 100,
                "esi": 0,
                "pt": 0,
                "total_statutory": 100,
            },
        },
    }

    row = payroll_export_values(item, "2026-10-01", "2026-10-31")
    values = dict(zip(PAYROLL_EXPORT_HEADERS, row))

    assert len(row) == len(PAYROLL_EXPORT_HEADERS)
    assert values["Period Start"] == "2026-10-01"
    assert values["Period End"] == "2026-10-31"
    assert values["Days Present"] == 2
    assert values["Total Working Hours"] == 17
    assert values["Daily Salary Rate(s) Applied"] == "1000.00, 1200.00"
    assert values["Gross Earnings"] == 2300
    assert values["Total Deductions"] == 225
    assert values["Net Payroll"] == 2075
    assert "Attendance Date" not in PAYROLL_EXPORT_HEADERS
