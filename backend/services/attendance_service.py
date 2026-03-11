import json
from datetime import datetime, date, timedelta
from utils import parse_db_datetime

def calculate_daily_hours(records, timetable=None, date_str=None):
    """
    Calculate work hours from a list of attendance records for a single user.
    Records must be sorted by timestamp ASC.
    timetable: List of activity objects (from company live_timetable) to determine payability of gaps.
    date_str: Optional date string to enable real-time calculation for active sessions.
    """
    total_seconds = 0
    current_checkin = None
    current_checkin_activity = None # Track activity started at Check-In
    last_checkout_activity = None # Track activity of last checkout to determine gap payability
    sessions = []
    
    # Sort just in case
    sorted_records = sorted(records, key=lambda x: x['timestamp'])

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
                
                # Check if the GAP before this Check-In is payable
                # Logic: If we had a previous session that ended (last_checkout_activity), 
                # we check if THAT activity was payable.
                # Usually, Gaps are Breaks. If Break is Payable, we add the gap time.
                # However, calculate_daily_hours iterates linearly.
                # We need to look at the gap between `sessions[-1]['end_ts']` and `current_checkin`.
                
                if sessions:
                    last_session = sessions[-1]
                    gap_seconds = (ts - last_session['end_ts']).total_seconds()
                    
                    if gap_seconds > 0 and timetable:
                        # Find the activity definition for the gap
                        # We use the activity name from the PREVIOUS CHECK_OUT record (stored in last_checkout_activity)
                        # If last_checkout_activity is None, we can't determine.
                        
                        is_gap_payable = False
                        if last_checkout_activity:
                             # Find activity in timetable (Case Insensitive)
                             last_act_lower = last_checkout_activity.lower().strip()
                             for act in timetable:
                                if act.get('name', '').lower().strip() == last_act_lower:
                                    # Default is_payable to True for Work, False for others if not specified?
                                    # User said: "if it is off, then the activity is not payable".
                                    # In our JSON, we defaulted is_payable to True in UI, but existing data might miss it.
                                    # Let's assume default True for 'Work' type, False for others if missing.
                                    act_type = act.get('type', 'Work')
                                    
                                    # STRICT PAYROLL RULE: 
                                    # Gaps are NEVER payable automatically. 
                                    # User Instruction: "only those tiem when the emplyee had check in and check out that time needs to be saved"
                                    # Users must Check-In to a "Paid Break" activity to get paid for it.
                                    # Checking Out stops the wage counter immediately.
                                    is_gap_payable = False 
                                    
                                    # Legacy Logic Disabled:
                                    # is_gap_payable = act.get('is_payable', False)
                                    
                                    # if is_gap_payable:
                                    #    ... (Logic removed)
                                    pass
                                    break
                        
                        if is_gap_payable:
                             # This block is now effectively unreachable or always False
                             pass


        elif status == 'CHECK_OUT':
            if current_checkin:
                duration = (ts - current_checkin).total_seconds()
                
                # STRICT FIX: Prevent Negative Duration
                # If Check-Out is before Check-In (e.g. Timezone mismatch or bad data), clamp to 0.
                if duration < 0:
                    duration = 0

                # Determine Session Activity: Use the one from Check-In, fallback to current record if missing
                session_activity = current_checkin_activity if current_checkin_activity else activity_name
                
                # Check if this session's activity is PAYABLE
                # User Requirement: "payable hours calculated only when we register an activity with shift"
                # Strict Logic: Rely entirely on the timetable configuration.
                is_session_payable = False
                
                # Normalize for matching
                session_activity_lower = session_activity.lower().strip() if session_activity else ""
                
                if timetable:
                    found_act = None
                    for act in timetable:
                        act_name = act.get('name', '').lower().strip()
                        if act_name == session_activity_lower:
                            found_act = act
                            break
                    
                    if found_act:
                        # STRICT: Use the is_payable flag from the DB. 
                        # If missing, default to False (safe).
                        is_session_payable = found_act.get('is_payable', False)
                    else:
                        # Activity not found in timetable
                        # Strict Fallback: If not defined by admin, it is NOT payable.
                        is_session_payable = False
                else:
                    # No timetable -> No payable hours (Strict)
                    is_session_payable = False

                if is_session_payable:
                    total_seconds += duration
                else:
                    pass
                    
                sessions.append({
                    "type": "Work", # Standard session
                    "activity": session_activity,
                    "is_payable": is_session_payable,
                    "start_ts": current_checkin, # Correct start
                    "end_ts": ts,
                    "start": current_checkin.strftime('%H:%M'),
                    "end": ts.strftime('%H:%M'),
                    "duration_mins": round(duration / 60)
                })
                current_checkin = None
                current_checkin_activity = None
                last_checkout_activity = activity_name # Use Check-Out reason for gap logic (e.g. Lunch/TeaBreak)
    
    # --- Deduct Unpaid Overlaps (REMOVED based on user request for strict Check-In/Out calculation) ---
    # User instruction: "wage counting is very important based on payble check in and check out times gap only"
    # This implies no auto-deductions for scheduled breaks if the user didn't actually check out.
    # if timetable and records and total_seconds > 0:
    #     try:
    #         # ... (Logic removed to prevent auto-deduction)
    #         pass
    #     except Exception as e:
    #         print(f"Error in unpaid deduction logic: {e}")

    # Clean up sessions for output
    final_sessions = []
    for s in sessions:
        # Keep timestamps as ISO strings for reporting
        if "start_ts" in s and isinstance(s["start_ts"], datetime):
             s["start_ts"] = s["start_ts"].isoformat()
        if "end_ts" in s and isinstance(s["end_ts"], datetime):
             s["end_ts"] = s["end_ts"].isoformat()
        final_sessions.append(s)

    is_active = current_checkin is not None
    
    # Real-time Calculation: If active and today, add duration from last checkin to NOW
    if is_active and date_str:
        try:
            today_str = datetime.now().strftime('%Y-%m-%d')
            # Allow active calculation if it's today OR if we are processing a continuous stream
            if True: # Always check active if date_str is present (it implies "Live" context)
                now_dt = datetime.now()
                duration = (now_dt - current_checkin).total_seconds()
                if duration < 0:
                    duration = 0
                
                # Check payability of current active session
                # We need the activity name for the current session.
                # Assuming the LAST Check-In established the activity.
                # Find the last Check-In record
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
                
                # Add Active Session to FINAL sessions directly
                final_sessions.append({
                    "type": "Work (Active)",
                    "activity": active_activity_name,
                    "is_payable": is_active_payable,
                    "start_ts": current_checkin.isoformat(),
                    "end_ts": now_dt.isoformat(),
                    "start": current_checkin.strftime('%H:%M'),
                    "end": now_dt.strftime('%H:%M'),
                    "duration_mins": round(duration / 60)
                })
        except Exception as e:
            pass # print(f"Real-time calc error: {e}")

    # Calculate string format (e.g. "2h 30m")
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    total_hours_str = f"{h}h {m}m"

    return {
        "total_hours": round(total_seconds / 3600, 2),
        "total_hours_str": total_hours_str,
        "sessions": final_sessions,
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
            except Exception as e:
                pass # print(f"Error calculating expected hours for activity {act}: {e}")
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
        except Exception as e:
            pass # print(f"Error calc arrival status: {e}")
            # Fallback: simple comparison if complex logic fails
            try:
                 # Simple string compare if format allows? No, safer to leave as On Time or retry simple
                 pass
            except:
                 pass

    return arrival_status