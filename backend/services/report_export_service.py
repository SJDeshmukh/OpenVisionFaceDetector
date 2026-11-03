"""Pure row formatting helpers for professional attendance and payroll exports."""


PAYROLL_EXPORT_HEADERS = [
    "Employee ID", "Employee Name", "Department", "Designation", "Shift",
    "Period Start", "Period End", "Days Present", "Scheduled Hours / Day",
    "Total Working Hours", "Regular Hours", "Overtime Hours",
    "Daily Salary Rate(s) Applied", "Gross Earnings", "Basic", "HRA",
    "Conveyance", "Special Allowance", "PF Deduction", "ESI Deduction",
    "Professional Tax", "Late Deduction", "Approved Advance Deduction",
    "Total Deductions", "Net Payroll",
]


def payroll_export_values(item, start_date, end_date):
    """Build one period-level payroll row for one employee."""
    breakdown = item.get("breakdown") or {}
    components = breakdown.get("components") or {}
    statutory = breakdown.get("deductions") or {}
    late_deduction = float(item.get("late_deduction") or 0)
    advance_deduction = float(item.get("advance_deduction") or 0)
    statutory_total = float(statutory.get("total_statutory") or 0)
    total_deductions = round(statutory_total + late_deduction + advance_deduction, 2)
    rates = item.get("salary_rates_applied") or []
    salary_rates = ", ".join(f"{float(rate):.2f}" for rate in rates)
    if not salary_rates:
        salary_rates = f"{float(item.get('daily_wage') or 0):.2f}"
    return [
        item.get("display_id") or item.get("person_id"),
        item.get("name") or "",
        item.get("department") or "",
        item.get("designation") or "",
        item.get("shift") or "",
        start_date,
        end_date,
        int(item.get("days_present") or 0),
        float(item.get("scheduled_hours_per_day") or 0),
        float(item.get("total_hours") or 0),
        float(item.get("regular_hours") or 0),
        float(item.get("overtime_hours") or 0),
        salary_rates,
        float(breakdown.get("gross") or item.get("base_cost") or 0),
        float(components.get("basic") or 0),
        float(components.get("hra") or 0),
        float(components.get("conveyance") or 0),
        float(components.get("special_allowance") or 0),
        float(statutory.get("pf") or 0),
        float(statutory.get("esi") or 0),
        float(statutory.get("pt") or 0),
        late_deduction,
        advance_deduction,
        total_deductions,
        float(item.get("final_payout") or 0),
    ]
