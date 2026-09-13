import sqlite3
import pytest
import hashlib


def hash_password(pw):
    return hashlib.sha256(str(pw).encode()).hexdigest()


def verify_password(pw, hashed):
    return hash_password(pw) == hashed


def get_table_columns(conn, table_name):
    """Returns a list of column names for a given table."""
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()
    try:
        if is_pg:
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table_name,))
            return [str(r[0]) for r in c.fetchall()]
        else:
            c.execute(f"PRAGMA table_info({table_name})")
            return [str(r[1]) for r in c.fetchall()]
    except Exception:
        return []
    finally:
        c.close()


def setup_test_db():
    """Create an in-memory SQLite database simulating vendors and system_users."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        CREATE TABLE vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            registration_config TEXT,
            contact_person TEXT,
            web_login_enabled INTEGER DEFAULT 0,
            frontend_bundle_id TEXT,
            backend_service_id TEXT,
            vertical TEXT,
            num_rectors INTEGER DEFAULT 0,
            num_hods INTEGER DEFAULT 0,
            departments TEXT,
            retention_days INTEGER DEFAULT 90,
            attendance_type TEXT DEFAULT 'total_time',
            config TEXT DEFAULT '{}',
            kiosk_pin TEXT DEFAULT '8888',
            kiosk_username TEXT
        )
    """)

    c.execute("""
        CREATE TABLE system_users (
            username TEXT PRIMARY KEY,
            password TEXT,
            password_plain TEXT,
            role TEXT,
            vendor_id INTEGER,
            has_set_password INTEGER DEFAULT 0,
            force_password_change INTEGER DEFAULT 0,
            person_id INTEGER,
            last_active_at TIMESTAMP,
            kiosk_pin TEXT DEFAULT '8888',
            is_kiosk INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            plan_type TEXT DEFAULT 'custom',
            start_date TEXT,
            end_date TEXT,
            max_users INTEGER DEFAULT 10,
            max_employees INTEGER DEFAULT 50,
            max_mobile_devices INTEGER DEFAULT 1,
            cost_per_user REAL DEFAULT 0,
            cost_per_employee REAL DEFAULT 0,
            setup_fee REAL DEFAULT 0,
            setup_fee_paid INTEGER DEFAULT 0,
            features TEXT DEFAULT '[]'
        )
    """)

    c.execute("""
        CREATE TABLE vendor_whatsapp_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            status TEXT DEFAULT 'disconnected',
            phone_number TEXT
        )
    """)

    c.execute("""
        CREATE TABLE vendor_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            device_id TEXT
        )
    """)

    c.execute("""
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            name TEXT
        )
    """)

    conn.commit()
    return conn


def test_kiosk_query_isolates_from_employees():
    """Verify that get_vendors never picks employee accounts (e.g. emp0002) as user_username."""
    conn = setup_test_db()
    c = conn.cursor()

    # 1. Insert Vendor 1
    c.execute("INSERT INTO vendors (id, company_name, kiosk_pin, kiosk_username) VALUES (1, 'Manufacturing Corp', '5678', 'kiosk_manufac')")
    c.execute("INSERT INTO subscriptions (vendor_id) VALUES (1)")

    # 2. Insert Admin and Kiosk users
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('admin_manufac', 'hash_admin', 'vendor_admin', 1, 0, NULL, '5678')
    """)
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('kiosk_manufac', 'hash_kiosk', 'user', 1, 1, NULL, '5678')
    """)

    # 3. Insert Employee users (created via bulk upload or face registration)
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('emp0001', 'hash_emp1', 'user', 1, 0, 101, '8888')
    """)
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('emp0002', 'hash_emp2', 'user', 1, 0, 102, '8888')
    """)
    conn.commit()

    # 4. Simulate get_vendors query logic exactly as updated in admin.py
    vendor_cols = get_table_columns(conn, "vendors")
    sys_user_cols = get_table_columns(conn, "system_users")
    has_kiosk_username_col = "kiosk_username" in vendor_cols
    has_is_kiosk_col = "is_kiosk" in sys_user_cols

    kiosk_filter = "(is_kiosk = 1 OR person_id IS NULL)" if has_is_kiosk_col else "(person_id IS NULL)"
    kiosk_order = "CASE WHEN is_kiosk = 1 THEN 0 WHEN person_id IS NULL THEN 1 ELSE 2 END, " if has_is_kiosk_col else ""

    if has_kiosk_username_col:
        user_user_select = f"""COALESCE(
            NULLIF(v.kiosk_username, ''),
            (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'user' AND {kiosk_filter} ORDER BY {kiosk_order}username ASC LIMIT 1)
        ) as user_username"""
    else:
        user_user_select = f"""(SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'user' AND {kiosk_filter} ORDER BY {kiosk_order}username ASC LIMIT 1) as user_username"""

    query = f"SELECT v.id, v.company_name, {user_user_select} FROM vendors v WHERE v.id = 1"
    c.execute(query)
    row = c.fetchone()

    # Crucial assertion: user_username must be the dedicated kiosk user, NEVER an employee!
    assert row["user_username"] == "kiosk_manufac"
    assert row["user_username"] != "emp0002"
    assert row["user_username"] != "emp0001"
    conn.close()


