import json
import csv
import io
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Blueprint, request, jsonify, send_file
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

from utils import (
    get_db_connection, get_table_columns, parse_db_date, cache_get, cache_set,
    vendor_has_feature, _run
)
from services.attendance_service import (
    calculate_daily_hours, calculate_expected_hours, calculate_arrival_status
)
from services.auth_service import require_auth
from middleware.validation import validate_request
from schemas import PayrollReportRequest
from flask import Blueprint, request, jsonify, send_file, g

attendance_reports_bp = Blueprint('attendance_reports_bp', __name__)

@attendance_reports_bp.route("/reports/analytics", methods=["GET"])
@require_auth()
@validate_request(PayrollReportRequest)
def get_analytics(valid_data: PayrollReportRequest):
    vendor_id = g.vendor_id
    
    start_date = valid_data.start_date
    end_date = valid_data.end_date
        
    cache_key = f"vendor:{vendor_id}:analytics:{start_date}:{end_date}"
    cached = cache_get(cache_key)
    if cached: return jsonify(cached)

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch Timetable
    timetable = []
    c.execute("SELECT live_timetable FROM companies WHERE vendor_id = ?", (vendor_id,))
    company_row = c.fetchone()
    if company_row and company_row['live_timetable']:
        try: timetable = json.loads(company_row['live_timetable'])
        except: pass
            
    # 2. Fetch Persons
    c.execute("SELECT id, name, department, designation FROM faces WHERE vendor_id = ?", (vendor_id,))
    persons = {row['id']: dict(row) for row in c.fetchall()}
    
    # 3. Fetch Attendance
    try:
        s_dt = datetime.strptime(start_date, '%Y-%m-%d')
        e_dt = datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError:
        conn.close(); return jsonify({"error": "Invalid date format"}), 400

    query = "SELECT * FROM attendance WHERE date(timestamp) BETWEEN ? AND ? AND vendor_id = ? ORDER BY timestamp ASC"
    c.execute(query, (start_date, end_date, vendor_id))
    rows = c.fetchall()
    conn.close()
    
    user_records = defaultdict(list)
    for row in rows:
        pid = row.get('person_id')
        if pid: user_records[pid].append(dict(row))
        
    # Analysis
    daily_stats = defaultdict(lambda: {"present": 0, "late": 0, "undertime": 0, "overtime": 0})
    person_stats = {}
    
    total_days = (e_dt - s_dt).days + 1
    all_dates = [(s_dt + timedelta(days=x)).strftime('%Y-%m-%d') for x in range(total_days)]
    
    for pid, person_info in persons.items():
        records = user_records.get(pid, [])
        p_total_hours = 0
        p_present_days = 0
        p_late_count = 0
        
        # Group records by date for this person
        p_date_records = defaultdict(list)
        for r in records:
            d_str = parse_db_date(r['timestamp'])
            if d_str: p_date_records[d_str.strftime('%Y-%m-%d')].append(r)
            
        for d_str in all_dates:
            d_records = p_date_records.get(d_str, [])
            if not d_records: continue
            
            stats = calculate_daily_hours(d_records, timetable, date_str=d_str)
            p_total_hours += stats['total_hours']
            p_present_days += 1
            
            # Check if late in any session of the day
            is_late_day = any(r.get('is_late') == 1 for r in d_records)
            if is_late_day: p_late_count += 1
            
            # Update daily global stats
            daily_stats[d_str]["present"] += 1
            if is_late_day: daily_stats[d_str]["late"] += 1
            
        person_stats[pid] = {
            "name": person_info['name'],
            "department": person_info['department'],
            "total_hours": round(p_total_hours, 2),
            "present_days": p_present_days,
            "late_count": p_late_count,
            "attendance_rate": round((p_present_days / total_days) * 100, 1) if total_days > 0 else 0
        }
    
    result = {
        "daily_stats": daily_stats,
        "person_stats": person_stats,
        "summary": {
            "total_persons": len(persons),
            "avg_attendance": round(sum(p['attendance_rate'] for p in person_stats.values()) / len(person_stats), 1) if person_stats else 0
        }
    }
    cache_set(cache_key, result, 300)
    return jsonify(result)

