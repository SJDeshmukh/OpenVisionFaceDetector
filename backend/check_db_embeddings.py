import sqlite3
import os
import numpy as np

def check_embeddings():
    # Found from backend/db_factory.py: DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "face_db.sqlite")
    # Since we run from root, backend/face_db.sqlite is the path.
    db_path = 'backend/face_db.sqlite'
        
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}. Checking root...")
        db_path = 'face_db.sqlite'
        if not os.path.exists(db_path):
            print("Database not found.")
            return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    print(f"Checking person_embeddings table in {db_path}...")
    try:
        c.execute("SELECT person_id, COUNT(*) FROM person_embeddings GROUP BY person_id ORDER BY person_id DESC LIMIT 20")
        rows = c.fetchall()
        
        if not rows:
            print("No embeddings found in person_embeddings.")
        else:
            print("Recent persons and their embedding counts:")
            for pid, count in rows:
                print(f"Person ID: {pid}, Embedding Count: {count}")
                
        c.execute("SELECT COUNT(*) FROM person_embeddings")
        total = c.fetchone()[0]
        print(f"\nTotal embeddings: {total}")
        
    except Exception as e:
        print(f"Error checking table: {e}")
        # Check if table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='person_embeddings'")
        if not c.fetchone():
            print("Table 'person_embeddings' does not exist!")
    
    conn.close()

if __name__ == "__main__":
    check_embeddings()
