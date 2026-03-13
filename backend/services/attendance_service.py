import json
from datetime import datetime, date, timedelta
from utils import parse_db_datetime

def calculate_daily_hours(records, timetable=None, date_str=None, attendance_type='total_time'):
    """
    Calculate work hours from a list of attendance records for a single user.
    Records must be sorted by timestamp ASC.
    timetable: List of activity objects (from company live_timetable) to determine payability of gaps.
    date_str: Optional date string to enable real-time calculation for active sessions.
    attendance_type: 'total_time' (sum intervals) or 'first_last' (earliest IN to latest OUT).
    """
    total_seconds = 0
    sessions = []
    
    # Sort just in case
    sorted_records = sorted(records, key=lambda x: x['timestamp'])

    if attendance_type == 'first_last':
        first_in = None
        last_out = None
        
        for record in sorted_records:
            ts = parse_db_datetime(record['timestamp'])
            if not ts: continue
            
            if record['status'] == 'CHECK_IN':
                if first_in is None:
                    first_in = ts
            elif record['status'] == 'CHECK_OUT':
                last_out = ts
        
        # Handle active session if it's today
        effective_last_out = last_out
        is_active = False
        if first_in:
            last_record = sorted_records[-1]
            if last_record['status'] == 'CHECK_IN':
                # If there's an IN without a LATER OUT, it's active
                # Check if it was today
                now_dt = datetime.now()
                effective_last_out = now_dt
                is_active = True
        
        if first_in and effective_last_out:
            duration = (effective_last_out - first_in).total_seconds()
            if duration > 0:
                total_seconds = duration
                sessions.append({
                    "type": "Work (First-Last)" if not is_active else "Work (Active)",
                    "activity": "Work",
                    "is_payable": True,
                    "start_ts": first_in.isoformat(),
                    "end_ts": effective_last_out.isoformat(),
                    "start": first_in.strftime('%H:%M'),
                    "end": effective_last_out.strftime('%H:%M'),
                    "duration_mins": round(duration / 60)
                })
        
        # Calculate string format (e.g. "2h 30m")
        h = int(total_seconds // 3600)
        m = int((total_seconds % 3600) // 60)
        total_hours_str = f"{h}h {m}m"

        return {
            "total_hours": round(total_seconds / 3600, 2),
            "total_hours_str": total_hours_str,
            "sessions": sessions,
            "is_active": is_active,
            "last_checkin": first_in.strftime('%H:%M') if first_in else None
        }

    # Default 'total_time' logic
    current_checkin = None
    current_checkin_activity = None # Track activity started at Check-In
    last_checkout_activity = None # Track activity of last checkout to determine gap payability
    
    for record in sorted_records:
        status = record['status']
        activity_name = record.get('activity', 'Work')
        
        # Robust parsing (handle PG datetime objects vs SQLite strings)
        ts = parse_db_datetime(record['timestamp'])
        if not ts:
            continue # Skip invalid

        if status == 'CHECK_IN':
            if current_checkin is None:
                current_checkin = ts
                current_checkin_activity = activity_name # Store activity from Check-In
        elif status == 'CHECK_OUT':
            if current_checkin:
                duration = (ts - current_checkin).total_seconds()
                if duration < 0: duration = 0

                session_activity = current_checkin_activity if current_checkin_activity else activity_name
                
                is_session_payable = False
                session_activity_lower = session_activity.lower().strip() if session_activity else ""
                
                if timetable:
                    found_act = None
                    for act in timetable:
                        act_name = act.get('name', '').lower().strip()
                        if act_name == session_activity_lower:
                            found_act = act
                            break
                    if found_act:
                        act_type = found_act.get('type', 'Work')
                        is_session_payable = found_act.get('is_payable', act_type == 'Work')
                    else:
                        is_session_payable = (session_activity_lower == 'work' or not session_activity_lower)
                else:
                    is_session_payable = (session_activity_lower == 'work' or not session_activity_lower)

                if is_session_payable:
                    total_seconds += duration
                    
                sessions.append({
                    "type": "Work",
                    "activity": session_activity,
                    "is_payable": is_session_payable,
                    "start_ts": current_checkin.isoformat(),
                    "end_ts": ts.isoformat(),
                    "start": current_checkin.strftime('%H:%M'),
                    "end": ts.strftime('%H:%M'),
                    "duration_mins": round(duration / 60)
                })
                current_checkin = None
                current_checkin_activity = None
                last_checkout_activity = activity_name

    is_active = current_checkin is not None
    
    # Real-time Calculation: If active and today, add duration from last checkin to NOW
    if is_active and date_str:
        try:
            now_dt = datetime.now()
            duration = (now_dt - current_checkin).total_seconds()
            if duration < 0: duration = 0
            
            # Check payability of current active session
            last_in_record = None
            for r in reversed(sorted_records):
                if r['status'] == 'CHECK_IN':
                    last_in_record = r
                    break
            
            active_activity_name = last_in_record.get('activity', 'Work') if last_in_record else "Unknown"
            is_active_payable = False
            found_act = None
            if timetable:
                 for act in timetable:
                     if act.get('name') == active_activity_name:
                         found_act = act
                         break
                 if found_act:
                     act_type = found_act.get('type', 'Work')
                     is_active_payable = found_act.get('is_payable', act_type == 'Work')
            
            if is_active_payable:
                total_seconds += duration
            
            sessions.append({
                "type": "Work (Active)",
                "activity": active_activity_name,
                "is_payable": is_active_payable,
                "start_ts": current_checkin.isoformat(),
                "end_ts": now_dt.isoformat(),
                "start": current_checkin.strftime('%H:%M'),
                "end": now_dt.strftime('%H:%M'),
                "duration_mins": round(duration / 60)
            })
        except Exception:
            pass

    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    total_hours_str = f"{h}h {m}m"

    return {
        "total_hours": round(total_seconds / 3600, 2),
        "total_hours_str": total_hours_str,
        "sessions": sessions,
        "is_active": is_active,
        "last_checkin": current_checkin.strftime('%H:%M') if current_checkin else None
    }

def calculate_expected_hours(day_activities):
    """
    Helper to calculate total expected work hours from a list of activities.
    Handles overnight shifts correctly.
    """
    expected_hours = 0
    for act in day_activities:
        # Check is_payable, default to True if Work, False otherwise
        is_payable = act.get('is_payable', act.get('type') == 'Work')
        
        if is_payable:
            try:
                s = datetime.strptime(act['start_time'], '%H:%M')
                e = datetime.strptime(act['end_time'], '%H:%M')
                
                # Handle overnight shifts (end < start)
                if e < s:
                    e += timedelta(days=1)
                    
                duration = (e - s).total_seconds() / 3600
                expected_hours += duration
            except Exception:
                pass
    return expected_hours

def calculate_arrival_status(expected_start, sessions, day_activities=None):
    """
    Determines if the user arrived late based on their first 'Work' session.
    """
    arrival_status = "On Time"
    if not expected_start or not sessions:
        return arrival_status

    # Find the first 'Work' or relevant session
    first_checkin = None
    for s in sessions:
        s_type = s.get('type', '')
        if s_type == 'Work' or 'Active' in s_type:
             # Prefer 'Work' but 'Active' works if it's the first one
             first_checkin = s['start']
             break
    
    if not first_checkin:
        # Fallback to first session if no Work session found yet
        first_checkin = sessions[0]['start']

    if first_checkin:
        # Get tolerance from the first scheduled activity
        tolerance_mins = 0 # Default Strict
        if day_activities:
             # Check rules for grace_period ONLY (Strict User Request)
             first_act = day_activities[0]
             rules = first_act.get('rules', {}) or {}
             
             # Handle grace_period
             gp = rules.get('grace_period')
             if gp is not None:
                 try:
                     # Robust parsing for grace period (handle "15 min", "15", etc.)
                     if isinstance(gp, str):
                         import re
                         digits = re.findall(r'\d+', gp)
                         if digits:
                             tolerance_mins = int(digits[0])
                         else:
                             tolerance_mins = 0
                     else:
                         tolerance_mins = int(gp)
                 except:
                     tolerance_mins = 0
             else:
                 # No grace period defined -> 0 tolerance
                 tolerance_mins = 0

        try:
            exp_dt = datetime.strptime(expected_start, '%H:%M')
            act_dt = datetime.strptime(first_checkin, '%H:%M')
            
            # Handle midnight crossing (e.g. Expected 23:00, Actual 00:10 next day)
            if act_dt < exp_dt and (exp_dt.hour - act_dt.hour) > 12:
                act_dt += timedelta(days=1)
            
            # Handle reverse midnight crossing (Expected 00:10, Actual 23:50 prev day)
            # Only apply if Expected Start is early morning (e.g. < 06:00) to avoid false positives for very late Day Shifts
            if exp_dt < act_dt and (act_dt.hour - exp_dt.hour) > 12:
                 if exp_dt.hour < 6:
                     exp_dt += timedelta(days=1)

            diff_seconds = (act_dt - exp_dt).total_seconds()
            if diff_seconds > (tolerance_mins * 60):
                arrival_status = "Late"
        except Exception:
            pass

    return arrival_status