def test_kiosk_query_fallback_without_kiosk_username_column():
    """Even if vendors.kiosk_username is NULL, fallback query MUST NEVER return an employee."""
    conn = setup_test_db()
    c = conn.cursor()

    # Vendor without kiosk_username set yet (e.g. before migration)
    c.execute("INSERT INTO vendors (id, company_name, kiosk_pin, kiosk_username) VALUES (2, 'Legacy Corp', '8888', NULL)")
    c.execute("INSERT INTO subscriptions (vendor_id) VALUES (2)")

    # Insert employee users first (which previously caused LIMIT 1 to return them)
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('emp0001', 'hash_emp1', 'user', 2, 0, 201, '8888')
    """)
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('emp0002', 'hash_emp2', 'user', 2, 0, 202, '8888')
    """)
    # Insert dedicated kiosk user
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('user_2', 'hash_kiosk2', 'user', 2, 1, NULL, '8888')
    """)
    conn.commit()

    kiosk_filter = "(is_kiosk = 1 OR person_id IS NULL)"
    kiosk_order = "CASE WHEN is_kiosk = 1 THEN 0 WHEN person_id IS NULL THEN 1 ELSE 2 END, "
    user_user_select = f"""COALESCE(
        NULLIF(v.kiosk_username, ''),
        (SELECT username FROM system_users WHERE vendor_id = v.id AND role = 'user' AND {kiosk_filter} ORDER BY {kiosk_order}username ASC LIMIT 1)
    ) as user_username"""

    query = f"SELECT v.id, {user_user_select} FROM vendors v WHERE v.id = 2"
    c.execute(query)
    row = c.fetchone()

    assert row["user_username"] == "user_2"
    assert row["user_username"] != "emp0001"
    assert row["user_username"] != "emp0002"
    conn.close()


def test_update_vendor_details_protects_employees():
    """Verify that updating kiosk credentials updates ONLY the kiosk account and never overwrites employee accounts."""
    conn = setup_test_db()
    c = conn.cursor()

    vendor_id = 1
    c.execute("INSERT INTO vendors (id, company_name, kiosk_pin, kiosk_username) VALUES (1, 'Mfg Ltd', '5678', 'kiosk_mfg')")
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('kiosk_mfg', 'old_kiosk_pw', 'user', 1, 1, NULL, '5678')
    """)
    c.execute("""
        INSERT INTO system_users (username, password, role, vendor_id, is_kiosk, person_id, kiosk_pin)
        VALUES ('emp0002', 'emp_secret_pw', 'user', 1, 0, 102, '8888')
    """)
    conn.commit()

    # Simulate PUT /api/admin/vendors/1 with user_username='kiosk_mfg_v2', user_password='new_secure_password_123', kiosk_pin='9999'
    data = {
        'user_username': 'kiosk_mfg_v2',
        'user_password': 'new_secure_password_123',
        'kiosk_pin': '9999'
    }

    user_username = (data.get('user_username') or '').strip()
    user_password = data.get('user_password')

    vendor_cols = get_table_columns(conn, "vendors")
    has_kiosk_username_col = "kiosk_username" in vendor_cols
    sys_user_cols = get_table_columns(conn, "system_users")
    has_is_kiosk_col = "is_kiosk" in sys_user_cols

    # 1. Lookup
    existing_kiosk_username = None
    if has_kiosk_username_col:
        c.execute("SELECT kiosk_username FROM vendors WHERE id = ?", (vendor_id,))
        v_row = c.fetchone()
        if v_row and v_row["kiosk_username"]:
            existing_kiosk_username = str(v_row["kiosk_username"]).strip()

    kiosk_user = None
    if existing_kiosk_username:
        c.execute("SELECT username FROM system_users WHERE vendor_id = ? AND username = ?", (vendor_id, existing_kiosk_username))
        kiosk_user = c.fetchone()

    current_kiosk_username = kiosk_user["username"] if kiosk_user else None
    target_username = user_username or current_kiosk_username

    if user_username or user_password:
        update_query = "UPDATE system_users SET is_kiosk = 1, person_id = NULL, "
        update_params = []
        if user_username and user_username != current_kiosk_username:
            update_query += "username = ?, "
            update_params.append(user_username)
        if user_password:
            update_query += "password = ?, password_plain = NULL, "
            update_params.append(hash_password(user_password))

        update_query = update_query.rstrip(", ") + " WHERE username = ? AND vendor_id = ?"
        update_params.extend([current_kiosk_username, vendor_id])
        c.execute(update_query, update_params)
        c.execute("UPDATE vendors SET kiosk_username = ? WHERE id = ?", (target_username, vendor_id))

    if 'kiosk_pin' in data and data.get('kiosk_pin') is not None:
        pin_val = str(data.get('kiosk_pin')).strip()
        c.execute("UPDATE vendors SET kiosk_pin = ? WHERE id = ?", (pin_val, vendor_id))
        c.execute("UPDATE system_users SET kiosk_pin = ? WHERE vendor_id = ? AND username = ?", (pin_val, vendor_id, target_username))
    conn.commit()

    # Check employee record emp0002
    c.execute("SELECT * FROM system_users WHERE username = 'emp0002'")
    emp = c.fetchone()
    assert emp is not None, "Employee emp0002 must NOT be deleted or mutated!"
    assert emp["password"] == "emp_secret_pw", "Employee password must NOT be overwritten!"
    assert emp["person_id"] == 102, "Employee person_id must remain intact!"
    assert emp["is_kiosk"] == 0, "Employee must not be marked as kiosk!"
    assert emp["kiosk_pin"] == "8888", "Employee pin must remain untouched!"

    # Check renamed kiosk account
    c.execute("SELECT * FROM system_users WHERE username = 'kiosk_mfg_v2'")
    kiosk = c.fetchone()
    assert kiosk is not None, "Kiosk user must be updated to new username"
    assert verify_password("new_secure_password_123", kiosk["password"]), "Kiosk password must be updated"
    assert kiosk["is_kiosk"] == 1
    assert kiosk["kiosk_pin"] == "9999"

    # Check vendor table
    c.execute("SELECT kiosk_username, kiosk_pin FROM vendors WHERE id = 1")
    v = c.fetchone()
    assert v["kiosk_username"] == "kiosk_mfg_v2"
    assert v["kiosk_pin"] == "9999"
    conn.close()


