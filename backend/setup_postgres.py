import os
import sys
import subprocess
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import time

def get_current_user():
    import getpass
    return getpass.getuser()

def create_database(db_name="face_db"):
    user = get_current_user()
    # Default Postgres ports
    host = "localhost"
    port = "5432"
    
    print(f"Attempting to create database '{db_name}' on {host}:{port} as user '{user}'...")
    
    # Connection parameters to try
    # 1. User 'postgres', no password (common local dev)
    # 2. User 'postgres', password 'postgres'
    # 3. Current user, no password
    # 4. Current user, password 'postgres'
    
    attempts = [
        {"user": user, "dbname": "postgres"},
        {"user": "postgres", "dbname": "postgres"},
    ]

    conn = None
    connected_user = None

    for attempt in attempts:
        try:
            print(f"Connecting as {attempt['user']}...")
            conn = psycopg2.connect(
                dbname=attempt["dbname"],
                user=attempt["user"],
                host=host,
                port=port
            )
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            connected_user = attempt["user"]
            print("Success!")
            break
        except psycopg2.OperationalError:
            continue

    if not conn:
        print("\n----------------------------------------------------------------")
        print("ERROR: Could not connect to PostgreSQL server.")
        print("----------------------------------------------------------------")
        print("Troubleshooting steps:")
        print("1. Ensure PostgreSQL is installed.")
        print("   Run: brew install postgresql")
        print("2. Ensure the service is running.")
        print("   Run: brew services start postgresql")
        print("   Or:  pg_ctl -D /usr/local/var/postgres start")
        print("3. If you just installed it, wait a few seconds.")
        print("----------------------------------------------------------------")
        return False, None

    try:
        cur = conn.cursor()
        # Check if DB exists
        cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (db_name,))
        if cur.fetchone():
            print(f"Database '{db_name}' already exists.")
        else:
            print(f"Creating database '{db_name}'...")
            cur.execute(f"CREATE DATABASE {db_name}")
            print(f"Database '{db_name}' created successfully.")
            
        cur.close()
        conn.close()
        
        # Construct Database URL
        # We assume no password for local dev if we connected without one
        return True, f"postgresql://{connected_user}@localhost:5432/{db_name}"
        
    except Exception as e:
        print(f"An unexpected error occurred during DB creation: {e}")
        return False, None

def update_env_file(db_url):
    env_path = ".env"
    print(f"Updating {env_path}...")
    
    new_lines = []
    db_type_set = False
    db_url_set = False
    
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
            
        for line in lines:
            if line.startswith("DB_TYPE="):
                new_lines.append("DB_TYPE=postgres\n")
                db_type_set = True
            elif line.startswith("DATABASE_URL="):
                new_lines.append(f"DATABASE_URL={db_url}\n")
                db_url_set = True
            else:
                new_lines.append(line)
    
    if not db_type_set:
        new_lines.append("\n# Database Type\nDB_TYPE=postgres\n")
    if not db_url_set:
        new_lines.append(f"DATABASE_URL={db_url}\n")
        
    with open(env_path, "w") as f:
        f.writelines(new_lines)
        
    print(f"Updated {env_path} with DB_TYPE=postgres and DATABASE_URL.")

def run_migration(db_url):
    print("\nRunning migration script...")
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["DB_TYPE"] = "postgres"
    
    script_path = "migrate_to_postgres.py"
    if not os.path.exists(script_path):
        print(f"Error: {script_path} not found.")
        return False

    try:
        subprocess.run([sys.executable, script_path], env=env, check=True)
        print("Migration script executed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Migration script failed with exit code {e.returncode}")
        return False

def main():
    print("=== PostgreSQL Setup & Migration ===\n")
    
    # 1. Create DB
    success, db_url = create_database()
    if not success:
        sys.exit(1)
        
    # 2. Run Migration
    if not run_migration(db_url):
        print("Migration failed. Aborting .env update.")
        sys.exit(1)
        
    # 3. Update .env
    update_env_file(db_url)
    
    print("\n=== Setup Complete! ===")
    print("The application is now configured to use PostgreSQL.")
    print("Please restart the backend server.")

if __name__ == "__main__":
    main()
