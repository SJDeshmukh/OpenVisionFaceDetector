import sqlite3
import psycopg2
from datetime import datetime, timedelta
import logging
import os
import json

# Relative imports might be tricky depending on how its called, 
# but assuming its called from the root or as a module.
try:
    from db_factory import get_db_connection, get_backup_db_connection, DATABASE_URL
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db_factory import get_db_connection, get_backup_db_connection, DATABASE_URL

logger = logging.getLogger(__name__)

def run_archival():
    """
    Moves data older than retention_days from primary to backup database.
    """
    logger.info("Starting automated data archival process...")
    conn = get_db_connection()
    c = conn.cursor()
    
    backup_conn = get_backup_db_connection()
    bc = backup_conn.cursor()
    
    try:
        # 1. Fetch all vendors and their retention settings
        c.execute("SELECT id, retention_days FROM vendors")
        vendors = c.fetchall()
        
        total_archived = 0
        for v in vendors:
            vendor_id = v['id']
            # Default to 90 days if not set
            retention_days = v['retention_days'] if v['retention_days'] is not None else 90
            
            # Retention days = 0 means keep forever? 
            # Or per user request, we shift data after X days.
            if retention_days < 0:
                continue

            cutoff_date = (datetime.now() - timedelta(days=retention_days))
            
            # Handle different database types for date comparison
            if DATABASE_URL and not getattr(conn, "_is_fallback", False):
                # Postgres
                cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
                c.execute("SELECT * FROM attendance WHERE vendor_id = %s AND timestamp < %s", (vendor_id, cutoff_date))
            else:
                # SQLite
                cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
                c.execute("SELECT * FROM attendance WHERE vendor_id = ? AND timestamp < ?", (vendor_id, cutoff_str))
            
            records = c.fetchall()
            
            if records:
                start_date = None
                end_date = None
                
                for r in records:
                    # Convert row to dict for easy access
                    rd = dict(r)
                    
                    # Archive Attendance
                    # Columns: id, name, timestamp, status, captured_image, activity, is_late, device_id, vendor_id, person_id
                    bc.execute("""
                        INSERT OR IGNORE INTO attendance (id, name, timestamp, status, captured_image, activity, is_late, device_id, vendor_id, person_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (rd['id'], rd['name'], rd.get('timestamp'), rd['status'], rd.get('captured_image'), 
                          rd.get('activity'), rd.get('is_late', 0), rd.get('device_id'), rd['vendor_id'], rd.get('person_id')))
                    
                    # Track dates for metadata
                    ts = rd.get('timestamp')
                    if isinstance(ts, str):
                        try: ts = datetime.fromisoformat(ts.replace(' ', 'T'))
                        except: ts = None
                    
                    if ts:
                        if start_date is None or ts < start_date: start_date = ts
                        if end_date is None or ts > end_date: end_date = ts
                
                # Update Metadata only if we actually staged some records
                # Note: record_count is total found in primary for this cutoff
                bc.execute("""
                    INSERT INTO backup_metadata (vendor_id, start_date, end_date, record_count, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (vendor_id, start_date.isoformat() if start_date else None, 
                      end_date.isoformat() if end_date else None, len(records), 'archived'))
                
                # Delete from primary only after successful backup
                if DATABASE_URL and not getattr(conn, "_is_fallback", False):
                    c.execute("DELETE FROM attendance WHERE vendor_id = %s AND timestamp < %s", (vendor_id, cutoff_date))
                    c.execute("DELETE FROM leave_requests WHERE vendor_id = %s AND created_at < %s", (vendor_id, cutoff_date))
                else:
                    c.execute("DELETE FROM attendance WHERE vendor_id = ? AND timestamp < ?", (vendor_id, cutoff_str))
                    c.execute("DELETE FROM leave_requests WHERE vendor_id = ? AND created_at < ?", (vendor_id, cutoff_str))

                total_archived += len(records)
                logger.info(f"Archived {len(records)} records for vendor {vendor_id}")
            else:
                logger.debug(f"No records to archive for vendor {vendor_id}")
        
        conn.commit()
        backup_conn.commit()
        logger.info(f"Archival complete. Total records moved: {total_archived}")
        return total_archived
    except Exception as e:
        logger.error(f"Archival failed: {e}")
        try: conn.rollback()
        except: pass
        try: backup_conn.rollback()
        except: pass
        return 0
    finally:
        conn.close()
        backup_conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_archival()
