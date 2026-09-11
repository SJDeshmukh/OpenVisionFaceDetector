import pytest

from services.employee_email_reports_service import employee_email, month_period


def test_employee_email_accepts_configured_custom_field():
    assert employee_email({"custom_data": '{"employee_email":"Worker@Example.com"}'}) == "worker@example.com"


def test_employee_email_rejects_invalid_values():
    assert employee_email({"custom_data": '{"email":"not-an-email"}'}) is None


def test_month_period_covers_the_complete_selected_month():
    start, end = month_period("2026-02")
    assert start.isoformat() == "2026-02-01"
    assert end.isoformat() == "2026-02-28"


def test_month_period_rejects_non_month_input():
    with pytest.raises(ValueError, match="YYYY-MM"):
        month_period("2026-02-15")
