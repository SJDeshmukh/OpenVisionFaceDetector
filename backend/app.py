import sqlite3
import base64
import os
from flask import Flask, Blueprint, request, jsonify, render_template
from flask_cors import CORS
from services.llm_service import generate_greeting
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Ensure database is always accessed from the same location (backend directory)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faces.db')

# --- Web Dashboard ---
@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "Face Detection Backend API",
        "version": "1.0.0",
        "message": "Please use the Frontend Application to access the dashboard."
    })

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS faces
                 (name TEXT PRIMARY KEY, 
                  templates TEXT, 
                  face_image TEXT,
                  department TEXT,
                  designation TEXT,
                  phone TEXT,
                  shift TEXT)''')
    
    # New Table for Attendance
    # Check if captured_image column exists, if not, we might need to recreate or alter
    # For dev simplicity, we'll just ensure the table exists with the new schema if it doesn't.
    # If it exists from previous runs without the column, this CREATE IF NOT EXISTS won't add it.
    # So let's handle migration loosely by checking columns.
    
    c.execute('''CREATE TABLE IF NOT EXISTS attendance
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, 
                  timestamp DATETIME, 
                  status TEXT,
                  captured_image TEXT,
                  activity TEXT)''') 

    # Table for System Users (Admin/Standard)
    c.execute('''CREATE TABLE IF NOT EXISTS system_users
                 (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    
    # Check for captured_image column in attendance table and add if missing
    c.execute("PRAGMA table_info(attendance)")
    attendance_columns = [info[1] for info in c.fetchall()]
    if 'captured_image' not in attendance_columns:
        print("Migrating: Adding captured_image column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN captured_image TEXT")

    # Check for extra columns in faces table (department, designation, phone)
    c.execute("PRAGMA table_info(faces)")
    faces_columns = [info[1] for info in c.fetchall()]
    
    if 'department' not in faces_columns:
        print("Migrating: Adding department column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN department TEXT")
        
    if 'designation' not in faces_columns:
        print("Migrating: Adding designation column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN designation TEXT")
        
    if 'phone' not in faces_columns:
        print("Migrating: Adding phone column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN phone TEXT")

    if 'shift' not in faces_columns:
        print("Migrating: Adding shift column to faces table")
        c.execute("ALTER TABLE faces ADD COLUMN shift TEXT")

    # Check for activity column in attendance table and add if missing
    c.execute("PRAGMA table_info(attendance)")
    attendance_columns = [info[1] for info in c.fetchall()]
    if 'activity' not in attendance_columns:
        print("Migrating: Adding activity column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN activity TEXT")

    if 'is_late' not in attendance_columns:
        print("Migrating: Adding is_late column to attendance table")
        c.execute("ALTER TABLE attendance ADD COLUMN is_late INTEGER DEFAULT 0")

    # Create default admin if not exists
    c.execute("SELECT * FROM system_users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)", 
                  ('admin', 'admin123', 'admin'))

    # Create default kiosk user if not exists
    c.execute("SELECT * FROM system_users WHERE username = 'kiosk'")
    if not c.fetchone():
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)", 
                  ('kiosk', 'kiosk123', 'user'))

    # --- New Table for Companies & Timetables ---
    c.execute('''CREATE TABLE IF NOT EXISTS companies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT UNIQUE, 
                  shifts TEXT,
                  draft_timetable TEXT, 
                  live_timetable TEXT,
                  last_modified_by TEXT,
                  last_modified_at DATETIME,
                  published_by TEXT,
                  published_at DATETIME)''')

    # Create default company if not exists
    c.execute("SELECT * FROM companies WHERE name = 'Open Vision'")
    if not c.fetchone():
        # Initialize with empty JSON array for timetables and shifts
        c.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable) VALUES (?, ?, ?, ?)", 
                  ('Open Vision', '[]', '[]', '[]'))
    
    # Check for shifts column in companies table and add if missing
    c.execute("PRAGMA table_info(companies)")
    companies_columns = [info[1] for info in c.fetchall()]
    if 'shifts' not in companies_columns:
        print("Migrating: Adding shifts column to companies table")
        c.execute("ALTER TABLE companies ADD COLUMN shifts TEXT DEFAULT '[]'")
    
    # --- New Table for System Settings ---
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
                 
    # Default Settings
    default_settings = {
        "threshold": "0.6",
        "cooldown": "30",
        "work_start_time": "09:00",
        "late_threshold": "09:30",
        "late_grace_period": "15",
        "activity_tolerance": "30",
        "auto_checkout": "false",
        "voice_greeting": "true",
        "admin_alerts": "false"
    }
    
    for key, val in default_settings.items():
        c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (key, val))

    conn.commit()
    conn.close()

init_db()

greeting_bp = Blueprint("greeting", __name__, url_prefix="/api")

# --- Company & Timetable Endpoints ---

