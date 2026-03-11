import os

auth_service = os.path.join("backend", "services", "auth_service.py")

func_code = """
import sqlite3
from datetime import datetime, date, timedelta

def check_vendor_status(vendor_id):
    \"\"\"
    Checks if a vendor is allowed to access the system.
    Returns: (is_allowed, reason)
    \"\"\"
    if not vendor_id:
        return True, "SuperAdmin"
        
    from app import get_db_connection
    conn = get_db_connection()
    if not getattr(conn, "_is_pg", False):
        conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Check Vendor Status
    c.execute("SELECT status FROM vendors WHERE id = ?", (vendor_id,))
    vendor = c.fetchone()
    if not vendor:
        conn.close()
        return False, "Vendor not found"
        
    if vendor['status'] != 'active':
        conn.close()
        return False, "Account Suspended"
        
    # Check Subscription Expiry
    c.execute("SELECT end_date, grace_period_days FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
    sub = c.fetchone()
    
    # Check Overdue Invoices
    today = date.today().isoformat()
    c.execute(\"\"\"
        SELECT COUNT(*) FROM invoices 
        WHERE vendor_id = ? 
        AND (status = 'overdue' OR (status = 'generated' AND due_date < ?))
    \"\"\", (vendor_id, today))
    overdue_count = c.fetchone()[0]
    
    conn.close()
    
    if overdue_count > 0:
        return False, "Unpaid Invoices"
    
    if sub and sub['end_date']:
        try:
            # Robust parsing (handle optional time)
            end_date_str = sub['end_date'].split(' ')[0]
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            grace = sub['grace_period_days'] or 0
            limit_date = end_date + timedelta(days=grace)
            
            if date.today() > end_date:
                return False, "Subscription Expired"
        except ValueError as e:
            return False, "Invalid Date Format"
            
    return True, "Active"
"""

with open(auth_service, "a") as f:
    f.write(func_code)

print("done appending check_vendor_status")
