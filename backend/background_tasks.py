import os
import time
import glob
import shutil
import threading
from datetime import datetime
from utils import get_db_connection, is_testing, _PROJECT_ROOT, _BACKEND_DIR

def periodic_cleanup():
    """Background task to clean up temporary files and stale resources."""
    print("[CLEANUP] Background task started.", flush=True)
    while True:
        try:
            # 1. Clean up temporary test databases
            search_dirs = [_PROJECT_ROOT, _BACKEND_DIR]
            patterns = ["test_*.db", "test_*.db-shm", "test_*.db-wal", "test_features_*.db*"]
            
            for d in search_dirs:
                if not os.path.exists(d): continue
                for p in patterns:
                    for f in glob.glob(os.path.join(d, p)):
                        try:
                            if os.path.isfile(f):
                                os.remove(f)
                                print(f"[CLEANUP] Removed temp file: {f}", flush=True)
                            elif os.path.isdir(f):
                                shutil.rmtree(f)
                                print(f"[CLEANUP] Removed temp dir: {f}", flush=True)
                        except Exception as e:
                            print(f"[CLEANUP] Failed to remove {f}: {e}", flush=True)
            
            # 2. Database maintenance (SQLite only)
            try:
                from db_factory import DB_TYPE
                if DB_TYPE == 'sqlite':
                    conn = get_db_connection()
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.close()
            except Exception:
                pass

        except Exception as e:
            print(f"[CLEANUP] Error: {e}", flush=True)
        
        # Run every hour
        time.sleep(3600)

def start_background_tasks(app):
    """Starts all general background tasks."""
    if not is_testing():
        # Only start cleanup thread if it's the main process/first worker
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or os.environ.get("GUNICORN_WORKER_ID") == "1" or not os.environ.get("GUNICORN_WORKER_ID"):
            cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
            cleanup_thread.start()

def start_archival_thread():
    """Starts the archival background thread."""
    def archival_loop():
        from services.archival_service import run_archival
        # Wait a bit after startup
        time.sleep(60)
        while True:
            try:
                run_archival()
            except Exception as e:
                print(f"Archival Background Error: {e}")
            # Run once every 24 hours
            time.sleep(86400)
    
    t = threading.Thread(target=archival_loop, daemon=True)
    t.start()
