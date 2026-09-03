"""Convert allow-listed XChat tool results into safe UI presentation data."""

from collections import Counter


CHART_WORDS = ("chart", "graph", "trend", "visual", "plot", "pie", "bar", "line")
LIST_WORDS = ("list", "table", "breakdown", "details", "detail", "who", "which", "rank")
MAX_PRESENTATION_ROWS = 100


def _indexed(rows):
    return [{"index": position, **row} for position, row in enumerate((rows or [])[:MAX_PRESENTATION_ROWS], 1)]


def _chart_type(question):
    query = str(question or "").lower()
    if "pie" in query:
        return "pie"
    if "line" in query or "trend" in query:
        return "line"
    return "bar"


def _wants_chart(question):
    query = str(question or "").lower()
    return any(word in query for word in CHART_WORDS)


def _wants_list(question):
    query = str(question or "").lower()
    return any(word in query for word in LIST_WORDS)


def _table(table_id, title, columns, rows, filename):
    return {
        "id": table_id,
        "title": title,
        "columns": columns,
        "rows": _indexed(rows),
        "download_name": filename,
    }


def _chart(chart_id, chart_type, title, index_label, series, rows, filename):
    return {
        "id": chart_id,
        "type": chart_type,
        "title": title,
        "index_label": index_label,
        "series": series,
        "data": _indexed(rows),
        "download_name": filename,
    }


