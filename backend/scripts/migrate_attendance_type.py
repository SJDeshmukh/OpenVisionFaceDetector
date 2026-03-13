
import sqlite3
import os

def migrate():
    # Manually load .env
    db_path = 'database.db'
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(backend_dir, '.env')
    
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
                    if key == 'DB_PATH':
                        db_path = value

    # If relative path, join with backend dir
    if not os.path.isabs(db_path):
        db_path = os.path.join(backend_dir, db_path)

    print(f"Connecting to {db_path}...")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        # Add attendance_type to vendors
        # total_time: sum of all sessions (default)
        # first_last: time between first check-in and last check-out
        c.execute("ALTER TABLE vendors ADD COLUMN attendance_type TEXT DEFAULT 'total_time'")
        print("Added attendance_type column to vendors table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("attendance_type column already exists.")
        else:
            print(f"Error: {e}")
            
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
