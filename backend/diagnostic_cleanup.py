import psycopg2
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db():
    return psycopg2.connect('postgresql://postgres:postgres@localhost:5432/face_db')

def _extract_sn(custom_data):
    if not custom_data: return None
    try:
        cd = json.loads(custom_data) if isinstance(custom_data, str) else custom_data
        return str(cd.get("student_number") or cd.get("student number") or cd.get("student_id") or cd.get("id_number") or "").strip()
    except: return None

def cleanup():
    conn = get_db()
    c = conn.cursor()
    
    logger.info("Scanning for ghost students (duplicates)...")
    
    # 1. Group faces by (vendor_id, extracted_student_number)
    c.execute("SELECT id, vendor_id, name, custom_data FROM faces")
    all_faces = c.fetchall()
    
    groups = {} # (vendor_id, sn) -> [list of ids]
    for fid, vid, name, cd in all_faces:
        sn = _extract_sn(cd)
        if not sn: continue
        key = (vid, sn.lower())
        if key not in groups: groups[key] = []
        groups[key].append(fid)
    
    to_delete = []
    for key, ids in groups.items():
        if len(ids) > 1:
            # Keep the highest ID, delete the rest
            ids.sort()
            keep = ids[-1]
            abandon = ids[:-1]
            logger.info(f"Duplicate found for Vendor {key[0]}, SN {key[1]}: Keeping {keep}, Deleting {abandon}")
            to_delete.extend(abandon)
            
    if to_delete:
        logger.info(f"Purging {len(to_delete)} ghost records...")
        ph = ",".join(["%s"] * len(to_delete))
        
        # Cleanup related tables first
        c.execute(f"DELETE FROM student_parents WHERE person_id IN ({ph})", to_delete)
        c.execute(f"UPDATE parent_users SET selected_person_id = NULL WHERE selected_person_id IN ({ph})", to_delete)
        c.execute(f"DELETE FROM person_embeddings WHERE person_id IN ({ph})", to_delete)
        c.execute(f"DELETE FROM attendance WHERE person_id IN ({ph})", to_delete)
        c.execute(f"DELETE FROM system_users WHERE person_id IN ({ph})", to_delete)
        c.execute(f"DELETE FROM advances WHERE person_id IN ({ph})", to_delete)
        c.execute(f"DELETE FROM lecture_attendance WHERE person_id IN ({ph})", to_delete)
        c.execute(f"DELETE FROM leave_requests WHERE student_id IN ({ph})", to_delete)
        
        c.execute(f"DELETE FROM faces WHERE id IN ({ph})", to_delete)
        
        conn.commit()
        logger.info("Ghost records purged successfully.")
    else:
        logger.info("No ghost students found.")
        
    # 2. Cleanup orphaned parent_users (those with invalid selected_person_id)
    logger.info("Cleaning up orphaned parent associations...")
    c.execute("DELETE FROM student_parents WHERE person_id NOT IN (SELECT id FROM faces)")
    c.execute("UPDATE parent_users SET selected_person_id = NULL WHERE selected_person_id NOT IN (SELECT id FROM faces)")
    conn.commit()
    
    conn.close()
    logger.info("Diagnostic cleanup complete.")

if __name__ == "__main__":
    cleanup()
