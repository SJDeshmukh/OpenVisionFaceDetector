import os
import io
import struct
import zipfile
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

def extract_apk_manifest_info(apk_file_or_bytes):
    """
    Parses Android Binary XML (AXML) from AndroidManifest.xml inside an APK.
    Extracts version_code, version_name, and package_name directly from the compiled binary.
    Zero external dependencies.
    """
    try:
        if isinstance(apk_file_or_bytes, bytes):
            zf = zipfile.ZipFile(io.BytesIO(apk_file_or_bytes), 'r')
        elif hasattr(apk_file_or_bytes, 'read'):
            pos = apk_file_or_bytes.tell() if hasattr(apk_file_or_bytes, 'tell') else None
            data_bytes = apk_file_or_bytes.read()
            if pos is not None and hasattr(apk_file_or_bytes, 'seek'):
                apk_file_or_bytes.seek(pos)
            zf = zipfile.ZipFile(io.BytesIO(data_bytes), 'r')
        else:
            zf = zipfile.ZipFile(apk_file_or_bytes, 'r')

        with zf:
            if 'AndroidManifest.xml' not in zf.namelist():
                return None
            data = zf.read('AndroidManifest.xml')

        if len(data) < 40:
            return None

        file_type, file_size = struct.unpack('<II', data[0:8])
        if file_type != 0x00080003:
            return None

        chunk_type, chunk_size, string_count, style_count, flags, strings_start, styles_start = struct.unpack('<IIIIIII', data[8:36])
        is_utf8 = bool(flags & (1 << 8))
        offset_table = struct.unpack(f'<{string_count}I', data[36:36 + 4 * string_count])
        strings_data_start = 8 + strings_start

        strings = []
        for offset in offset_table:
            pos = strings_data_start + offset
            if is_utf8:
                u16len = data[pos]
                pos += 1
                if u16len & 0x80: pos += 1
                u8len = data[pos]
                pos += 1
                if u8len & 0x80: pos += 1
                s = data[pos:pos+u8len].decode('utf-8', errors='replace')
            else:
                u16len = struct.unpack('<H', data[pos:pos+2])[0]
                pos += 2
                if u16len & 0x8000: pos += 2
                byte_len = u16len * 2
                s = data[pos:pos+byte_len].decode('utf-16le', errors='replace')
            strings.append(s)

        pos = 8 + chunk_size
        manifest_info = {'version_code': None, 'version_name': None, 'package_name': None}

        while pos < len(data):
            if pos + 8 > len(data): break
            c_type, c_size = struct.unpack('<II', data[pos:pos+8])
            if c_type == 0x00100102: # CHUNK_START_TAG
                tag_name_idx = struct.unpack('<I', data[pos+20:pos+24])[0]
                tag_name = strings[tag_name_idx] if tag_name_idx < len(strings) else ''
                attr_start, attr_size, attr_count = struct.unpack('<HHH', data[pos+24:pos+30])
                attr_pos = pos + 16 + attr_start

                for i in range(attr_count):
                    a_offset = attr_pos + i * attr_size
                    if a_offset + 20 > len(data): break
                    ns_idx, name_idx, val_str_idx, val_type, val_data = struct.unpack('<IIIIi', data[a_offset:a_offset+20])
                    name = strings[name_idx] if name_idx < len(strings) else ''
                    if name == 'package':
                        manifest_info['package_name'] = strings[val_str_idx] if val_str_idx < len(strings) else ''
                    elif name == 'versionCode':
                        manifest_info['version_code'] = val_data
                    elif name == 'versionName':
                        manifest_info['version_name'] = strings[val_str_idx] if (val_str_idx >= 0 and val_str_idx < len(strings)) else str(val_data)
                if tag_name == 'manifest': break
            pos += c_size
            if c_size == 0: break
        return manifest_info
    except Exception as e:
        logger.warning(f"Failed to extract manifest from APK: {e}")
        return None

def save_apk_release(conn, file_storage, version_code=None, version_name=None, 
                     package_name=None,
                     release_notes="", force_update=False, min_supported_version=1):
    """
    Saves an uploaded APK file and registers it in the database.
    Deactivates previous active releases so this newly uploaded release becomes the current active one.
    Automatically auto-detects version_code, version_name, and package_name directly from the APK binary!
    """
    ensure_storage_dir()
    ensure_app_releases_table(conn)

    # Read content to compute hash and size
    file_bytes = file_storage.read()
    file_size = len(file_bytes)
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # Automatically extract manifest details directly from the uploaded APK
    extracted = extract_apk_manifest_info(file_bytes)
    if extracted:
        if not version_code and extracted.get("version_code") is not None:
            version_code = extracted["version_code"]
        if not version_name and extracted.get("version_name"):
            version_name = extracted["version_name"]
        if not package_name and extracted.get("package_name"):
            package_name = extracted["package_name"]

    # Fallback if extraction was None and user did not provide values
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    if not version_code:
        c.execute("SELECT COALESCE(MAX(version_code), 0) + 1 FROM app_releases")
        row = c.fetchone()
        version_code = row[0] if row else 1

    if not version_name:
        version_name = f"{version_code}.0"

    if not package_name:
        package_name = "com.faceplugin.facerecognitionsdk"

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

def delete_release(conn, release_id):
    """
    Deletes an APK release from the database and removes its physical file from disk.
    If the deleted release was active, activates the newest remaining release (if any).
    """
    ensure_app_releases_table(conn)
    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    try:
        # 1. Fetch file path and active state
        select_sql = "SELECT file_path, is_active FROM app_releases WHERE id = %s" if is_pg else "SELECT file_path, is_active FROM app_releases WHERE id = ?"
        c.execute(select_sql, (release_id,))
        row = c.fetchone()
        if not row:
            return False, "Release not found"

        file_path = row[0] if not hasattr(row, 'keys') else row['file_path']
        was_active = bool(row[1] if not hasattr(row, 'keys') else row['is_active'])

        # 2. Delete from database
        del_sql = "DELETE FROM app_releases WHERE id = %s" if is_pg else "DELETE FROM app_releases WHERE id = ?"
        c.execute(del_sql, (release_id,))

        # 3. If was active, promote the newest remaining release to active
        if was_active:
            sub_sql = "SELECT id FROM app_releases ORDER BY version_code DESC, id DESC LIMIT 1"
            c.execute(sub_sql)
            rem_row = c.fetchone()
            if rem_row:
                new_active_id = rem_row[0] if not hasattr(rem_row, 'keys') else rem_row['id']
                upd_sql = "UPDATE app_releases SET is_active = TRUE WHERE id = %s" if is_pg else "UPDATE app_releases SET is_active = 1 WHERE id = ?"
                c.execute(upd_sql, (new_active_id,))

        conn.commit()

        # 4. Remove physical file from disk
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Failed to remove physical APK file {file_path}: {e}")

        return True, "Release and APK file deleted successfully"
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to delete release {release_id}: {e}")
        return False, str(e)