@attendance_reports_bp.route("/reports/export", methods=["GET"])
@require_auth()
@validate_request(PayrollReportRequest)
def export_attendance(valid_data: PayrollReportRequest):
    vendor_id = g.vendor_id
    
    start_date = valid_data.start_date
    end_date = valid_data.end_date
        
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = """
        SELECT a.name, a.timestamp, a.status, a.activity, a.is_late,
               f.department, f.designation, f.phone
        FROM attendance a
        LEFT JOIN faces f ON a.person_id = f.id
        WHERE date(a.timestamp) BETWEEN ? AND ? AND a.vendor_id = ?
        ORDER BY a.timestamp ASC
    """
    c.execute(query, (start_date, end_date, vendor_id))
    rows = c.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Timestamp", "Status", "Activity", "Is Late", "Department", "Designation", "Phone"])
    
    for row in rows:
        writer.writerow([
            row['name'], row['timestamp'], row['status'], row['activity'],
            "Yes" if row['is_late'] else "No",
            row['department'], row['designation'], row['phone']
        ])
        
    return output.getvalue(), 200, {
        "Content-Type": "text/csv",
        "Content-Disposition": f"attachment; filename=attendance_{start_date}_{end_date}.csv"
    }

@attendance_reports_bp.route("/reports/payroll", methods=["GET"])
@require_auth()
@validate_request(PayrollReportRequest)
def get_payroll_report(valid_data: PayrollReportRequest):
    vendor_id = g.vendor_id

    start_date = valid_data.start_date
    end_date = valid_data.end_date
        
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch Timetable and Working Hours
    c.execute("SELECT live_timetable, working_hours FROM companies WHERE vendor_id = ?", (vendor_id,))
    company_row = c.fetchone()

    timetable = []
    company_working_hours = 8.0 # Default
    if company_row:
        if company_row['live_timetable']:
            try: timetable = json.loads(company_row['live_timetable'])
            except: pass
        try:
            if company_row['working_hours']: company_working_hours = float(company_row['working_hours'])
        except: pass

    late_enabled = vendor_has_feature(vendor_id, "late_mark")

    # 2. Fetch Persons
    try:
        fcols = get_table_columns(conn, "faces")
        extra = [col for col in ["late_allowance_days", "late_deduction_amount"] if col in fcols]
        extra_select = ", " + ", ".join(extra) if extra else ""
        c.execute(f"SELECT id, name, daily_wage, department, designation, face_image, phone, display_id, custom_data{extra_select} FROM faces WHERE vendor_id = ?", (vendor_id,))
    except:
        c.execute("SELECT id, name, daily_wage, department, designation, face_image, phone FROM faces WHERE vendor_id = ?", (vendor_id,))
    
    persons = {row['id']: dict(row) for row in c.fetchall()}
    
    # 3. Fetch Global Settings
    c.execute("SELECT key, value FROM system_settings WHERE key IN ('global_late_allowance', 'global_late_deduction')")
    settings = {row['key']: row['value'] for row in c.fetchall()}
    global_allowance = int(settings.get('global_late_allowance', 7))
    global_deduction = float(settings.get('global_late_deduction', 0.0))
    
    # 4. Fetch Attendance
    try:
        s_dt = datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=1)
        e_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        conn.close(); return jsonify({"error": "Invalid date format"}), 400

    query = "SELECT * FROM attendance WHERE date(timestamp) BETWEEN ? AND ? AND vendor_id = ? ORDER BY timestamp ASC"
    c.execute(query, (s_dt.strftime('%Y-%m-%d'), e_dt.strftime('%Y-%m-%d'), vendor_id))
    rows = c.fetchall()
    conn.close()
    
    user_records = defaultdict(list)
    for row in rows:
        pid = row.get('person_id')
        if pid: user_records[pid].append(dict(row))
        
    payroll_data = []
    today_str = datetime.now().strftime('%Y-%m-%d')
    start_dt_req = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_dt_req = datetime.strptime(end_date, '%Y-%m-%d').date()

    for pid, person_info in persons.items():
        total_hours = 0
        present_dates = set()
        late_dates = set()
        
        records = user_records.get(pid, [])
        stats = calculate_daily_hours(records, timetable, date_str=today_str)
        
        for r in records:
            if r.get('is_late') == 1:
                r_dt = parse_db_date(r['timestamp'])
                if r_dt and start_dt_req <= r_dt <= end_dt_req:
                    late_dates.add(r_dt)
        
        late_marks_count = len(late_dates) if late_enabled else 0

        for session in stats.get('sessions', []):
            if session.get('start_ts'):
                try:
                    sess_start = datetime.fromisoformat(session['start_ts'])
                    sess_date = sess_start.date()
                    if start_dt_req <= sess_date <= end_dt_req and session.get('is_payable', False):
                        total_hours += (session.get('duration_mins', 0) / 60.0)
                        present_dates.add(sess_date)
                except: continue

        daily_wage = person_info.get('daily_wage') or 0
        hourly_rate = daily_wage / company_working_hours if daily_wage and company_working_hours > 0 else 0
        base_cost = round(total_hours * hourly_rate, 2)
        
        allowance = person_info.get('late_allowance_days') if person_info.get('late_allowance_days') is not None else global_allowance
        deduction_amt = person_info.get('late_deduction_amount') if person_info.get('late_deduction_amount') is not None else global_deduction
        
        deductable_lates = max(0, late_marks_count - allowance)
        total_deduction = round(deductable_lates * deduction_amt, 2)
        final_payout = round(base_cost - total_deduction, 2)
        
        payroll_data.append({
            "person_id": pid,
            "name": person_info.get('name'),
            "department": person_info.get('department'),
            "designation": person_info.get('designation'),
            "face_image": person_info.get('face_image'),
            "phone": person_info.get('phone'),
            "daily_wage": daily_wage,
            "total_hours": round(total_hours, 2),
            "days_present": len(present_dates),
            "base_cost": base_cost,
            "late_marks_count": late_marks_count,
            "late_deduction": total_deduction,
            "final_payout": final_payout,
            "custom_data": json.loads(person_info.get('custom_data') or '{}') if isinstance(person_info.get('custom_data'), str) else person_info.get('custom_data')
        })
    
    return jsonify({
        "payroll": payroll_data,
        "global_settings": {"allowance": global_allowance, "deduction": global_deduction}
    })