@greeting_bp.route("/companies", methods=["GET"])
def get_companies():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, name FROM companies")
    companies = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({"companies": companies})

@greeting_bp.route("/companies", methods=["POST"])
def create_company():
    data = request.json
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name is required"}), 400
        
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable) VALUES (?, ?, ?, ?)", 
                  (name, '[]', '[]', '[]'))
        conn.commit()
        company_id = c.lastrowid
        conn.close()
        return jsonify({"success": True, "id": company_id, "name": name})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Company already exists"}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@greeting_bp.route("/companies/<int:company_id>/shifts", methods=["PUT"])
def update_shifts(company_id):
    data = request.json
    shifts = data.get("shifts") # Expecting JSON string or object
    
    if shifts is None:
        return jsonify({"error": "shifts is required"}), 400

    import json
    if isinstance(shifts, list):
        shifts = json.dumps(shifts)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE companies SET shifts = ? WHERE id = ?", (shifts, company_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@greeting_bp.route("/companies/<int:company_id>", methods=["GET"])
def get_company_details(company_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        data = dict(row)
        import json
        for key in ['shifts', 'draft_timetable', 'live_timetable']:
            if data.get(key):
                try:
                    data[key] = json.loads(data[key])
                except:
                    data[key] = []
        return jsonify(data)
    else:
        return jsonify({"error": "Company not found"}), 404

@greeting_bp.route("/companies/<int:company_id>/draft", methods=["PUT"])
def update_draft_timetable(company_id):
    data = request.json
    draft_timetable = data.get("draft_timetable") # Expecting JSON string or object
    modified_by = data.get("modified_by", "unknown")
    
    if draft_timetable is None:
        return jsonify({"error": "draft_timetable is required"}), 400

    import json
    if isinstance(draft_timetable, list):
        draft_timetable = json.dumps(draft_timetable)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""UPDATE companies 
                 SET draft_timetable = ?, last_modified_by = ?, last_modified_at = ? 
                 WHERE id = ?""", 
              (draft_timetable, modified_by, datetime.now(), company_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@greeting_bp.route("/companies/<int:company_id>/publish", methods=["POST"])
def publish_timetable(company_id):
    data = request.json
    published_by = data.get("published_by", "unknown")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Copy draft to live
    c.execute("""UPDATE companies 
                 SET live_timetable = draft_timetable, published_by = ?, published_at = ? 
                 WHERE id = ?""", 
              (published_by, datetime.now(), company_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@greeting_bp.route("/reports/analytics", methods=["GET"])
def get_analytics():
    import json
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Fetch Timetable
    c.execute("SELECT live_timetable FROM companies WHERE id = 1")
    company_row = c.fetchone()
    timetable = []
    if company_row and company_row['live_timetable']:
        try:
            timetable = json.loads(company_row['live_timetable'])
        except:
            timetable = []

    # Fetch Late Grace Period
    c.execute("SELECT value FROM system_settings WHERE key='late_grace_period'")
    row = c.fetchone()
    grace_period = int(row['value']) if row else 15

    def get_late_users(target_date_str):
        # 1. Try to use is_late column (New Logic)
        try:
            c.execute("SELECT COUNT(DISTINCT name) as count FROM attendance WHERE date(timestamp) = ? AND is_late = 1", (target_date_str,))
            db_late_count = c.fetchone()['count']
            if db_late_count > 0:
                # If we found explicit late records, return the list of names (need to fetch names)
                c.execute("SELECT DISTINCT name FROM attendance WHERE date(timestamp) = ? AND is_late = 1", (target_date_str,))
                return [r['name'] for r in c.fetchall()]
        except Exception as e:
            print(f"Error checking is_late column: {e}")

        # 2. Fallback to calculation (Legacy Logic or if count is 0)
        # Note: If count is 0, it might be that nobody is late, or it's old data.
        # Running calculation is safe (should return 0 if nobody is late).
        
        day_name = datetime.strptime(target_date_str, '%Y-%m-%d').strftime('%a')
        
        # Fetch all Check-Ins for the date with User Shift (First Check-in per user)
        c.execute("""
            SELECT a.name, MIN(a.timestamp) as timestamp, f.shift
            FROM attendance a
            LEFT JOIN faces f ON a.name = f.name
            WHERE date(a.timestamp) = ? AND a.status = 'CHECK_IN'
            GROUP BY a.name
        """, (target_date_str,))
        
        records = c.fetchall()
        late_users = []
        
        for row in records:
            name = row['name']
            ts_str = row['timestamp']
            shift_name = row['shift'] if 'shift' in row.keys() else None
            
            # Filter timetable for this day
            day_acts = [t for t in timetable if day_name in t.get('days', []) and t.get('type', '').lower() == 'work']
            
            # Match shift
            matched_act = None
            if shift_name:
                for act in day_acts:
                    if act.get('name') == shift_name:
                        matched_act = act
                        break
            
            # If no shift matched or no shift assigned, pick first work act (Fallback)
            if not matched_act and day_acts:
                matched_act = day_acts[0]
            
            if matched_act:
                work_start = matched_act.get('start_time', "09:00")
                try:
                    h, m = map(int, work_start.split(':'))
                    threshold_mins = h * 60 + m + grace_period
                    
                    # Parse timestamp
                    if '.' in ts_str:
                         ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
                    else:
                         ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    
                    checkin_mins = ts.hour * 60 + ts.minute
                    
                    if checkin_mins > threshold_mins:
                        late_users.append(name)
                except:
                    pass
        return late_users

    # 1. Overall Stats (Today)
    today_date = datetime.now()
    today_str = today_date.strftime('%Y-%m-%d')
    
    late_users_today = get_late_users(today_str)
    late_today = len(late_users_today)

    c.execute("SELECT COUNT(DISTINCT name) as count FROM attendance WHERE date(timestamp) = ?", (today_str,))
    present_today = c.fetchone()['count']
    
    c.execute("SELECT COUNT(*) as count FROM faces")
    total_users = c.fetchone()['count']
    
    absent_today = max(0, total_users - present_today)
    on_time_today = max(0, present_today - late_today)

    # 2. Daily Attendance Trend (Last 7 Days)
    dates = [(today_date - timedelta(days=i)) for i in range(6, -1, -1)]
    attendance_trend = []
    
    for d_obj in dates:
        d_str = d_obj.strftime('%Y-%m-%d')
        
        c.execute("SELECT COUNT(DISTINCT name) as count FROM attendance WHERE date(timestamp) = ?", (d_str,))
        present = c.fetchone()['count']
        absent = max(0, total_users - present)
        
        late = len(get_late_users(d_str))

        attendance_trend.append({
            "name": d_obj.strftime('%a'),
            "date": d_str,
            "present": present,
            "absent": absent,
            "late": late,
            "total": total_users
        })

    # 3. Department Stats (Late Arrivals Today)
    dept_data = []
    if late_users_today:
        placeholders = ','.join(['?'] * len(late_users_today))
        c.execute(f"""
            SELECT department, COUNT(*) as count
            FROM faces 
            WHERE name IN ({placeholders})
            AND department IS NOT NULL AND department != ''
            GROUP BY department
        """, late_users_today)
        dept_rows = c.fetchall()
        dept_data = [{"name": row['department'], "late": row['count']} for row in dept_rows]

    conn.close()

    return jsonify({
        "pie_data": [
            {"name": "On Time", "value": on_time_today},
            {"name": "Late", "value": late_today},
            {"name": "Absent", "value": absent_today}
        ],
        "bar_data": attendance_trend,
        "dept_data": dept_data,
        "summary": {
            "total_users": total_users,
            "present_today": present_today,
            "late_today": late_today,
            "absent_today": absent_today
        }
    })

@greeting_bp.route("/reports/export", methods=["GET"])
def export_report():
    import csv
    import io
    from flask import Response
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Filters
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    department = request.args.get('department')
    designation = request.args.get('designation')
    
    query = """
        SELECT a.name, a.timestamp, a.status, f.department, f.designation
        FROM attendance a
        LEFT JOIN faces f ON a.name = f.name
        WHERE date(a.timestamp) BETWEEN ? AND ?
    """
    params = [start_date, end_date]
    
    if department:
        query += " AND f.department = ?"
        params.append(department)
        
    if designation:
        query += " AND f.designation = ?"
        params.append(designation)
        
    query += " ORDER BY a.timestamp DESC"
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Date', 'Time', 'Status', 'Department', 'Designation'])
    
    for row in rows:
        ts = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
        date_str = ts.strftime('%Y-%m-%d')
        time_str = ts.strftime('%I:%M %p')
        
        status_str = row['status']
        if row['status'] == 'CHECK_IN' and 'is_late' in row.keys() and row['is_late'] == 1:
            status_str = 'Late'
            
        writer.writerow([
            row['name'], 
            date_str, 
            time_str, 
            status_str, 
            row['department'] or 'N/A', 
            row['designation'] or 'N/A'
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=attendance_report_{start_date}_to_{end_date}.csv"}
    )

@greeting_bp.route("/reports/filters", methods=["GET"])
def get_report_filters():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get unique departments and designations
    c.execute("SELECT DISTINCT department FROM faces WHERE department IS NOT NULL AND department != ''")
    departments = [row['department'] for row in c.fetchall()]
    
    c.execute("SELECT DISTINCT designation FROM faces WHERE designation IS NOT NULL AND designation != ''")
    designations = [row['designation'] for row in c.fetchall()]
    
    conn.close()
    
    return jsonify({
        "departments": departments,
        "designations": designations
    })

@greeting_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "message": "Server is running"})

# --- Auth Endpoints ---
@greeting_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    print(f"Login Attempt: User={username}, Pass={password}") # DEBUG LOG

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM system_users WHERE username = ? AND password = ?", (username, password))
    user = c.fetchone()
    conn.close()

    if user:
        print(f"Login Success: Role={user['role']}") # DEBUG LOG
        return jsonify({
            "status": "success",
            "role": user["role"],
            "username": user["username"]
        })
    else:
        print("Login Failed: Invalid credentials") # DEBUG LOG
        return jsonify({"error": "Invalid credentials"}), 401

@greeting_bp.route("/auth/register", methods=["POST"])
def register_user():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    role = data.get("role", "user") # admin or user

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO system_users (username, password, role) VALUES (?, ?, ?)", 
                  (username, password, role))
        conn.commit()
        return jsonify({"status": "success", "message": "User created"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# --- System Settings Endpoints ---

@greeting_bp.route("/settings", methods=["GET"])
def get_settings():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT key, value FROM system_settings")
    rows = c.fetchall()
    conn.close()
    
    settings = {row['key']: row['value'] for row in rows}
    return jsonify(settings)

@greeting_bp.route("/settings", methods=["POST"])
def update_settings():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        for key, value in data.items():
            # Ensure value is string
            val_str = str(value) if value is not None else ""
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, val_str))
        conn.commit()
        return jsonify({"status": "success", "message": "Settings updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# --- User Management Endpoints ---
@greeting_bp.route("/users", methods=["GET"])
def get_users():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT username, role FROM system_users")
    rows = c.fetchall()
    conn.close()

    users = [{"username": row["username"], "role": row["role"]} for row in rows]
    return jsonify({"users": users})

@greeting_bp.route("/users", methods=["POST"])
def create_user():
    return register_user() # Reuse register logic

@greeting_bp.route("/users/<username>", methods=["PUT"])
def update_user(username):
    data = request.json
    password = data.get("password")
    role = data.get("role")

    if not password and not role:
        return jsonify({"error": "Nothing to update"}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        if password and role:
            c.execute("UPDATE system_users SET password = ?, role = ? WHERE username = ?", (password, role, username))
        elif password:
            c.execute("UPDATE system_users SET password = ? WHERE username = ?", (password, username))
        elif role:
            c.execute("UPDATE system_users SET role = ? WHERE username = ?", (role, username))
        
        conn.commit()
        if c.rowcount > 0:
            return jsonify({"status": "success", "message": f"User {username} updated"})
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/users/<username>", methods=["DELETE"])
def delete_user(username):
    if username == "admin": # Prevent deleting the main admin
        return jsonify({"error": "Cannot delete default admin"}), 403

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("DELETE FROM system_users WHERE username = ?", (username,))
        conn.commit()
        if c.rowcount > 0:
            return jsonify({"status": "success", "message": f"User {username} deleted"})
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# --- Sync Endpoints ---

@greeting_bp.route("/sync/upload", methods=["POST"])
def upload_face():
    data = request.json
    name = data.get("name")
    templates = data.get("templates", "") # Base64 string, optional
    face_image = data.get("face_image") # Base64 string
    phone = data.get("phone", "")
    department = data.get("department", "")
    designation = data.get("designation", "")
    shift = data.get("shift", "")

    if not name:
        return jsonify({"error": "Missing name"}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO faces (name, templates, face_image, phone, department, designation, shift) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (name, templates, face_image, phone, department, designation, shift))
        conn.commit()
        return jsonify({"status": "success", "message": f"Face for {name} saved."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@greeting_bp.route("/sync/download", methods=["GET"])
def download_faces():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM faces")
    rows = c.fetchall()
    conn.close()

    faces = []
    for row in rows:
        faces.append({
            "name": row["name"],
            "templates": row["templates"],
            "face_image": row["face_image"],
            "phone": row["phone"] if "phone" in row.keys() else "",
            "department": row["department"] if "department" in row.keys() else "",
            "designation": row["designation"] if "designation" in row.keys() else "",
            "shift": row["shift"] if "shift" in row.keys() else ""
        })
    
    return jsonify({"faces": faces})

@greeting_bp.route("/sync/delete/<name>", methods=["DELETE"])
def delete_face(name):
    if not name:
        return jsonify({"error": "Missing name"}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("DELETE FROM faces WHERE name = ?", (name,))
        conn.commit()
        if c.rowcount > 0:
            return jsonify({"status": "success", "message": f"Face for {name} deleted."})
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@greeting_bp.route("/person-event", methods=["POST"])
def person_event():
    data = request.json
    
    # Debug Log
    print(f"Received person-event: detected={data.get('detected')}, recognized={data.get('recognized')}, name={data.get('name')}")

    detected = data.get("detected", False)
    recognized = data.get("recognized", False)
    name = data.get("name")
    person_id = data.get("person_id")
    confidence = data.get("confidence", 0)
    captured_image = data.get("image") # Base64 string of the frame
    is_attendance = data.get("is_attendance", True) # Default to True for backward compatibility

    # Case 1: No person detected
    if not detected:
        return jsonify({"speak": False})

    # Case 2: Person detected but NOT recognized
    if detected and not recognized:
        message = "Hello! You are not recognized. Please register with the admin first."
        return jsonify({
            "speak": True,
            "text": message
        })

    # Case 3: Person detected and recognized
    
    # If this is just an identification check (e.g. from Admin panel), do not record attendance
    if not is_attendance:
        print(f"Admin Identification Check: {name}")
        return jsonify({
            "speak": True,
            "text": f"Identified: {name}"
        })

    # --- Check-in / Check-out Logic ---
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Identify Activity Context FIRST to determine duplication rules
    activity_name = "Work" # Default
    activity_type = "Work"
    best_match = None
    
    try:
        # Fetch Timetable and Shifts
        c.execute("SELECT live_timetable, shifts FROM companies WHERE id = 1")
        company_row = c.fetchone()
        
        # Fetch User Shift
        c.execute("SELECT shift FROM faces WHERE name = ?", (name,))
        face_row = c.fetchone()
        user_shift_name = face_row['shift'] if face_row and 'shift' in face_row.keys() else None

        if company_row and company_row['live_timetable']:
            import json
            timetable = json.loads(company_row['live_timetable'])
            shifts_data = json.loads(company_row['shifts']) if company_row['shifts'] else []
            
            # Resolve User Shift ID
            user_shift_id = None
            if user_shift_name:
                for s in shifts_data:
                    if s.get('name') == user_shift_name:
                        user_shift_id = s.get('id')
                        break
            
            now = datetime.now()
            current_hm = now.strftime('%H:%M')
            day_name = now.strftime('%a')
            
            def to_mins(hm):
                try:
                    h, m = map(int, hm.split(':'))
                    return h * 60 + m
                except:
                    return 0

            curr_mins = to_mins(current_hm)
            today_acts = [a for a in timetable if day_name in a.get('days', [])]
            
            matching_acts = []
            
            # Fetch Settings
            c.execute("SELECT key, value FROM system_settings WHERE key IN ('activity_tolerance', 'late_grace_period')")
            settings = {row['key']: row['value'] for row in c.fetchall()}
            tolerance = int(settings.get('activity_tolerance', 30))
            grace_period = int(settings.get('late_grace_period', 15))
            
            for act in today_acts:
                start_mins = to_mins(act.get('start_time', '00:00'))
                end_mins = to_mins(act.get('end_time', '00:00'))
                
                # Check if current time is within this activity (with buffer)
                if (start_mins - tolerance) <= curr_mins <= (end_mins + tolerance):
                    # Filter by Shift ID if activity has one
                    act_shift_id = act.get('shift_id')
                    # If activity has a shift_id, it MUST match the user's shift_id
                    # If activity has NO shift_id, it is global (matches everyone)
                    if act_shift_id:
                        if user_shift_id and int(act_shift_id) == int(user_shift_id):
                            matching_acts.append(act)
                    else:
                        matching_acts.append(act)
            
            # Prioritize:
            # 1. 'Break' type over 'Work' type (Lunch > Work)
            # 2. Specificity (Shift-specific > Global) - handled by filtering above mostly
            
            best_match = None
            
            # Check for Breaks first
            breaks = [a for a in matching_acts if a.get('type', '').lower() != 'work']
            if breaks:
                best_match = breaks[0] # Pick first break
            elif matching_acts:
                # If only work acts, pick the one matching user shift
                # If we have multiple (e.g. global Work and Shift Work), prefer Shift Work?
                # For now, just pick the first one.
                best_match = matching_acts[0]
            
            if best_match:
                activity_name = best_match.get('name', 'Work')
                activity_type = best_match.get('type', 'Work')

    except Exception as e:
        print(f"Activity Detection Error: {e}")

    # --- Duplication Check ---
    # User Requirement: "if the employee has completed the activity... it should not duplicate again"
    # Logic: For non-Work activities (Breaks), if we have a complete pair (OUT and IN), block further scans.
    
    if activity_type.lower() != 'work':
        today_str = datetime.now().strftime('%Y-%m-%d')
        c.execute("""
            SELECT count(*) as count 
            FROM attendance 
            WHERE name = ? 
            AND date(timestamp) = ? 
            AND activity = ?
        """, (name, today_str, activity_name))
        count = c.fetchone()['count']
        
        # Assuming a complete activity cycle is 2 records (OUT for Lunch, IN from Lunch)
        # Or maybe just check if they are already "IN" from Lunch?
        # If count >= 2, it implies they left and came back.
        if count >= 2:
            print(f"Activity {activity_name} already completed for {name}. Skipping.")
            conn.close()
            return jsonify({
                "speak": True,
                "text": f"You have already completed {activity_name}."
            })

    # Get last status and timestamp
    c.execute("SELECT * FROM attendance WHERE name = ? ORDER BY timestamp DESC LIMIT 1", (name,))
    last_record = c.fetchone()
    
    # --- Cooldown Check ---
    try:
        if last_record:
            last_ts_str = last_record['timestamp']
            # Parse timestamp (handle both with and without microseconds)
            if '.' in last_ts_str:
                last_ts = datetime.strptime(last_ts_str, '%Y-%m-%d %H:%M:%S.%f')
            else:
                last_ts = datetime.strptime(last_ts_str, '%Y-%m-%d %H:%M:%S')
            
            # Get cooldown setting
            c.execute("SELECT value FROM system_settings WHERE key='cooldown'")
            row = c.fetchone()
            cooldown_seconds = int(row['value']) if row else 30
            
            # Calculate time difference
            # Use abs() to handle cases where DB has "future" timestamps due to timezone mixups
            # (e.g. if DB has IST but server checks against UTC)
            delta_seconds = (datetime.now() - last_ts).total_seconds()
            print(f"Cooldown Check: Name={name}, Last={last_ts}, Now={datetime.now()}, Delta={delta_seconds}s, Limit={cooldown_seconds}s")
            
            if 0 <= delta_seconds < cooldown_seconds:
                print(f"Cooldown active for {name}. Skipping.")
                conn.close()
                return jsonify({"speak": False})
            elif delta_seconds < 0:
                 # Last record is in the future.
                 # If it's just a few seconds (clock skew), treat as cooldown.
                 # If it's large (timezone mismatch), we should probably allow it to correct the drift, 
                 # OR block it if we want to enforce strictness. 
                 # Given the issues, let's allow it if it's > 60 seconds in future (assume data error/timezone),
                 # but block if it's within 0 to -60 seconds (likely just double scan with clock skew).
                 if abs(delta_seconds) < 60:
                     print(f"Cooldown active (future skew) for {name}. Skipping.")
                     conn.close()
                     return jsonify({"speak": False})
                 else:
                     print(f"Ignoring future timestamp (timezone mismatch?) for {name}. Allowing entry.")

    except Exception as e:
        print(f"Cooldown Error: {e}" )

    new_status = 'CHECK_IN'
    if last_record and last_record['status'] == 'CHECK_IN':
        new_status = 'CHECK_OUT'
    
    # Calculate Late Status
    is_late = 0
    if new_status == 'CHECK_IN' and best_match:
        try:
            # Ensure grace_period is available
            if 'grace_period' not in locals(): grace_period = 15
            
            # Recalculate curr_mins if needed
            if 'curr_mins' not in locals():
                now_check = datetime.now()
                curr_mins = now_check.hour * 60 + now_check.minute
            
            start_hm = best_match.get('start_time', '09:00')
            h, m = map(int, start_hm.split(':'))
            start_mins = h * 60 + m
            threshold_mins = start_mins + grace_period
            
            if curr_mins > threshold_mins:
                is_late = 1
                print(f"Late Detected: {name} (Time: {curr_mins}, Start: {start_mins}, Grace: {grace_period})")
        except Exception as e:
            print(f"Late Calculation Error: {e}")

    # Insert new record with image
    # Use UTC for storage to ensure consistency
    current_time_utc = datetime.utcnow()
    # But for now, since we use naive datetimes everywhere, let's stick to naive local server time
    # to avoid breaking existing logic that expects naive objects.
    # Ideally, we should migrate to UTC everywhere.
    # Given the user's issue "past attendance", let's make sure we return ISO 8601 strings in API.
    
    current_time = datetime.now()
    try:
        c.execute("INSERT INTO attendance (name, timestamp, status, captured_image, activity, is_late) VALUES (?, ?, ?, ?, ?, ?)", 
                  (name, current_time, new_status, captured_image, activity_name, is_late))
        conn.commit()
        print(f"Attendance Recorded: {name} - {new_status} ({activity_name}) Late={is_late} at {current_time}")
    except Exception as e:
        print(f"Insert Error: {e}")
        conn.close()
        return jsonify({"error": "Database Insert Failed"}), 500
    
    # --- Context Determination Logic (Legacy / UI) ---
    # We already determined activity_name/type above.
    # Now we map it to the UI 'context' strings if needed.
    
    activity_context = None
    if activity_type.lower() != 'work':
        if 'lunch' in activity_name.lower():
            activity_context = 'leaving_for_lunch' if new_status == 'CHECK_OUT' else 'returning_from_lunch'
        elif 'tea' in activity_name.lower():
            activity_context = 'leaving_for_tea' if new_status == 'CHECK_OUT' else 'returning_from_tea'
    else:
        # Work Logic
        if new_status == 'CHECK_IN':
             # Check Late
             # We need start time of this activity
             # We can reuse the best_match from above if we saved it
             pass # Simplified for now, the UI logic below is still valid or can be simplified

    conn.close()

    # Generate Greeting with Context
    greeting = generate_greeting(name, new_status, context=activity_context)
    
    if new_status == 'CHECK_IN':
        display_status = f"Check In: {current_time.strftime('%I:%M %p')}"
        if is_late:
            display_status += " (Late)"
        if activity_name != 'Work':
             display_status += f" ({activity_name})"
    else:
        display_status = f"Check Out: {current_time.strftime('%I:%M %p')}"
        if activity_name != 'Work':
             display_status += f" ({activity_name})"

    return jsonify({
        "speak": True,
        "text": greeting,
        "status": new_status,
        "display_status": display_status
    })

@greeting_bp.route("/attendance", methods=["GET"])
def get_attendance():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Filters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    department = request.args.get('department')
    designation = request.args.get('designation')
    name = request.args.get('name')
    status = request.args.get('status')

    query = """
        SELECT a.*, f.department, f.designation, f.shift
        FROM attendance a
        LEFT JOIN faces f ON a.name = f.name
        WHERE 1=1
    """
    params = []

    if start_date:
        query += " AND date(a.timestamp) >= ?"
        params.append(start_date)
    
    if end_date:
        query += " AND date(a.timestamp) <= ?"
        params.append(end_date)

    if department:
        query += " AND f.department = ?"
        params.append(department)

    if designation:
        query += " AND f.designation = ?"
        params.append(designation)

    if name:
        query += " AND a.name LIKE ?"
        params.append(f"%{name}%")

    if status and status != "All Statuses":
        # Map UI status to DB status if needed, or just use DB status
        # The UI sends 'On Time', 'Late', 'Absent' which are derived statuses, 
        # but the DB stores 'CHECK_IN', 'CHECK_OUT'. 
        # Filtering by 'Late' or 'On Time' is complex in SQL without pre-calculation.
        # For now, let's support basic CHECK_IN/CHECK_OUT if passed, 
        # or if the user meant the derived status, we might need to filter in Python 
        # or do complex SQL. 
        # Given the "filters like report page" request, simpler is better.
        # Let's stick to DB status if it matches, otherwise ignore for now 
        # or implement simple mapping if easy.
        # The UI currently has "On Time", "Late", "Absent". 
        # "Absent" implies no record, so it won't be in logs.
        # "Late" implies CHECK_IN after a time.
        # Let's just filter by name/dept/date for now as primary requirement.
        pass

    query += " ORDER BY a.timestamp DESC"

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    attendance = []
    for row in rows:
        # Check if captured_image column exists in the row (for backward compatibility)
        img = None
        if 'captured_image' in row.keys():
            img = row['captured_image']
            
        attendance.append({
            "id": row["id"],
            "name": row["name"],
            "timestamp": row["timestamp"],
            "status": row["status"],
            "is_late": row["is_late"] if "is_late" in row.keys() else 0,
            "activity": row["activity"] if "activity" in row.keys() else "",
            "captured_image": img,
            "department": row["department"] if "department" in row.keys() else "",
            "designation": row["designation"] if "designation" in row.keys() else "",
            "shift": row["shift"] if "shift" in row.keys() else ""
        })
    
    return jsonify({"attendance": attendance})

def calculate_daily_hours(records):
    """
    Calculate work hours from a list of attendance records for a single user.
    Records must be sorted by timestamp ASC.
    """
    total_seconds = 0
    current_checkin = None
    sessions = []
    
    # Sort just in case
    sorted_records = sorted(records, key=lambda x: x['timestamp'])

    for record in sorted_records:
        status = record['status']
        try:
            ts = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            # Fallback for timestamps without microseconds
            try:
                ts = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S')
            except:
                continue # Skip invalid

        if status == 'CHECK_IN':
            if current_checkin is None:
                current_checkin = ts
        elif status == 'CHECK_OUT':
            if current_checkin:
                duration = (ts - current_checkin).total_seconds()
                total_seconds += duration
                sessions.append({
                    "start_ts": current_checkin,
                    "end_ts": ts,
                    "start": current_checkin.strftime('%H:%M'),
                    "end": ts.strftime('%H:%M'),
                    "duration_mins": round(duration / 60)
                })
                current_checkin = None
    
    # Calculate break time (gaps between sessions)
    total_break_seconds = 0
    if len(sessions) > 1:
        for i in range(len(sessions) - 1):
            gap = (sessions[i+1]['start_ts'] - sessions[i]['end_ts']).total_seconds()
            if gap > 0:
                total_break_seconds += gap

    # Remove ts objects before returning
    for s in sessions:
        del s['start_ts']
        del s['end_ts']

    is_active = current_checkin is not None
    
    return {
        "total_hours": round(total_seconds / 3600, 2),
        "total_break_hours": round(total_break_seconds / 3600, 2),
        "sessions": sessions,
        "is_active": is_active,
        "last_checkin": current_checkin.strftime('%H:%M') if current_checkin else None
    }

# --- Live Camera Stream Endpoints ---

# In-memory storage for the latest frame (single device support for now)
latest_frame = {
    "data": None,
    "timestamp": None,
    "source_ip": None
}

@greeting_bp.route("/stream/upload", methods=["POST"])
def upload_stream_frame():
    try:
        data = request.json
        image_data = data.get("image") # Base64 string
        
        if not image_data:
            return jsonify({"error": "No image data"}), 400
            
        latest_frame["data"] = image_data
        latest_frame["timestamp"] = datetime.now()
        # Capture Real IP (Render uses X-Forwarded-For)
        latest_frame["source_ip"] = request.headers.get('X-Forwarded-For', request.remote_addr)
        
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Stream Upload Error: {e}")
        return jsonify({"error": str(e)}), 500

@greeting_bp.route("/stream/view", methods=["GET"])
def view_stream_frame():
    # Check if frame is stale (older than 10 seconds)
    if latest_frame["timestamp"]:
        delta = datetime.now() - latest_frame["timestamp"]
        if delta.total_seconds() > 10:
            return jsonify({"status": "offline", "image": None})
            
    if latest_frame["data"]:
        return jsonify({
            "status": "online", 
            "image": latest_frame["data"],
            "source_ip": latest_frame.get("source_ip", "Unknown")
        })
    else:
        return jsonify({"status": "offline", "image": None})

@greeting_bp.route("/attendance/summary", methods=["GET"])
def get_attendance_summary():

    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    company_id = request.args.get('company_id', 1) # Default to company ID 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch Timetable
    c.execute("SELECT live_timetable FROM companies WHERE id = ?", (company_id,))
    company_row = c.fetchone()
    timetable = []
    if company_row and company_row['live_timetable']:
        import json
        try:
            timetable = json.loads(company_row['live_timetable'])
        except:
            pass
            
    # 2. Parse Timetable for the target day
    target_date = datetime.strptime(date_str, '%Y-%m-%d')
    day_name = target_date.strftime('%a') # Mon, Tue...
    
    expected_work_hours = 0
    expected_start = None
    expected_end = None
    
    # Filter activities for this day
    day_activities = [a for a in timetable if day_name in a.get('days', [])]
    # Sort by start time
    day_activities.sort(key=lambda x: x.get('start_time', '00:00'))
    
    if day_activities:
        # Calculate expected hours (Work type only)
        for act in day_activities:
            if act.get('type') == 'Work':
                s = datetime.strptime(act['start_time'], '%H:%M')
                e = datetime.strptime(act['end_time'], '%H:%M')
                duration = (e - s).total_seconds() / 3600
                expected_work_hours += duration
        
        expected_start = day_activities[0]['start_time']
        expected_end = day_activities[-1]['end_time']

    # 3. Get all records for the day
    c.execute("SELECT * FROM attendance WHERE date(timestamp) = ? ORDER BY timestamp ASC", (date_str,))
    rows = c.fetchall()
    conn.close()

    # Group by user
    user_records = defaultdict(list)
    for row in rows:
        user_records[row['name']].append(dict(row))

    summary = []
    for user, records in user_records.items():
        stats = calculate_daily_hours(records)
        
        # 4. Compare with Schedule
        status = "Present"
        if stats['total_hours'] == 0:
            status = "Absent"
        elif expected_work_hours > 0:
            if stats['total_hours'] < (expected_work_hours - 0.5): # 30 min buffer
                status = "Undertime"
            elif stats['total_hours'] > (expected_work_hours + 1):
                status = "Overtime"
            else:
                status = "On Track"
        
        # Check Late Arrival
        arrival_status = "On Time"
        if expected_start and stats['sessions']:
            first_checkin = stats['sessions'][0]['start']
            # Simple string comparison works for HH:MM 24h format
            if first_checkin > expected_start: 
                # Add grace period check (e.g. 15 mins)
                exp_dt = datetime.strptime(expected_start, '%H:%M')
                act_dt = datetime.strptime(first_checkin, '%H:%M')
                if (act_dt - exp_dt).total_seconds() > 900: # 15 mins
                    arrival_status = "Late"

        summary.append({
            "name": user,
            "date": date_str,
            "schedule": {
                "expected_hours": round(expected_work_hours, 2),
                "expected_start": expected_start,
                "expected_end": expected_end,
            },
            "status": status,
            "arrival_status": arrival_status,
            **stats
        })

    return jsonify({"summary": summary})

app.register_blueprint(greeting_bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
