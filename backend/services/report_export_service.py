"""Pure row formatting helpers for professional attendance and payroll exports."""


BASE_PAYROLL_EXPORT_HEADERS = [
    "Employee Name",
    "Shift",
    "Start Date",
    "End Date",
    "Days Present",
    "Hours Per Day",
    "Total Working Hours",
    "Daily Salary",
]

OPTIONAL_PAYROLL_EXPORT_HEADERS = (
    ("PF Deduction", "pf_enabled"),
    ("ESI Deduction", "esi_enabled"),
    ("Gratuity", "gratuity_enabled"),
)

PAYROLL_EXPORT_TAIL_HEADERS = [
    "Approved Advance",
    "Total Deductions",
    "Net Payroll",
]


def _is_enabled(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _benefit_amount(item, label):
    breakdown = item.get("breakdown") or {}
    if label == "Gratuity":
        return float((breakdown.get("provisions") or {}).get("gratuity") or 0)
    key = "pf" if label == "PF Deduction" else "esi"
    return float((breakdown.get("deductions") or {}).get(key) or 0)


def payroll_export_headers(items):
    """Return customer-facing columns, including only enabled statutory benefits."""
    rows = items or []
    optional = [
        label
        for label, flag in OPTIONAL_PAYROLL_EXPORT_HEADERS
        if any(
            _is_enabled(item.get(flag)) or _benefit_amount(item, label) != 0
            for item in rows
        )
    ]
    return BASE_PAYROLL_EXPORT_HEADERS + optional + PAYROLL_EXPORT_TAIL_HEADERS


def payroll_export_values(item, start_date, end_date, headers=None):
    """Build one period-level payroll row for one employee."""
    breakdown = item.get("breakdown") or {}
    statutory = breakdown.get("deductions") or {}
    provisions = breakdown.get("provisions") or {}
    late_deduction = float(item.get("late_deduction") or 0)
    advance_deduction = float(item.get("advance_deduction") or 0)
    statutory_total = float(statutory.get("total_statutory") or 0)
    total_deductions = round(statutory_total + late_deduction + advance_deduction, 2)
    rates = item.get("salary_rates_applied") or []
    normalized_rates = sorted({float(rate) for rate in rates})
    if len(normalized_rates) == 1:
        salary_rates = normalized_rates[0]
    elif normalized_rates:
        salary_rates = ", ".join(f"{rate:.2f}" for rate in normalized_rates)
    else:
        salary_rates = float(item.get("daily_wage") or 0)
    values = {
        "Employee Name": item.get("name") or "",
        "Shift": item.get("shift") or "",
        "Start Date": start_date,
        "End Date": end_date,
        "Days Present": int(item.get("days_present") or 0),
        "Hours Per Day": float(item.get("scheduled_hours_per_day") or 0),
        "Total Working Hours": float(item.get("total_hours") or 0),
        "Daily Salary": salary_rates,
        "PF Deduction": (
            float(statutory.get("pf") or 0)
            if _is_enabled(item.get("pf_enabled")) or float(statutory.get("pf") or 0) != 0
            else ""
        ),
        "ESI Deduction": (
            float(statutory.get("esi") or 0)
            if _is_enabled(item.get("esi_enabled")) or float(statutory.get("esi") or 0) != 0
            else ""
        ),
        "Gratuity": (
            float(provisions.get("gratuity") or 0)
            if _is_enabled(item.get("gratuity_enabled"))
            or float(provisions.get("gratuity") or 0) != 0
            else ""
        ),
        "Approved Advance": advance_deduction,
        "Total Deductions": total_deductions,
        "Net Payroll": float(item.get("final_payout") or 0),
    }
    selected_headers = headers or payroll_export_headers([item])
    return [values[label] for label in selected_headers]