@attendance_reports_bp.route("/reports/payroll/export-daily", methods=["GET"])
@require_auth()
def export_payroll_daily():
    vendor_id = g.vendor_id
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date required"}), 400

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        c.execute("SELECT working_hours FROM companies WHERE vendor_id = ?", (vendor_id,))
        v_row = c.fetchone()
        company_working_hours = float(v_row['working_hours']) if v_row and v_row['working_hours'] else 8.0

        c.execute("SELECT * FROM attendance WHERE vendor_id = ?", (vendor_id,))
        rows = c.fetchall()
        user_records = defaultdict(list)
        for row in rows:
            d = dict(row)
            if d.get('person_id'): user_records[d['person_id']].append(d)
            
        c.execute("SELECT id, name, daily_wage, late_allowance_days, late_deduction_amount, shift FROM faces WHERE vendor_id = ?", (vendor_id,))
        persons = {r['id']: dict(r) for r in c.fetchall()}

        c.execute("SELECT key, value FROM system_settings WHERE key IN ('global_late_allowance', 'global_late_deduction')")
        s_map = {r['key']: r['value'] for r in c.fetchall()}
        global_allowance = int(s_map.get('global_late_allowance', 7))
        global_deduction = float(s_map.get('global_late_deduction', 0.0))

        start_dt_req = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt_req = datetime.strptime(end_date, '%Y-%m-%d').date()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["person_id","name","date","hours_payable","late_mark","deduction_applied","net_wage"])

        for pid, records in user_records.items():
            if pid not in persons: continue
            info = persons[pid]
            # Simple fallback for timetable if needed (would ideally use company timetable)
            timetable = []
            try:
                tjson = info.get('shift') or ""
                if tjson: timetable = json.loads(tjson) if isinstance(tjson, str) else (tjson or [])
            except: pass
            
            stats = calculate_daily_hours(records, timetable)
            per_day = defaultdict(float)
            for s in stats.get('sessions', []):
                try:
                    sd = datetime.fromisoformat(s['start_ts']).date()
                    if start_dt_req <= sd <= end_dt_req and s.get('is_payable', False):
                        per_day[sd] += (s.get('duration_mins', 0) or 0)
                except: continue

            late_dates = sorted(set(parse_db_date(r['timestamp']) for r in records if r.get('is_late') == 1 and parse_db_date(r['timestamp']) and start_dt_req <= parse_db_date(r['timestamp']) <= end_dt_req))
            allowance = info.get('late_allowance_days') if info.get('late_allowance_days') is not None else global_allowance
            deduction_amt = info.get('late_deduction_amount') if info.get('late_deduction_amount') is not None else global_deduction
            
            for d, mins in sorted(per_day.items()):
                lm = 1 if d in late_dates else 0
                idx = late_dates.index(d) + 1 if d in late_dates else 0
                deduct = deduction_amt if (lm == 1 and idx > allowance) else 0.0
                daily_wage = float(info.get('daily_wage') or 0.0)
                hourly_rate = daily_wage / company_working_hours if daily_wage and company_working_hours > 0 else 0
                base_wage_for_day = round((mins / 60.0) * hourly_rate, 2)
                writer.writerow([pid, info.get('name'), d.isoformat(), round(mins/60.0,2), lm, deduct, round(base_wage_for_day - deduct, 2)])
        
        return output.getvalue(), 200, {"Content-Type": "text/csv"}
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@attendance_reports_bp.route("/reports/payroll/export-excel", methods=["GET"])
@require_auth()
def export_payroll_excel():
    vendor_id = g.vendor_id
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date required"}), 400

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        c.execute("SELECT working_hours FROM companies WHERE vendor_id = ?", (vendor_id,))
        v_row = c.fetchone()
        company_working_hours = float(v_row['working_hours']) if v_row and v_row['working_hours'] else 8.0

        c.execute("SELECT * FROM attendance WHERE vendor_id = ?", (vendor_id,))
        rows = c.fetchall()
        user_records = defaultdict(list)
        for row in rows:
            d = dict(row)
            if d.get('person_id'): user_records[d['person_id']].append(d)
        
        c.execute("SELECT id, name, daily_wage, late_allowance_days, late_deduction_amount FROM faces WHERE vendor_id = ?", (vendor_id,))
        persons = {r['id']: dict(r) for r in c.fetchall()}

        c.execute("SELECT key, value FROM system_settings WHERE key IN ('global_late_allowance', 'global_late_deduction')")
        s_map = {r['key']: r['value'] for r in c.fetchall()}
        global_allowance = int(s_map.get('global_late_allowance', 7))
        global_deduction = float(s_map.get('global_late_deduction', 0.0))

        wb = Workbook()
        ws = wb.active
        ws.title = "Daily Payroll"
        headers = ["Person ID", "Name", "Date", "Working Hours", "Is Late", "Deduction", "Net Wage"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")

        start_dt_req = datetime.fromisoformat(start_date).date()
        end_dt_req = datetime.fromisoformat(end_date).date()

        for pid, records in user_records.items():
            if pid not in persons: continue
            info = persons[pid]
            stats = calculate_daily_hours(records)
            per_day = defaultdict(float)
            for s in stats.get('sessions', []):
                try:
                    sd = datetime.fromisoformat(s['start_ts']).date()
                    if start_dt_req <= sd <= end_dt_req and s.get('is_payable', False):
                        per_day[sd] += (s.get('duration_mins', 0) or 0)
                except: continue
            
            late_dates = sorted(set(parse_db_date(r['timestamp']) for r in records if r.get('is_late') == 1 and parse_db_date(r['timestamp']) and start_dt_req <= parse_db_date(r['timestamp']) <= end_dt_req))
            allowance = info.get('late_allowance_days') if info.get('late_allowance_days') is not None else global_allowance
            deduction_amt = info.get('late_deduction_amount') if info.get('late_deduction_amount') is not None else global_deduction
            
            for d, mins in sorted(per_day.items()):
                lm = 1 if d in late_dates else 0
                idx = late_dates.index(d) + 1 if d in late_dates else 0
                deduct = deduction_amt if (lm == 1 and idx > allowance) else 0.0
                daily_wage = float(info.get('daily_wage') or 0.0)
                hourly_rate = daily_wage / company_working_hours if daily_wage and company_working_hours > 0 else 0
                base_wage_for_day = round((mins / 60.0) * hourly_rate, 2)
                ws.append([pid, info.get('name'), d.isoformat(), round(mins/60.0, 2), lm, deduct, round(base_wage_for_day - deduct, 2)])

        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        return send_file(out, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"payroll_daily_{start_date}_{end_date}.xlsx")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@attendance_reports_bp.route("/reports/payroll/import", methods=["POST"])
@require_auth()
def import_payroll_adjustments():
    vendor_id = g.vendor_id
    if 'file' not in request.files:
        return jsonify({"error":"CSV file required"}), 400
    f = request.files['file']
    try:
        content = f.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        conn = get_db_connection()
        c = conn.cursor()
        updated = 0
        for row in reader:
            pid = row.get('person_id')
            if not pid: continue
            vals = {}
            try:
                if row.get('late_allowance_days'): vals['late_allowance_days'] = int(row['late_allowance_days'])
                if row.get('late_deduction_amount'): vals['late_deduction_amount'] = float(row['late_deduction_amount'])
            except: pass
            if vals:
                _run(c, "UPDATE faces SET late_allowance_days = ?, late_deduction_amount = ? WHERE vendor_id = ? AND id = ?", (vals.get('late_allowance_days'), vals.get('late_deduction_amount'), vendor_id, pid))
                updated += 1
        conn.commit(); conn.close()
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