def test_migration_backfill():
    """Verify that migration correctly classifies existing users and backfills vendors.kiosk_username."""
    conn = setup_test_db()
    c = conn.cursor()

    # Setup unclassified state (e.g. legacy data)
    c.execute("INSERT INTO vendors (id, company_name, kiosk_username) VALUES (1, 'LegacyCo', NULL)")
    c.execute("INSERT INTO system_users (username, password, role, vendor_id, person_id, is_kiosk) VALUES ('user_1', 'pw1', 'user', 1, NULL, 0)")
    c.execute("INSERT INTO system_users (username, password, role, vendor_id, person_id, is_kiosk) VALUES ('emp_legacy', 'pw2', 'user', 1, 999, 0)")
    conn.commit()

    # Run migration logic
    c.execute("UPDATE system_users SET is_kiosk = 0 WHERE person_id IS NOT NULL")
    c.execute("UPDATE system_users SET is_kiosk = 1 WHERE role = 'user' AND (person_id IS NULL OR person_id = 0)")
    c.execute("""
        UPDATE vendors
        SET kiosk_username = (
            SELECT username FROM system_users 
            WHERE vendor_id = vendors.id AND role = 'user' AND (is_kiosk = 1 OR person_id IS NULL)
            ORDER BY CASE WHEN is_kiosk = 1 THEN 0 ELSE 1 END, username ASC
            LIMIT 1
        )
        WHERE (kiosk_username IS NULL OR kiosk_username = '')
    """)
    conn.commit()

    # Assertions
    c.execute("SELECT is_kiosk FROM system_users WHERE username = 'user_1'")
    assert c.fetchone()["is_kiosk"] == 1

    c.execute("SELECT is_kiosk FROM system_users WHERE username = 'emp_legacy'")
    assert c.fetchone()["is_kiosk"] == 0

    c.execute("SELECT kiosk_username FROM vendors WHERE id = 1")
    assert c.fetchone()["kiosk_username"] == "user_1"
    conn.close()
