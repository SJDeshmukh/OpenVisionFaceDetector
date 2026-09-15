from flask import Blueprint, jsonify, current_app, request, send_file, abort
import sqlite3
import os
import logging

# Ensure logging is configured
logger = logging.getLogger(__name__)

public_bp = Blueprint('public_bp', __name__)

# Note: BASE_URL and FRONTEND_URL will be imported from app or handled via current_app
# For now, we can use a helper or placeholder until we fully modularize

@public_bp.route('/config', methods=['GET'])
def get_config():
    return jsonify({
        "backend_url": os.environ.get("BASE_URL", "http://localhost:5000"),
        "frontend_url": os.environ.get("FRONTEND_URL", "http://localhost:3000")
    })

@public_bp.route('/vendors', methods=['GET'])
def public_vendors():
    from utils import get_db_connection
    conn = get_db_connection()
    # Handle both SQLite and PostgreSQL Row factory
    is_pg = getattr(conn, "_is_pg", False)
    if not is_pg:
        conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT id, company_name, vertical, status FROM vendors ORDER BY company_name ASC")
        rows = c.fetchall()
    except Exception as e:
        logger.error(f"Error fetching public vendors: {e}")
        rows = []
    finally:
        conn.close()

    vendors = []
    for r in rows or []:
        try:
            rd = dict(r) if not isinstance(r, dict) else r
            if str(rd.get("status") or "active").lower() != "active":
                continue
            vendors.append({
                "id": rd.get("id"),
                "company_name": rd.get("company_name"),
                "vertical": rd.get("vertical")
            })
        except Exception:
            pass
    return jsonify({"vendors": vendors})

@public_bp.route('/business-types', methods=['GET'])
def public_business_types():
    """
    Returns business types filtered to the requesting app brand.
    X-App-Brand: AttendX  →  only attendx types
    X-App-Brand: TapInX   →  only tapinx types
    No header              →  all types (web dashboard / legacy)
    """
    app_brand = (request.headers.get('X-App-Brand') or '').strip().lower()
    logger.info(f"Public business-types requested, brand='{app_brand}'")

    final_list = [
        # ── AttendX ──────────────────────────────────────────────────────────
        {
            "value": "bulk_attendance_attendx",
            "label": "AttendX",
            "app_type": "attendx",
            "allow_parent_login": True,
            "default_frontend_bundle_id": "attendx_bulk_ui",
            "default_registration_config": [
                {"field": "student_number", "label": "Student/Employee Number", "type": "text", "required": True},
                {"field": "class_section", "label": "Class/Department", "type": "text", "required": True},
                {"field": "daily_wage", "label": "Daily Wage", "type": "text", "required": False},
                {"field": "phone", "label": "Parent/Contact Mobile", "type": "text", "required": True}
            ]
        },
        # ── TapInX — Hostel ──────────────────────────────────────────────────
        {
            "value": "hostel",
            "label": "Hostel",
            "app_type": "tapinx",
            "allow_parent_login": True,
            "default_frontend_bundle_id": "tapinx_ui",
            "default_registration_config": [
                {"field": "student_id", "label": "Resident ID", "type": "text", "required": True},
                {"field": "phone", "label": "Resident Mobile Number", "type": "text", "required": True},
                {"field": "class_id", "label": "Room/Block", "type": "class_select", "required": True}
            ]
        },
        # ── TapInX — School / College ─────────────────────────────────────────
        {
            "value": "school",
            "label": "School / College",
            "app_type": "tapinx",
            "allow_parent_login": True,
            "default_frontend_bundle_id": "tapinx_ui",
            "default_registration_config": [
                {"field": "student_id", "label": "Student ID", "type": "text", "required": True},
                {"field": "phone", "label": "Student Mobile Number", "type": "text", "required": True},
                {"field": "class_id", "label": "Class/Section", "type": "class_select", "required": True}
            ]
        },
        # ── TapInX — Daily Wages (no parent login) ───────────────────────────
        {
            "value": "daily_wages",
            "label": "Daily Wages",
            "app_type": "tapinx",
            "allow_parent_login": False,
            "default_frontend_bundle_id": "tapinx_ui",
            "default_registration_config": [
                {"field": "employee_id", "label": "Employee ID", "type": "text", "required": True},
                {"field": "phone", "label": "Contact Mobile", "type": "text", "required": False},
                {"field": "department", "label": "Department", "type": "text", "required": False}
            ]
        },
        # ── Enterprise ───────────────────────────────────────────────────────
        {
            "value": "enterprise",
            "label": "Enterprise (Custom)",
            "app_type": "other",
            "allow_parent_login": False,
            "default_frontend_bundle_id": "default_attendance",
            "default_registration_config": []
        }
    ]

    # Filter by brand if the mobile app identified itself
    if app_brand == 'attendx':
        final_list = [t for t in final_list if t.get('app_type') == 'attendx']
    elif app_brand == 'tapinx':
        final_list = [t for t in final_list if t.get('app_type') == 'tapinx']

    logger.info(f"Returning {len(final_list)} business types for brand='{app_brand}'.")
    return jsonify({"business_types": final_list})

