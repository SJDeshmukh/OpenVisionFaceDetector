from services.report_export_service import payroll_export_headers, payroll_export_values


def test_payroll_export_contains_only_requested_period_summary_columns():
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
        "pf_enabled": 1,
        "esi_enabled": 0,
        "gratuity_enabled": 1,
        "final_payout": 2055,
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
                "pt": 20,
                "total_statutory": 120,
            },
            "provisions": {"gratuity": 55},
        },
    }

    headers = payroll_export_headers([item])
    row = payroll_export_values(item, "2026-10-01", "2026-10-31", headers)
    values = dict(zip(headers, row))

    assert len(row) == len(headers)
    assert values["Employee Name"] == "Anant Batre"
    assert values["Shift"] == "Work"
    assert values["Start Date"] == "2026-10-01"
    assert values["End Date"] == "2026-10-31"
    assert values["Days Present"] == 2
    assert values["Hours Per Day"] == 8
    assert values["Total Working Hours"] == 17
    assert values["Daily Salary"] == "1000.00, 1200.00"
    assert values["PF Deduction"] == 100
    assert "ESI Deduction" not in headers
    assert values["Gratuity"] == 55
    assert values["Approved Advance"] == 100
    assert values["Total Deductions"] == 245
    assert values["Net Payroll"] == 2055

    removed_columns = {
        "Employee ID", "Department", "Designation", "Regular Hours",
        "Overtime Hours", "Gross Earnings", "Basic", "HRA", "Conveyance",
        "Special Allowance", "Professional Tax", "Late Deduction",
    }
    assert removed_columns.isdisjoint(headers)


def test_optional_statutory_columns_appear_only_when_enabled_in_selection():
    no_benefits = {"name": "One", "pf_enabled": 0, "esi_enabled": "false"}
    esi_employee = {"name": "Two", "esi_enabled": "1", "gratuity_enabled": 0}

    headers_without_benefits = payroll_export_headers([no_benefits])
    headers_with_esi = payroll_export_headers([no_benefits, esi_employee])

    assert "PF Deduction" not in headers_without_benefits
    assert "ESI Deduction" not in headers_without_benefits
    assert "Gratuity" not in headers_without_benefits
    assert "ESI Deduction" in headers_with_esi
    assert "PF Deduction" not in headers_with_esi
    assert "Gratuity" not in headers_with_esi