def build_presentation(question, tool_results):
    """Return a bounded declarative UI contract; never include raw database rows."""
    presentation = {"metrics": [], "tables": [], "charts": [], "images": []}
    wants_chart = _wants_chart(question)
    wants_list = _wants_list(question)
    requested_chart_type = _chart_type(question)
    payroll_summaries = [item for item in (tool_results or []) if item.get("name") == "get_payroll_summary"]

    for item in tool_results or []:
        name = item.get("name")
        result = item.get("result") or {}
        period = result.get("period") or {}
        period_label = " to ".join(filter(None, [period.get("start"), period.get("end")]))

        if name == "get_attendance_summary":
            presentation["metrics"].extend([
                {"label": "Employees", "value": result.get("employees", 0), "format": "number"},
                {"label": "Present employee-days", "value": result.get("present_person_days", 0), "format": "number"},
                {"label": "Late employee-days", "value": result.get("late_person_days", 0), "format": "number"},
                {"label": "Attendance rate", "value": result.get("attendance_rate_percent", 0), "format": "percent"},
            ])
            rows = result.get("daily_breakdown") or []
            if rows and (wants_list or wants_chart):
                presentation["tables"].append(_table(
                    "attendance-daily", f"Daily attendance · {period_label}",
                    [
                        {"key": "date", "label": "Date", "format": "date"},
                        {"key": "present_employees", "label": "Present", "format": "number"},
                        {"key": "late_employees", "label": "Late", "format": "number"},
                        {"key": "attendance_events", "label": "Events", "format": "number"},
                    ], rows, "attendance-daily.csv",
                ))
            if rows and wants_chart:
                presentation["charts"].append(_chart(
                    "attendance-trend", requested_chart_type, f"Attendance trend · {period_label}", "Date",
                    [
                        {"key": "present_employees", "label": "Present", "color": "#22d3ee"},
                        {"key": "late_employees", "label": "Late", "color": "#f59e0b"},
                    ], [{"label": row.get("date"), **row} for row in rows], "attendance-trend.png",
                ))

        elif name == "get_absent_people":
            presentation["metrics"].append({"label": "Absent people", "value": result.get("absent_count", 0), "format": "number"})
            rows = result.get("people") or []
            presentation["tables"].append(_table(
                "absent-people", f"Absent people · {result.get('date') or ''}",
                [
                    {"key": "display_id", "label": "ID"}, {"key": "name", "label": "Name"},
                    {"key": "department", "label": "Department"}, {"key": "designation", "label": "Designation"},
                    {"key": "shift", "label": "Shift"},
                ], rows, "absent-people.csv",
            ))

        elif name == "get_payroll_summary":
            presentation["metrics"].extend([
                {"label": "Estimated wages", "value": result.get("estimated_wages", 0), "format": "currency", "currency": result.get("currency", "INR")},
                {"label": "Payable hours", "value": result.get("total_payable_hours", 0), "format": "hours"},
                {"label": "Employees with hours", "value": result.get("employees_with_hours", 0), "format": "number"},
            ])
            rows = result.get("employee_breakdown") or []
            if rows and (wants_list or wants_chart):
                presentation["tables"].append(_table(
                    "payroll-employees", f"Employee wage breakdown · {period_label}",
                    [
                        {"key": "name", "label": "Employee"},
                        {"key": "department", "label": "Department"},
                        {"key": "hours", "label": "Hours", "format": "hours"},
                        {"key": "estimated_wages", "label": "Estimated wages", "format": "currency", "currency": result.get("currency", "INR")},
                    ], rows, "employee-wages.csv",
                ))
            if rows and wants_chart and len(payroll_summaries) == 1:
                wage_chart = not any(word in str(question).lower() for word in ("hour", "time"))
                value_key = "estimated_wages" if wage_chart else "hours"
                presentation["charts"].append(_chart(
                    "payroll-employees-chart", requested_chart_type,
                    f"{'Estimated wages' if wage_chart else 'Payable hours'} by employee · {period_label}", "Employee",
                    [{"key": value_key, "label": "Estimated wages" if wage_chart else "Hours", "color": "#38bdf8"}],
                    [{"label": row.get("name"), **row} for row in rows], "employee-payroll-chart.png",
                ))

        elif name == "get_person_payroll":
            presentation["metrics"].extend([
                {"label": "Estimated wages", "value": result.get("estimated_wages", 0), "format": "currency", "currency": result.get("currency", "INR")},
                {"label": "Payable hours", "value": result.get("total_payable_hours", 0), "format": "hours"},
                {"label": "Matching people", "value": result.get("matched_people", 0), "format": "number"},
            ])
            rows = result.get("people") or []
            if rows:
                presentation["tables"].append(_table(
                    "person-payroll", f"Individual payroll · {period_label}",
                    [
                        {"key": "name", "label": "Employee"}, {"key": "department", "label": "Department"},
                        {"key": "designation", "label": "Designation"}, {"key": "hours", "label": "Hours", "format": "hours"},
                        {"key": "estimated_wages", "label": "Estimated wages", "format": "currency", "currency": result.get("currency", "INR")},
                    ], rows, "individual-payroll.csv",
                ))

        elif name == "get_person_advances":
            presentation["metrics"].extend([
                {"label": "Total advances", "value": result.get("total_advance", 0), "format": "currency", "currency": result.get("currency", "INR")},
                {"label": "Advance records", "value": result.get("advance_count", 0), "format": "number"},
            ])
            presentation["tables"].append(_table(
                "person-advances", "Individual advance history",
                [
                    {"key": "name", "label": "Employee"}, {"key": "date", "label": "Date", "format": "date"},
                    {"key": "amount", "label": "Total", "format": "currency", "currency": result.get("currency", "INR")},
                    {"key": "amount_cash", "label": "Cash", "format": "currency", "currency": result.get("currency", "INR")},
                    {"key": "amount_online", "label": "Online", "format": "currency", "currency": result.get("currency", "INR")},
                    {"key": "deduction_month", "label": "Deduction month"}, {"key": "status", "label": "Status"},
                ], result.get("records") or [], "individual-advances.csv",
            ))

        elif name == "compare_payroll_periods":
            current, previous = result.get("current") or {}, result.get("previous") or {}
            currency = result.get("currency", "INR")
            rows = [
                {"period": "Current", "date_range": _period_text(current), "estimated_wages": current.get("estimated_wages", 0), "hours": current.get("total_payable_hours", 0)},
                {"period": "Previous", "date_range": _period_text(previous), "estimated_wages": previous.get("estimated_wages", 0), "hours": previous.get("total_payable_hours", 0)},
            ]
            presentation["metrics"].append({"label": "Wage change", "value": result.get("change", 0), "format": "currency", "currency": currency})
            presentation["tables"].append(_table(
                "payroll-comparison", "Payroll period comparison",
                [
                    {"key": "period", "label": "Period"}, {"key": "date_range", "label": "Dates"},
                    {"key": "hours", "label": "Hours", "format": "hours"},
                    {"key": "estimated_wages", "label": "Estimated wages", "format": "currency", "currency": currency},
                ], rows, "payroll-comparison.csv",
            ))
            if wants_chart:
                presentation["charts"].append(_chart(
                    "payroll-comparison-chart", requested_chart_type, "Estimated wages by period", "Period",
                    [{"key": "estimated_wages", "label": "Estimated wages", "color": "#22d3ee"}],
                    [{"label": row["period"], **row} for row in rows], "payroll-comparison.png",
                ))

        elif name == "get_employee_hours_ranking":
            rows = result.get("employees") or []
            presentation["tables"].append(_table(
                "employee-hours", f"Employee hours ranking · {period_label}",
                [
                    {"key": "name", "label": "Employee"}, {"key": "department", "label": "Department"},
                    {"key": "designation", "label": "Designation"}, {"key": "hours", "label": "Hours", "format": "hours"},
                    {"key": "estimated_wages", "label": "Estimated wages", "format": "currency", "currency": "INR"},
                ], rows, "employee-hours-ranking.csv",
            ))
            if rows and wants_chart:
                presentation["charts"].append(_chart(
                    "employee-hours-chart", requested_chart_type, f"Employee hours · {period_label}", "Employee",
                    [{"key": "hours", "label": "Hours", "color": "#22d3ee"}],
                    [{"label": row.get("name"), **row} for row in rows], "employee-hours.png",
                ))

        elif name == "get_incomplete_attendance":
            rows = result.get("records") or []
            presentation["metrics"].append({"label": "Incomplete records", "value": result.get("count", 0), "format": "number"})
            presentation["tables"].append(_table(
                "incomplete-attendance", f"Incomplete attendance · {period_label}",
                [
                    {"key": "name", "label": "Employee"}, {"key": "date", "label": "Date", "format": "date"},
                    {"key": "last_check_in", "label": "Last check-in", "format": "datetime"},
                    {"key": "department", "label": "Department"}, {"key": "reason", "label": "Reason"},
                ], rows, "incomplete-attendance.csv",
            ))
            if rows and wants_chart:
                counts = Counter(row.get("department") or "Unassigned" for row in rows)
                presentation["charts"].append(_chart(
                    "incomplete-by-department", requested_chart_type, "Incomplete attendance by department", "Department",
                    [{"key": "count", "label": "Records", "color": "#fb7185"}],
                    [{"label": label, "count": count} for label, count in sorted(counts.items())], "incomplete-by-department.png",
                ))

        elif name == "get_people_summary":
            presentation["metrics"].append({"label": "Registered people", "value": result.get("total_people", 0), "format": "number"})
            rows = result.get("people") or []
            if rows:
                presentation["tables"].append(_table(
                    "people", "Registered people",
                    [
                        {"key": "display_id", "label": "ID"}, {"key": "name", "label": "Name"},
                        {"key": "department", "label": "Department"}, {"key": "designation", "label": "Designation"},
                        {"key": "shift", "label": "Shift"}, {"key": "wage_configured", "label": "Wage configured"},
                    ], rows, "people.csv",
                ))
            breakdown = result.get("by_department") or {}
            if wants_chart and breakdown:
                presentation["charts"].append(_chart(
                    "people-by-department", requested_chart_type, "People by department", "Department",
                    [{"key": "count", "label": "People", "color": "#22d3ee"}],
                    [{"label": label, "count": value} for label, value in breakdown.items()], "people-by-department.png",
                ))

        elif name == "get_person_images":
            presentation["metrics"].extend([
                {"label": "Matching people", "value": result.get("matched_people", 0), "format": "number"},
                {"label": "Images found", "value": result.get("image_count", 0), "format": "number"},
            ])
            presentation["images"].extend(result.get("images") or [])

        elif name == "get_device_status":
            presentation["metrics"].extend([
                {"label": "Registered devices", "value": result.get("registered_devices", 0), "format": "number"},
                {"label": "Geofenced devices", "value": result.get("geofenced_devices", 0), "format": "number"},
            ])
            rows = result.get("devices") or []
            if rows:
                presentation["tables"].append(_table(
                    "devices", "Registered devices",
                    [
                        {"key": "name", "label": "Device"}, {"key": "last_active", "label": "Last active", "format": "datetime"},
                        {"key": "battery_percent", "label": "Battery", "format": "percent"},
                        {"key": "geofence_configured", "label": "Geofence"}, {"key": "geofence_radius_m", "label": "Radius (m)"},
                    ], rows, "device-status.csv",
                ))
            battery_rows = [row for row in rows if row.get("battery_percent") is not None]
            if wants_chart and battery_rows:
                presentation["charts"].append(_chart(
                    "device-battery", requested_chart_type, "Device battery levels", "Device",
                    [{"key": "battery_percent", "label": "Battery %", "color": "#34d399"}],
                    [{"label": row.get("name"), **row} for row in battery_rows], "device-battery.png",
                ))

        elif name == "get_shift_configuration":
            presentation["metrics"].extend([
                {"label": "Daily working hours", "value": result.get("working_hours_per_day", 0), "format": "hours"},
                {"label": "Configured shifts", "value": result.get("shift_count", 0), "format": "number"},
            ])
            rows = result.get("activities") or []
            if rows:
                presentation["tables"].append(_table(
                    "shift-activities", "Published timetable activities",
                    [
                        {"key": "name", "label": "Activity"}, {"key": "start_time", "label": "Start"},
                        {"key": "end_time", "label": "End"}, {"key": "type", "label": "Type"},
                        {"key": "is_payable", "label": "Payable"}, {"key": "overnight", "label": "Overnight"},
                    ], rows, "shift-activities.csv",
                ))

        elif name == "get_leave_summary":
            presentation["metrics"].append({"label": "Leave requests", "value": result.get("total_requests", 0), "format": "number"})
            rows = result.get("requests") or []
            if rows:
                presentation["tables"].append(_table(
                    "leave-requests", f"Leave requests · {period_label}",
                    [
                        {"key": "name", "label": "Name"}, {"key": "leave_type", "label": "Type"},
                        {"key": "start_date", "label": "Start", "format": "date"}, {"key": "end_date", "label": "End", "format": "date"},
                        {"key": "status", "label": "Status"},
                    ], rows, "leave-requests.csv",
                ))
            by_status = result.get("by_status") or {}
            if wants_chart and by_status:
                presentation["charts"].append(_chart(
                    "leave-status", requested_chart_type, f"Leave requests by status · {period_label}", "Status",
                    [{"key": "count", "label": "Requests", "color": "#818cf8"}],
                    [{"label": label, "count": value} for label, value in by_status.items()], "leave-status.png",
                ))

        elif name == "get_class_activity_summary":
            presentation["metrics"].extend([
                {"label": "Configured classes", "value": result.get("configured_classes", 0), "format": "number"},
                {"label": "Lectures", "value": result.get("lecture_count", 0), "format": "number"},
            ])
            rows = result.get("lectures") or []
            if rows:
                presentation["tables"].append(_table(
                    "class-lectures", f"Lecture activity · {period_label}",
                    [
                        {"key": "date", "label": "Date", "format": "date"}, {"key": "subject", "label": "Subject"},
                        {"key": "class_year", "label": "Class / Year"}, {"key": "division", "label": "Division"},
                        {"key": "branch", "label": "Branch"}, {"key": "teacher", "label": "Teacher"},
                        {"key": "attendance_count", "label": "Attendance", "format": "number"},
                    ], rows, "lecture-activity.csv",
                ))
            if wants_chart and rows:
                subject_counts = Counter(row.get("subject") or "Unspecified" for row in rows)
                presentation["charts"].append(_chart(
                    "lectures-by-subject", requested_chart_type, f"Lectures by subject · {period_label}", "Subject",
                    [{"key": "count", "label": "Lectures", "color": "#f59e0b"}],
                    [{"label": label, "count": count} for label, count in sorted(subject_counts.items())], "lectures-by-subject.png",
                ))

        elif name == "get_automated_report_status":
            presentation["metrics"].extend([
                {"label": "Schedule configured", "value": "Yes" if result.get("configured") else "No"},
                {"label": "Schedule enabled", "value": "Yes" if result.get("enabled") else "No"},
            ])
            rows = result.get("deliveries") or []
            if rows:
                presentation["tables"].append(_table(
                    "automated-report-deliveries", "Recent automated report deliveries",
                    [
                        {"key": "frequency", "label": "Frequency"}, {"key": "period_start", "label": "From", "format": "date"},
                        {"key": "period_end", "label": "To", "format": "date"}, {"key": "status", "label": "Status"},
                        {"key": "sent_at", "label": "Sent at", "format": "datetime"},
                    ], rows, "automated-report-deliveries.csv",
                ))
            if wants_chart and rows:
                status_counts = Counter(row.get("status") or "unknown" for row in rows)
                presentation["charts"].append(_chart(
                    "report-delivery-status", requested_chart_type, "Automated report delivery status", "Status",
                    [{"key": "count", "label": "Deliveries", "color": "#22d3ee"}],
                    [{"label": label, "count": count} for label, count in sorted(status_counts.items())], "report-delivery-status.png",
                ))

        elif name == "get_parent_access_summary":
            presentation["metrics"].extend([
                {"label": "Parent accounts", "value": result.get("parent_accounts", 0), "format": "number"},
                {"label": "Student-parent links", "value": result.get("student_parent_links", 0), "format": "number"},
                {"label": "Pending face resets", "value": result.get("pending_face_resets", 0), "format": "number"},
            ])

    if wants_chart and len(payroll_summaries) > 1:
        trend_rows = []
        for item in payroll_summaries:
            result = item.get("result") or {}
            trend_rows.append({
                "label": _period_text(result),
                "estimated_wages": result.get("estimated_wages", 0),
                "hours": result.get("total_payable_hours", 0),
            })
        presentation["charts"].append(_chart(
            "payroll-multi-period-trend", requested_chart_type, "Payroll trend by period", "Period",
            [
                {"key": "estimated_wages", "label": "Estimated wages", "color": "#22d3ee"},
                {"key": "hours", "label": "Hours", "color": "#818cf8"},
            ], trend_rows, "payroll-trend.png",
        ))

    return {key: value for key, value in presentation.items() if value}


def _period_text(result):
    period = result.get("period") or {}
    return " to ".join(filter(None, [period.get("start"), period.get("end")]))
