import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not found.")
    exit(1)

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    # Reset sequence to 1. 
    # If the table has data, we should set it to MAX(id) + 1. 
    # If the user wants a clean slate, they should clear people first.
    cur.execute("SELECT COUNT(*) FROM faces;")
    count = cur.fetchone()[0]
    
    if count == 0:
        cur.execute("ALTER SEQUENCE faces_id_seq RESTART WITH 1;")
        print("Sequence reset to 1 (table is empty).")
    else:
        cur.execute("SELECT MAX(id) FROM faces;")
        max_id = cur.fetchone()[0]
        cur.execute(f"SELECT setval('faces_id_seq', {max_id});")
        print(f"Sequence set to {max_id} (max current ID).")
        
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
