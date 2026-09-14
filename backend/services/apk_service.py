import os
import hashlib
import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

# Directory where APKs are stored
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
APK_STORAGE_DIR = os.path.join(_STATIC_DIR, "apks")

def ensure_storage_dir():
    """Ensure the APK storage directory exists."""
    os.makedirs(APK_STORAGE_DIR, exist_ok=True)

def ensure_app_releases_table(conn):
    """
    Creates the app_releases table if it doesn't already exist.
    Supports both PostgreSQL and SQLite.
    """
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()
    try:
        if is_pg:
            c.execute("""
                CREATE TABLE IF NOT EXISTS app_releases (
                    id SERIAL PRIMARY KEY,
                    version_code INTEGER NOT NULL,
                    version_name VARCHAR(64) NOT NULL,
                    package_name VARCHAR(128) DEFAULT 'com.faceplugin.facerecognitionsdk',
                    file_name VARCHAR(255) NOT NULL,
                    file_path VARCHAR(512) NOT NULL,
                    file_size BIGINT NOT NULL,
                    checksum_sha256 VARCHAR(64),
                    release_notes TEXT,
                    min_supported_version INTEGER DEFAULT 1,
                    force_update BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_app_releases_code ON app_releases(version_code DESC);")
        else:
            c.execute("""
                CREATE TABLE IF NOT EXISTS app_releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_code INTEGER NOT NULL,
                    version_name TEXT NOT NULL,
                    package_name TEXT DEFAULT 'com.faceplugin.facerecognitionsdk',
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    checksum_sha256 TEXT,
                    release_notes TEXT,
                    min_supported_version INTEGER DEFAULT 1,
                    force_update INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_app_releases_code ON app_releases(version_code DESC);")
        conn.commit()
    except Exception as e:
        logger.error(f"Error creating app_releases table: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        raise e

def save_apk_release(conn, file_storage, version_code, version_name, 
                     package_name="com.faceplugin.facerecognitionsdk",
                     release_notes="", force_update=False, min_supported_version=1):
    """
    Saves an uploaded APK file and registers it in the database.
    Deactivates previous active releases so this newly uploaded release becomes the current active one.
    """
    ensure_storage_dir()
    ensure_app_releases_table(conn)

    # Read content to compute hash and size
    file_bytes = file_storage.read()
    file_size = len(file_bytes)
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # Generate a clean, unique filename: tapinx_v{code}_{sha256[:8]}.apk
    safe_file_name = f"tapinx_v{version_code}_{sha256_hash[:8]}.apk"
    full_file_path = os.path.join(APK_STORAGE_DIR, safe_file_name)

    # Write file to disk
    with open(full_file_path, "wb") as f:
        f.write(file_bytes)

    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    try:
        # Deactivate all existing releases
        if is_pg:
            c.execute("UPDATE app_releases SET is_active = FALSE")
        else:
            c.execute("UPDATE app_releases SET is_active = 0")

        # Insert new release
        force_val = True if force_update else False if is_pg else (1 if force_update else 0)
        active_val = True if is_pg else 1

        insert_sql = """
            INSERT INTO app_releases 
                (version_code, version_name, package_name, file_name, file_path, 
                 file_size, checksum_sha256, release_notes, min_supported_version, force_update, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, version_code, version_name, file_name, file_size, checksum_sha256, created_at
        """ if is_pg else """
            INSERT INTO app_releases 
                (version_code, version_name, package_name, file_name, file_path, 
                 file_size, checksum_sha256, release_notes, min_supported_version, force_update, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            int(version_code),
            str(version_name).strip(),
            str(package_name or "com.faceplugin.facerecognitionsdk").strip(),
            safe_file_name,
            full_file_path,
            int(file_size),
            sha256_hash,
            str(release_notes or "").strip(),
            int(min_supported_version or 1),
            force_val,
            active_val
        )

        c.execute(insert_sql, params)
        
        new_id = None
        if is_pg:
            res = c.fetchone()
            new_id = res[0] if res else None
        else:
            new_id = c.lastrowid

        conn.commit()

        return {
            "id": new_id,
            "version_code": int(version_code),
            "version_name": str(version_name),
            "file_name": safe_file_name,
            "file_size": file_size,
            "checksum_sha256": sha256_hash,
            "release_notes": release_notes,
            "force_update": bool(force_update),
            "is_active": True
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to register APK release: {e}")
        # Clean up file if database insert failed
        if os.path.exists(full_file_path):
            try:
                os.remove(full_file_path)
            except Exception:
                pass
        raise e

def get_latest_release(conn):
    """
    Returns the currently active latest release, or None if no release exists.
    """
    ensure_app_releases_table(conn)
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    sql = """
        SELECT id, version_code, version_name, package_name, file_name, file_path, 
               file_size, checksum_sha256, release_notes, min_supported_version, force_update, is_active, created_at
        FROM app_releases
        WHERE is_active = TRUE
        ORDER BY version_code DESC, id DESC
        LIMIT 1
    """ if is_pg else """
        SELECT id, version_code, version_name, package_name, file_name, file_path, 
               file_size, checksum_sha256, release_notes, min_supported_version, force_update, is_active, created_at
        FROM app_releases
        WHERE is_active = 1
        ORDER BY version_code DESC, id DESC
        LIMIT 1
    """

    c.execute(sql)
    row = c.fetchone()
    if not row:
        return None

    if hasattr(row, 'keys'):
        d = dict(row)
    else:
        cols = [desc[0] for desc in c.description]
        d = dict(zip(cols, row))

    if isinstance(d.get('created_at'), datetime):
        d['created_at'] = d['created_at'].isoformat()
    elif d.get('created_at') is not None:
        d['created_at'] = str(d['created_at'])

    d['force_update'] = bool(d.get('force_update'))
    d['is_active'] = bool(d.get('is_active'))

    return d

def list_all_releases(conn, limit=50):
    """
    Returns all releases ordered by version_code DESC.
    """
    ensure_app_releases_table(conn)
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    sql = """
        SELECT id, version_code, version_name, package_name, file_name, file_path, 
               file_size, checksum_sha256, release_notes, min_supported_version, force_update, is_active, created_at
        FROM app_releases
        ORDER BY version_code DESC, id DESC
        LIMIT %s
    """ if is_pg else """
        SELECT id, version_code, version_name, package_name, file_name, file_path, 
               file_size, checksum_sha256, release_notes, min_supported_version, force_update, is_active, created_at
        FROM app_releases
        ORDER BY version_code DESC, id DESC
        LIMIT ?
    """

    c.execute(sql, (limit,))
    rows = c.fetchall() or []
    results = []

    for row in rows:
        if hasattr(row, 'keys'):
            d = dict(row)
        else:
            cols = [desc[0] for desc in c.description]
            d = dict(zip(cols, row))

        if isinstance(d.get('created_at'), datetime):
            d['created_at'] = d['created_at'].isoformat()
        elif d.get('created_at') is not None:
            d['created_at'] = str(d['created_at'])

        d['force_update'] = bool(d.get('force_update'))
        d['is_active'] = bool(d.get('is_active'))
        results.append(d)

    return results

def activate_release(conn, release_id):
    """
    Sets the specified release as the active one.
    """
    ensure_app_releases_table(conn)
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    try:
        if is_pg:
            c.execute("UPDATE app_releases SET is_active = FALSE")
            c.execute("UPDATE app_releases SET is_active = TRUE WHERE id = %s", (release_id,))
        else:
            c.execute("UPDATE app_releases SET is_active = 0")
            c.execute("UPDATE app_releases SET is_active = 1 WHERE id = ?", (release_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to activate release {release_id}: {e}")
        return False