@public_bp.route('/app/latest-version', methods=['GET'], strict_slashes=False)
def get_latest_app_version():
    """
    Public endpoint for Android kiosks and mobile apps to check for OTA updates.
    Returns latest active version info, checksum, file size, and download URL.
    """
    from utils import get_db_connection
    from services.apk_service import get_latest_release
    conn = get_db_connection()
    try:
        release = get_latest_release(conn)
        if not release:
            return jsonify({
                "has_update": False,
                "latest_release": None,
                "message": "No active releases published"
            }), 200

        # Construct download URL (relative or absolute)
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/api/public/app/download/latest"

        return jsonify({
            "has_update": True,
            "release_id": release["id"],
            "version_code": release["version_code"],
            "version_name": release["version_name"],
            "package_name": release.get("package_name") or "com.faceplugin.facerecognitionsdk",
            "file_name": release["file_name"],
            "file_size": release["file_size"],
            "checksum_sha256": release.get("checksum_sha256"),
            "release_notes": release.get("release_notes") or "",
            "force_update": bool(release.get("force_update")),
            "min_supported_version": release.get("min_supported_version") or 1,
            "download_url": download_url,
            "created_at": release.get("created_at")
        }), 200
    except Exception as e:
        logger.error(f"Error checking latest app version: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@public_bp.route('/app/download/latest', methods=['GET'], strict_slashes=False)
def download_latest_apk():
    """
    Public endpoint to download the latest active APK file.
    Streams file with proper Android package mime-type.
    """
    from utils import get_db_connection
    from services.apk_service import get_latest_release
    conn = get_db_connection()
    try:
        release = get_latest_release(conn)
        if not release:
            return jsonify({"error": "No active release found"}), 404

        file_path = release.get("file_path")
        if not file_path or not os.path.exists(file_path):
            logger.error(f"APK file missing on disk: {file_path}")
            return jsonify({"error": "APK file not found on disk"}), 404

        return send_file(
            file_path,
            mimetype="application/vnd.android.package-archive",
            as_attachment=True,
            download_name=release.get("file_name") or "tapinx-release.apk"
        )
    except Exception as e:
        logger.error(f"Error downloading latest APK: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@public_bp.route('/app/download/<int:release_id>', methods=['GET'], strict_slashes=False)
def download_release_apk_by_id(release_id):
    """
    Public endpoint to download a specific release by its ID.
    """
    from utils import get_db_connection
    from services.apk_service import list_all_releases
    conn = get_db_connection()
    try:
        releases = list_all_releases(conn, limit=100)
        target = next((r for r in releases if r.get("id") == release_id), None)
        if not target:
            return jsonify({"error": "Release not found"}), 404

        file_path = target.get("file_path")
        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": "APK file not found on disk"}), 404

        return send_file(
            file_path,
            mimetype="application/vnd.android.package-archive",
            as_attachment=True,
            download_name=target.get("file_name") or f"tapinx-v{target.get('version_code')}.apk"
        )
    except Exception as e:
        logger.error(f"Error downloading APK {release_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass
