# gunicorn_config.py
import os
from dotenv import load_dotenv
load_dotenv() # Load environmental variables from .env early

os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

port = os.environ.get("PORT", "5001")
bind = f"0.0.0.0:{port}"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
keepalive = 5
loglevel = "info"
accesslog = "-"
errorlog = "-"
capture_output = True

# Ensure the database and migrations are run on startup
def on_starting(server):
    print("Starting Gunicorn with gthread worker...")
    try:
        import db_factory
        import migrate_to_postgres
        
        # If running in Postgres mode (which is auto-detected if DATABASE_URL is set)
        if db_factory.DB_TYPE == 'postgres':
            print("PostgreSQL detected. Running safe migration/schema init...")
            migrate_to_postgres.run_safe_migration()
        else:
            print("Running in SQLite mode.")
    except Exception as e:
        print(f"Startup migration failed: {e}")
