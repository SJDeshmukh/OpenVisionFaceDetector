from flask import Blueprint, request, jsonify, send_file, g
import logging
import sqlite3
import json
import base64
import os
import hashlib
import io
import time
from datetime import datetime
import numpy as np
import cv2

logger = logging.getLogger(__name__)
from services.auth_service import authenticate_vendor_access, extract_token, verify_token, check_vendor_status, hash_password
import db_factory
from db_factory import set_row_factory
from utils import get_db_connection, LOW_RAM_MODE, _VENDOR_EMB_CACHE, reset_sequence, ALL_FEATURES, cache_delete_vendor_prefix, cache_delete, require_feature, cache_get, cache_set, decode_image_to_bgr, decode_image_to_rgb, get_face_augmentations
from services.face_service import _ensure_vendor_emb_cache, _normalize_vec, _suggest_from_cache
from storage import upload_base64_image, presigned_url_for_key, OBJECT_STORAGE_ENABLED, compress_image
import db_factory
from db_factory import set_row_factory
from concurrent.futures import ThreadPoolExecutor
from services.face_service import _extract_structural_vector

def _faculty_matches(mapped_faculty: str, username: str) -> bool:
    """True if mapped_faculty matches username, handling email vs local-part differences.

    mapped_subjects may store 'talekar@kbtcoe.org' while g.username is 'talekar', or vice-versa.
    """
    a = (mapped_faculty or "").lower().strip()
    b = (username or "").lower().strip()
    if not a or not b:
        return False
    if a == b:
        return True
    # strip domain from whichever side has one
    a_local = a.split("@")[0]
    b_local = b.split("@")[0]
    return a_local == b_local or a_local == b or a == b_local


def _get_redis():
    try:
        from app import redis_client as _rc
        return _rc
    except Exception:
        return None

try:
    import eventlet
except ImportError:
    eventlet = None

# Thread-pool fallback for heavy CPU/GPU-bound work when eventlet isn't available
_INFER_MAX_WORKERS = int(os.environ.get("INFER_THREADS", "2"))
_INFER_EXECUTOR = ThreadPoolExecutor(max_workers=_INFER_MAX_WORKERS) if eventlet is None else None


# require_feature imported from utils.py
def rate_limit(*args, **kwargs):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator

faces_bp = Blueprint('faces_bp', __name__)

def _unassign_faculty_from_classes(c, conn, vendor_id, usernames):
    """Remove faculty assignments from classes.mapped_subjects for the given usernames."""
    if not usernames or not vendor_id:
        return
    username_set = set(str(u) for u in usernames if u)
    if not username_set:
        return
    try:
        c.execute("SELECT id, mapped_subjects FROM classes WHERE vendor_id = ?", (vendor_id,))
        rows = c.fetchall() or []
        for row in rows:
            cls_id = row[0]
            ms_raw = row[1]
            try:
                ms = json.loads(ms_raw) if ms_raw else []
            except Exception:
                continue
            updated = False
            for entry in ms:
                if isinstance(entry, dict) and entry.get('faculty') in username_set:
                    entry['faculty'] = None
                    updated = True
            if updated:
                c.execute("UPDATE classes SET mapped_subjects = ? WHERE id = ?",
                          (json.dumps(ms), cls_id))
    except Exception:
        pass


def reindex_vendor_faces(conn, vendor_id):
    """Re-assigns display_id for all faces in a vendor to be gapless [1, 2, 3...]."""
    if not vendor_id:
        return
    c = conn.cursor()
    # Get all faces for this vendor ordered by creation (id)
    c.execute("SELECT id FROM faces WHERE vendor_id = ? ORDER BY id ASC", (vendor_id,))
    faces = [r[0] for r in c.fetchall()]
    for idx, fid in enumerate(faces):
        c.execute("UPDATE faces SET display_id = ? WHERE id = ?", (idx + 1, fid))
    conn.commit()

def vendor_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        vendor_id, err = authenticate_vendor_access()
        if err: return err
        request.vendor_id = vendor_id
        return f(*args, **kwargs)
    return decorated

# Mock track_metrics
def track_metrics(endpoint_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator


@faces_bp.route("/utils/detect-faces", methods=["POST"])
@require_feature("bulk_image_attendance")
def detect_faces_basic():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    try:
        file = None
        if 'image' in request.files:
            file = request.files['image'].read()
        else:
            data = request.get_json(silent=True) or {}
            img_b64 = data.get('image')
            if img_b64 and isinstance(img_b64, str):
                parts = img_b64.split(',', 1)
                payload = parts[1] if len(parts) == 2 else parts[0]
                file = base64.b64decode(payload)
        if not file:
            return jsonify({"error": "image required"}), 400
        
        img_hash = hashlib.sha256(file).hexdigest()
        bgr = decode_image_to_bgr(file)
        if bgr is None:
            return jsonify({"error": "invalid image"}), 400
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        from tasks import detect_faces_task
        try:
            # We must pass the raw base64 string because detect_faces_task base64 decodes it
            task_result = detect_faces_task.apply_async(args=[img_b64, data, vendor_id]).get(timeout=60)
            faces = task_result.get("faces", [])
            annotated_b64 = task_result.get("annotated_b64", "")
        except Exception as e:
            return jsonify({"error": f"Celery inference timeout or failure: {str(e)}"}), 500

        resp = {"faces": faces, "count": len(faces), "annotated_image": annotated_b64}
        redis = _get_redis()
        if redis:
            try:
                redis.setex(cache_key, cache_ttl, json.dumps(resp))
            except Exception:
                pass
        return jsonify(resp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@faces_bp.route("/utils/search-embedding", methods=["POST"])
def search_embedding():
    from services.auth_service import authenticate_vendor_access
    from tasks import search_embedding_task
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    try:
        data = request.get_json(silent=True) or {}
        img_b64 = data.get('image')
        if not img_b64:
            return jsonify({"error": "image required"}), 400
            
        from celery_app import celery
        if not celery:
            # Fallback to sync if celery not configured
            # (Keeping it simple for now, but in production we want it always async)
            return jsonify({"error": "Celery worker not available"}), 503

        task = search_embedding_task.delay(img_b64, data, vendor_id)
        return jsonify({"task_id": task.id, "status": "processing"}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@faces_bp.route("/utils/detect-faces-async", methods=["POST"])
def detect_faces_async():
    from services.auth_service import authenticate_vendor_access
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    try:
        data = request.get_json(silent=True) or {}
        img_b64 = data.get('image')
        if not img_b64:
            return jsonify({"error": "image required"}), 400
        from celery_app import celery
        if not celery:
            return jsonify({"error": "Celery worker not available"}), 503
        # Request deduplication by image hash + params
        try:
            header, payload = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
            raw = base64.b64decode(payload)
            img_hash = hashlib.sha256(raw).hexdigest()
        except Exception:
            img_hash = None
        pr = (data.get('priority') or 'normal').strip().lower()
        queue = 'normal_priority'
        if pr in ('high', 'vip', 'premium'):
            queue = 'high_priority'
        elif pr in ('low', 'bulk'):
            queue = 'low_priority'
        dedup_ttl = int(os.environ.get("DETECT_DEDUP_TTL", "120"))
        from tasks import detect_faces_task
        redis = _get_redis()
        if redis and img_hash:
            dedup_key = f"det-task:v1:{vendor_id}:{queue}:{img_hash}"
            try:
                existing = redis.get(dedup_key)
                if existing:
                    return jsonify({"task_id": existing.decode('utf-8'), "status": "processing"}), 202
            except Exception:
                pass
        task = detect_faces_task.apply_async(args=[img_b64, data, vendor_id], queue=queue)
        if redis and img_hash:
            try:
                redis.setex(f"det-task:v1:{vendor_id}:{queue}:{img_hash}", dedup_ttl, task.id)
            except Exception:
                pass
        return jsonify({"task_id": task.id, "status": "processing"}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@faces_bp.route("/utils/detect-faces-batch-async", methods=["POST"])
def detect_faces_batch_async():
    from services.auth_service import authenticate_vendor_access
    vendor_id, error = authenticate_vendor_access()
    if error:
        return error
    try:
        data = request.get_json(silent=True) or {}
        images = data.get('images') or []
        if not isinstance(images, list) or len(images) == 0:
            return jsonify({"error": "images array required"}), 400
        from celery_app import celery
        if not celery:
            return jsonify({"error": "Celery worker not available"}), 503
        from celery import group
        from tasks import detect_faces_task
        pr = (data.get('priority') or 'normal').strip().lower()
        queue = 'normal_priority'
        if pr in ('high', 'vip', 'premium'):
            queue = 'high_priority'
        elif pr in ('low', 'bulk'):
            queue = 'low_priority'
        # Build task signatures
        sigs = []
        for img_b64 in images:
            sigs.append(detect_faces_task.s(img_b64, data, vendor_id).set(queue=queue))
        task_ids = []
        group_id = None
        try:
            grp = group(sigs)
            result = grp.apply_async()
            group_id = getattr(result, 'id', None)
            try:
                # children returns AsyncResult list; collect ids
                task_ids = [ar.id for ar in (result.children or []) if hasattr(ar, 'id')]
            except Exception:
                task_ids = []
        except Exception:
            # Fallback: dispatch one-by-one
            for sig in sigs:
                ar = sig.apply_async()
                if hasattr(ar, 'id'):
                    task_ids.append(ar.id)
        resp = {"task_ids": task_ids}
        if group_id:
            resp["group_id"] = group_id
        return jsonify(resp), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@faces_bp.route("/persons", methods=["GET"])
def get_persons():
    from app import get_db_connection, socketio, is_testing
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    # Cache based on vendor and request parameters
    cache_params = sorted(request.args.items())
    cache_key = f"vendor:{vendor_id}:persons_list:{hash(tuple(cache_params))}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    conn = get_db_connection()
    set_row_factory(conn)
    c = conn.cursor()
    
    query = "SELECT id, display_id, name, department, designation, shift, daily_wage, face_image, phone, custom_data FROM faces"
    params = []
    
    if vendor_id:
        if g.user_role == 'faculty':
            # 1. Identify which classes this faculty is assigned to
            c.execute("SELECT class_year, division, branch, mapped_subjects FROM classes WHERE vendor_id = ?", (vendor_id,))
            all_classes = c.fetchall() or []
            assigned_classes = []
            for cl in all_classes:
                try:
                    ms = json.loads(cl[3]) if cl[3] else []
                    if any(_faculty_matches(m.get('faculty', ''), g.username) for m in ms):
                        assigned_classes.append((cl[0], cl[1], cl[2])) # (year, div, branch)
                except (json.JSONDecodeError, ValueError): pass
            
            if not assigned_classes:
                conn.close()
                return jsonify({"persons": []}) # No assigned classes = no students visible
            
            # 2. Build query to filter by these classes
            query += " WHERE vendor_id = ?"
            params.append(vendor_id)
            
            # Build a filter that matches ANY of the assigned classes
            is_pg = getattr(conn, "_is_pg", False)
            class_filters = []
            for y, d, b in assigned_classes:
                if is_pg:
                    f = "( (custom_data::jsonb->>'class_year' = ? OR custom_data::jsonb->>'Year' = ?) AND (custom_data::jsonb->>'division' = ? OR custom_data::jsonb->>'Division' = ?) AND (custom_data::jsonb->>'branch' = ? OR custom_data::jsonb->>'Branch' = ?) )"
                    class_filters.append(f)
                    params.extend([str(y), str(y), str(d), str(d), str(b), str(b)])
                else:
                    f = "( (custom_data LIKE ? OR custom_data LIKE ?) AND (custom_data LIKE ? OR custom_data LIKE ?) AND (custom_data LIKE ? OR custom_data LIKE ?) )"
                    class_filters.append(f)
                    params.extend([f'%\"class_year\":\"{y}\"%', f'%\"Year\":\"{y}\"%', f'%\"division\":\"{d}\"%', f'%\"Division\":\"{d}\"%', f'%\"branch\":\"{b}\"%', f'%\"Branch\":\"{b}\"%'])
            
            if class_filters:
                query += " AND (" + " OR ".join(class_filters) + ")"
        else:
            query += " WHERE vendor_id = ?"
            params.append(vendor_id)
        
    is_pg = getattr(conn, "_is_pg", False)
    class_year = request.args.get('class_year')
    division = request.args.get('division')
    branch = request.args.get('branch')
    
    if class_year:
        if is_pg:
            query += " AND (LOWER(TRIM(custom_data::jsonb->>'class_year')) = LOWER(TRIM(?)) OR LOWER(TRIM(custom_data::jsonb->>'Year')) = LOWER(TRIM(?)) OR LOWER(TRIM(custom_data::jsonb->>'year')) = LOWER(TRIM(?)))"
            params.extend([str(class_year), str(class_year), str(class_year)])
        else:
            query += " AND (LOWER(custom_data) LIKE ? OR LOWER(custom_data) LIKE ? OR LOWER(custom_data) LIKE ?)"
            params += [f'%\"class_year\":\"{class_year.lower()}\"%', f'%\"year\":\"{class_year.lower()}\"%', f'%\"Year\":\"{class_year.lower()}\"%']
            
    if division:
        if is_pg:
            query += " AND (LOWER(TRIM(custom_data::jsonb->>'division')) = LOWER(TRIM(?)) OR LOWER(TRIM(custom_data::jsonb->>'Division')) = LOWER(TRIM(?)))"
            params += [str(division), str(division)]
        else:
            query += " AND (LOWER(custom_data) LIKE ? OR LOWER(custom_data) LIKE ?)"
            params += [f'%\"division\":\"{division.lower()}\"%', f'%\"Division\":\"{division.lower()}\"%']
            
    if branch:
        if is_pg:
            query += " AND (LOWER(TRIM(custom_data::jsonb->>'branch')) = LOWER(TRIM(?)) OR LOWER(TRIM(custom_data::jsonb->>'Branch')) = LOWER(TRIM(?)))"
            params += [str(branch), str(branch)]
        else:
            query += " AND (LOWER(custom_data) LIKE ? OR LOWER(custom_data) LIKE ?)"
            params += [f'%\"branch\":\"{branch.lower()}\"%', f'%\"Branch\":\"{branch.lower()}\"%']
            
    # Default sorting to ensure stability (Display ID based)
    query += " ORDER BY display_id ASC"

    # Optional pagination
    try:
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params += [limit, offset]
    except (ValueError, TypeError):
        pass
    try:
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        logger.error("Persons query failed", exc_info=True)
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500
    
    persons = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row.copy()
        if r.get("custom_data") and isinstance(r["custom_data"], str):
            try:
                r["custom_data"] = json.loads(r["custom_data"])
            except Exception:
                pass
        persons.append(r)
    
    result = {"persons": persons}
    cache_set(cache_key, result, 300) # 5 min cache
    return jsonify(result)


@faces_bp.route("/sync/upload", methods=["POST"])
@require_feature("mobile_app", "bulk_image_attendance")
def upload_face():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    # Auth Check
    caller_vendor_id, error = authenticate_vendor_access()
    if error: return error

    data = request.json
    person_id = data.get("person_id")
    name = data.get("name")
    templates = data.get("templates")
    templates_list = data.get("templates_list")
    face_image = data.get("face_image")
    phone = data.get("phone")
    department = data.get("department")
    designation = data.get("designation")
    shift = data.get("shift")
    landmarks_3d = data.get("landmarks_3d")
    landmarks_3d_list = data.get("landmarks_3d_list")
    struct_vec = data.get("struct_vec")
    struct_vec_list = data.get("struct_vec_list")
    
    # Class Scope Support
    class_year = data.get("class_year")
    division = data.get("division")
    branch = data.get("branch")
    
    # Extract Custom Data (Dynamic Fields)
    standard_fields = {
        'person_id', 'name', 'templates', 'templates_list', 'face_image', 'phone', 
        'department', 'designation', 'shift', 'vendor_id', 
        'landmarks_3d', 'landmarks_3d_list', 'struct_vec', 'struct_vec_list'
        # 'class_year', 'division', 'branch' are intentional kept out here to be part of custom_dict
        # because the faces table lacks these columns and they must be in custom_data for UI.
    }
    custom_dict = {k: v for k, v in data.items() if k not in standard_fields}
    
    # Ensure scope fields are in custom_dict for UI visibility (Faces table lacks columns)
    if class_year: custom_dict['class_year'] = class_year
    if division: custom_dict['division'] = division
    if branch: custom_dict['branch'] = branch
    
    custom_data = json.dumps(custom_dict) if custom_dict else None
    
    # --- AUTOMATED EXTRACTION FOR NEW UPLOADS ---
    # We always re-extract embeddings from the face_image if provided to ensure
    # OCP (FacePlugin) compatibility, bypassing any ArcFace templates from the scan.
    if face_image:
        try:
            from services.face_service import _decode_data_uri_to_rgb
            from multiple_face_detection import app as mfd_app
            img_rgb_base = _decode_data_uri_to_rgb(face_image)
            if img_rgb_base is not None:
                # face_image is already a detected+refined crop from the pipeline.
                # Augment the crop directly — re-running face detection here is
                # redundant and fails on tight crops that have no margin.
                emb_list = []
                for aug_img in get_face_augmentations(img_rgb_base):
                    emb = mfd_app.get_embedder().embed(aug_img)
                    if emb is not None and emb.size > 0:
                        emb_list.append(_normalize_vec(emb))

                if emb_list:
                    templates_list = [
                        base64.b64encode(e.astype(np.float32).tobytes()).decode('utf-8')
                        for e in emb_list
                    ]

                # Structural vector from the original image (used for 3D pose consistency)
                engine = mfd_app.get_realtime_engine()
                if engine:
                    lmks = engine.extract_landmarks(img_rgb_base)
                    if lmks:
                        sv = mfd_app._extract_structural_vector(lmks[0])
                        if sv is not None and sv.size > 0:
                            struct_vec_list = [base64.b64encode(sv.astype(np.float32).tobytes()).decode('utf-8')]
                            landmarks_3d_list = [lmks[0].tolist()]
        except Exception as e:
            print(f"[FACES_ROUTE] OCP Auto-extraction failed: {e}", flush=True)

    # Use caller's vendor_id. If SuperAdmin, allow overriding via payload.
    vendor_id = caller_vendor_id
    if not vendor_id:
        vendor_id = data.get("vendor_id")

    if not name:
        return jsonify({"error": "Missing name"}), 400

    try:
        c = get_db_connection().cursor()
    except Exception:
        pass

    try:
        conn_check = get_db_connection()
        cc = conn_check.cursor()
        vertical = None
        if vendor_id:
            cc.execute("SELECT vertical FROM vendors WHERE id = ?", (vendor_id,))
            r = cc.fetchone()
            vertical = r[0] if r else None
        student_number = None
        try:
            student_number = str(custom_dict.get('student_number') or custom_dict.get('student_id') or custom_dict.get('id_number') or '').strip()
        except Exception:
            student_number = None
        if vertical == 'school' and student_number:
            if person_id:
                cc.execute("SELECT id, custom_data FROM faces WHERE vendor_id = ? AND id != ?", (vendor_id, person_id))
            else:
                cc.execute("SELECT id, custom_data FROM faces WHERE vendor_id = ?", (vendor_id,))
            rows = cc.fetchall()
            for r in rows:
                try:
                    cd = json.loads(r[1]) if r[1] else {}
                    sn = str(cd.get('student_id') or cd.get('id_number') or '').strip()
                    if sn and sn == student_number:
                        conn_check.close()
                        return jsonify({"error": "Duplicate student_number for this vendor"}), 409
                except Exception:
                    continue
        # Generic duplicate guard for new registrations:
        # If creating a new person (no person_id), block if name or templates already exist for this vendor
        if not person_id:
            try:
                if vendor_id:
                    if templates_list and isinstance(templates_list, list) and len(templates_list) > 0:
                        cc.execute("SELECT templates FROM faces WHERE vendor_id = ?", (vendor_id,))
                        rows_all = cc.fetchall()
                        for rtpl in rows_all:
                            try:
                                et = rtpl[0] if not isinstance(rtpl, dict) else rtpl.get("templates")
                                if not et:
                                    continue
                                if et.startswith('['):
                                    arr = json.loads(et)
                                    for t in templates_list:
                                        if t in arr:
                                            conn_check.close()
                                            return jsonify({"error": "Face already registered for this vendor (templates_list)"}), 409
                                else:
                                    for t in templates_list:
                                        if t == et:
                                            conn_check.close()
                                            return jsonify({"error": "Face already registered for this vendor (templates)"}), 409
                            except Exception:
                                continue
                    elif vendor_id and templates and str(templates).strip() != "":
                        cc.execute("SELECT id FROM faces WHERE vendor_id = ? AND templates = ? LIMIT 1", (vendor_id, templates))
                        row_tpl = cc.fetchone()
                        if row_tpl:
                            conn_check.close()
                            return jsonify({"error": "Face already registered for this vendor (templates)"}), 409
            except Exception:
                pass
        conn_check.close()
    except Exception:
        pass

    # 1. Vendor Status Check
    if vendor_id:
        allowed, reason = check_vendor_status(vendor_id)
        if not allowed:
            return jsonify({"error": f"Access Denied: {reason}"}), 403

    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # 2. Employee Limit Check & Operation
        if not person_id and vendor_id:
            # Check limit (only for new users)
            c.execute("SELECT max_employees FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
            sub = c.fetchone()
            max_employees = (sub[0] if sub and sub[0] is not None else 50)
            
            c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (vendor_id,))
            current_count = c.fetchone()[0]
            
            if current_count >= max_employees:
                conn.close()
                return jsonify({"error": f"Employee Limit Reached ({max_employees}). Upgrade your plan."}), 403

        if face_image:
            try:
                # Always compress, regardless of storage backend
                data_part = face_image.split(",")[-1] if "," in face_image else face_image
                raw_body = base64.b64decode(data_part)
                processed_body = compress_image(raw_body)
                face_image = base64.b64encode(processed_body).decode('utf-8')
                
                if OBJECT_STORAGE_ENABLED:
                    s3_url = upload_base64_image(name or f"face_{datetime.now().timestamp()}", face_image)
                    if s3_url:
                        image_url = presigned_url_for_key(s3_url, expires_seconds=3600)
                        face_image = image_url
            except Exception as e:
                print(f"Image processing error: {e}")
                pass
        if person_id:
            if caller_vendor_id:
                c.execute(
                    "SELECT name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data FROM faces WHERE id=? AND vendor_id=?",
                    (person_id, caller_vendor_id),
                )
            else:
                c.execute(
                    "SELECT name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data FROM faces WHERE id=?",
                    (person_id,),
                )
            row = c.fetchone()
            if not row:
                return jsonify({"error": "Person not found"}), 404
            existing = {
                "name": row[0],
                "templates": row[1],
                "face_image": row[2],
                "phone": row[3],
                "department": row[4],
                "designation": row[5],
                "shift": row[6],
                "vendor_id": row[7],
                "custom_data": row[8]
            }
            if custom_data is None and existing["custom_data"]:
                try:
                    old = json.loads(existing["custom_data"])
                    for k, v in custom_dict.items():
                        old[k] = v
                    custom_data = json.dumps(old)
                except Exception:
                    custom_data = existing["custom_data"]
            fields = []
            params = []
            if name is not None:
                fields.append("name=?"); params.append(name)
            if templates_list and isinstance(templates_list, list) and len(templates_list) > 0:
                fields.append("templates=?"); params.append(json.dumps(templates_list))
            elif templates is not None and templates != "":
                fields.append("templates=?"); params.append(templates)
            if face_image is not None and face_image != "":
                fields.append("face_image=?"); params.append(face_image)
            if phone is not None and phone != "":
                fields.append("phone=?"); params.append(phone)
            if department is not None and department != "":
                fields.append("department=?"); params.append(department)
            if designation is not None and designation != "":
                fields.append("designation=?"); params.append(designation)
            if shift is not None and shift != "":
                fields.append("shift=?"); params.append(shift)
            if caller_vendor_id is None and vendor_id is not None:
                fields.append("vendor_id=?"); params.append(vendor_id)
            if custom_data is not None:
                fields.append("custom_data=?"); params.append(custom_data)
            
            # Allow manual override of display_id/Student ID
            display_id = data.get("display_id")
            if display_id is not None:
                fields.append("display_id=?"); params.append(display_id)

            if not fields:
                new_id = person_id
            else:
                q = "UPDATE faces SET " + ", ".join(fields) + " WHERE id=?"
                params.append(person_id)
                c.execute(q, params)
                new_id = person_id
                
                # CRITICAL: Sync metadata to person_embeddings if scope changed
                # Ensure the recognition engine can still find these embeddings under the new class/division/branch
                if class_year is not None or division is not None or branch is not None:
                    sync_fields = []
                    sync_params = []
                    if class_year is not None: sync_fields.append("class_year = ?"); sync_params.append(str(class_year))
                    if division is not None: sync_fields.append("division = ?"); sync_params.append(str(division))
                    if branch is not None: sync_fields.append("branch = ?"); sync_params.append(str(branch))
                    if sync_fields:
                        sync_params.append(person_id)
                        c.execute(f"UPDATE person_embeddings SET {', '.join(sync_fields)} WHERE person_id = ?", sync_params)
                
                # If face image or templates are updated, clear accumulated embeddings
                if (face_image is not None and face_image != "") or (templates_list and len(templates_list) > 0) or (templates is not None and templates != ""):
                    try:
                        # Only delete if we are actually providing new templates to replace them!
                        target_templates = templates_list if (templates_list and len(templates_list) > 0) else None
                        if not target_templates and templates:
                            try:
                                target_templates = json.loads(templates)
                                if not isinstance(target_templates, list): target_templates = [templates]
                            except Exception:
                                target_templates = [templates]
                        
                        if target_templates:
                            c.execute("DELETE FROM person_embeddings WHERE person_id = ?", (person_id,))
                            
                            # PERSIST NEW EMBEDDINGS if templates provided
                            for idx, t_item in enumerate(target_templates):
                                try:
                                    # Handle both base64 strings and raw lists
                                    if isinstance(t_item, str):
                                        raw_bytes = base64.b64decode(t_item)
                                        emb = np.frombuffer(raw_bytes, dtype=np.float32).copy()
                                    elif isinstance(t_item, (list, tuple)):
                                        emb = np.array(t_item, dtype=np.float32)
                                    else:
                                        continue
                                    
                                    from services.face_service import _normalize_vec
                                    emb = _normalize_vec(emb)
                                    if emb.size > 0:
                                        vec_blob = emb.astype(np.float32).tobytes()
                                        
                                        # Handle associated features
                                        cur_struct_blob = None
                                        cur_lmks_json = None
                                        
                                        # Try to get corresponding indexed feature
                                        sv = None
                                        if struct_vec_list and idx < len(struct_vec_list):
                                            sv = struct_vec_list[idx]
                                        elif idx == 0 and struct_vec:
                                            sv = struct_vec
                                            
                                        if sv:
                                            try:
                                                if isinstance(sv, str):
                                                    cur_struct_blob = base64.b64decode(sv)
                                                else:
                                                    cur_struct_blob = np.array(sv, dtype=np.float32).tobytes()
                                            except Exception: pass
                                            
                                        lm = None
                                        if landmarks_3d_list and idx < len(landmarks_3d_list):
                                            lm = landmarks_3d_list[idx]
                                        elif idx == 0 and landmarks_3d:
                                            lm = landmarks_3d
                                            
                                        if lm:
                                            try: cur_lmks_json = json.dumps(lm)
                                            except Exception: pass

                                        c.execute("""INSERT INTO person_embeddings (vendor_id, person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d) 
                                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                                                  (vendor_id or existing.get("vendor_id"), person_id, str(class_year or ''), str(division or ''), str(branch or ''), vec_blob, int(emb.size), cur_struct_blob, cur_lmks_json))
                                except Exception:
                                    continue

                        # Invalidate cache
                        vid = existing.get("vendor_id") or vendor_id
                        prefix = f"{int(vid or 0)}_"
                        keys_to_delete = [k for k in _VENDOR_EMB_CACHE.keys() if str(k).startswith(prefix)]
                        for k in keys_to_delete:
                            del _VENDOR_EMB_CACHE[k]
                    except Exception:
                        pass

            try:
                if phone is not None and phone != "" and str(phone) != str(existing.get("phone") or ""):
                    updated_cd = custom_data if custom_data is not None else existing.get("custom_data")
                    student_number_for_parent = None
                    try:
                        cd_obj = json.loads(updated_cd) if updated_cd else {}
                        if isinstance(cd_obj, dict):
                            student_number_for_parent = str(cd_obj.get("student_id") or cd_obj.get("id_number") or "").strip()
                    except Exception:
                        student_number_for_parent = None
                    if student_number_for_parent:
                        c.execute(
                            "UPDATE parent_users SET contact_phone = ?, device_id = NULL, fcm_token = NULL, session_version = COALESCE(session_version, 1) + 1 WHERE vendor_id = ? AND student_number = ?",
                            (phone, existing.get("vendor_id"), student_number_for_parent),
                        )
                    
                    # --- Automated Student Login Sync on Update ---
                    c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (existing.get("vendor_id"),))
                    s_row = c.fetchone()
                    features = json.loads(s_row[0]) if s_row and s_row[0] else []
                    
                    if 'leave_management' in features:
                        # If phone or ID changed, we might need to update the login
                        cd_old_obj = json.loads(existing.get("custom_data") or "{}") if existing.get("custom_data") else {}
                        old_sid = str(cd_old_obj.get("student_id") or cd_old_obj.get("id_number") or "").strip()
                        new_sid = student_number_for_parent
                        new_phone = str(phone or "").strip()
                        
                        if new_sid and new_phone:
                            # Check if a login exists for this person_id
                            c.execute("SELECT username, password_plain FROM system_users WHERE person_id = ?", (person_id,))
                            login_row = c.fetchone()
                            
                            if login_row:
                                old_username = login_row[0]
                                old_plain = login_row[1]
                                
                                # If the username (student ID) changed, update it
                                if old_username != new_sid:
                                    c.execute("UPDATE system_users SET username = ? WHERE person_id = ?", (new_sid, person_id))
                                
                                # If the password was still the old phone number, update it to the new one
                                if old_plain == str(existing.get("phone") or "").strip():
                                    c.execute("UPDATE system_users SET password = ?, password_plain = ? WHERE person_id = ?", 
                                              (new_phone, new_phone, person_id))
                            else:
                                # Proactively create it if it didn't exist
                                c.execute("INSERT OR IGNORE INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (?, ?, ?, 'user', ?, ?)",
                                          (new_sid, new_phone, new_phone, existing.get("vendor_id"), person_id))
            except Exception:
                pass
        else:
            # Insert New
            to_store_templates = None
            if templates_list and isinstance(templates_list, list) and len(templates_list) > 0:
                to_store_templates = json.dumps(templates_list)
            else:
                to_store_templates = templates or ""
            # Get next display_id for this vendor
            c.execute("SELECT COALESCE(MAX(display_id), 0) + 1 FROM faces WHERE vendor_id = ?", (vendor_id,))
            next_display_id = c.fetchone()[0]

            c.execute("INSERT INTO faces (name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data, display_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (name, to_store_templates, face_image, phone or "", department or "", designation or "", shift or "", vendor_id, custom_data, next_display_id))
            new_id = c.lastrowid
            
            # --- Automated Student Login Creation ("Inking") ---
            try:
                # Check if leave management is enabled for this vendor
                c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
                s_row = c.fetchone()
                features = json.loads(s_row[0]) if s_row and s_row[0] else []
                
                if 'leave_management' in features:
                    # Extract student ID from custom_data
                    cd_obj = json.loads(custom_data) if custom_data else {}
                    student_id = str(cd_obj.get("student_id") or cd_obj.get("id_number") or "").strip()
                    student_phone = str(phone or "").strip()
                    
                    if student_id and student_phone:
                        # Check if user already exists
                        c.execute("SELECT username FROM system_users WHERE username = ?", (student_id,))
                        if not c.fetchone():
                            # Create system user
                            # Using phone as initial password
                            c.execute(
                                "INSERT INTO system_users (username, password, password_plain, role, vendor_id, person_id) VALUES (?, ?, ?, 'user', ?, ?)",
                                (student_id, student_phone, student_phone, vendor_id, new_id)
                            )
                            # We don't need to commit here if the outer transaction commits
            except Exception as e:
                pass # Non-critical if auto-creation fails 
            
            # Invalidate cache and persist embeddings for new insert
            try:
                # PERSIST EMBEDDINGS if templates provided
                target_templates = templates_list if (templates_list and len(templates_list) > 0) else None
                if not target_templates and templates:
                    try:
                        target_templates = json.loads(templates)
                        if not isinstance(target_templates, list): target_templates = [templates]
                    except Exception:
                        target_templates = [templates]
                
                if target_templates:
                    for idx, t_item in enumerate(target_templates):
                        try:
                            if isinstance(t_item, str):
                                raw_bytes = base64.b64decode(t_item)
                                emb = np.frombuffer(raw_bytes, dtype=np.float32).copy()
                            elif isinstance(t_item, (list, tuple)):
                                emb = np.array(t_item, dtype=np.float32)
                            else:
                                continue
                            
                            from services.face_service import _normalize_vec
                            emb = _normalize_vec(emb)
                            if emb.size > 0:
                                vec_blob = emb.astype(np.float32).tobytes()
                                
                                # Handle associated features
                                cur_struct_blob = None
                                cur_lmks_json = None
                                
                                sv = None
                                if struct_vec_list and idx < len(struct_vec_list):
                                    sv = struct_vec_list[idx]
                                elif idx == 0 and struct_vec:
                                    sv = struct_vec
                                    
                                if sv:
                                    try:
                                        if isinstance(sv, str):
                                            cur_struct_blob = base64.b64decode(sv)
                                        else:
                                            cur_struct_blob = np.array(sv, dtype=np.float32).tobytes()
                                    except Exception: pass
                                    
                                lm = None
                                if landmarks_3d_list and idx < len(landmarks_3d_list):
                                    lm = landmarks_3d_list[idx]
                                elif idx == 0 and landmarks_3d:
                                    lm = landmarks_3d
                                    
                                if lm:
                                    try: cur_lmks_json = json.dumps(lm)
                                    except Exception: pass

                                c.execute("""INSERT INTO person_embeddings (vendor_id, person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d) 
                                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (vendor_id, new_id, str(class_year or ''), str(division or ''), str(branch or ''), vec_blob, int(emb.size), cur_struct_blob, cur_lmks_json))
                        except Exception:
                            continue

                prefix = f"{int(vendor_id or 0)}_"
                keys_to_delete = [k for k in _VENDOR_EMB_CACHE.keys() if str(k).startswith(prefix)]
                for k in keys_to_delete:
                    del _VENDOR_EMB_CACHE[k]
            except Exception:
                pass

        conn.commit()

        # Schedule async metric projection retrain (3-second debounce).
        try:
            from metric_learning import schedule_retrain as _sched_retrain
            _sched_retrain(int(vendor_id or 0))
        except Exception:
            pass

        # Invalidate vendor-specific caches and global stats
        if vendor_id:
            cache_delete_vendor_prefix(vendor_id)
        cache_delete("admin_stats")

        # Real-time update for Vendor Dashboard (People List) and SuperAdmin (Limits)
        socketio.emit('persons_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
        socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')

        return jsonify({"status": "success", "message": f"Face for {name} saved.", "person_id": new_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@faces_bp.route("/sync/download", methods=["GET"], endpoint="sync_download_route")
@require_feature("mobile_app")
@track_metrics("sync_download")
@rate_limit(limit=120, window=60)
def download_faces():
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    set_row_factory(conn)
    c = conn.cursor()
    
    query = """
        SELECT f.*, su.role as system_role
        FROM faces f
        LEFT JOIN system_users su ON f.id = su.person_id
    """
    params = []
    
    if vendor_id:
        query += " WHERE f.vendor_id = ?"
        params.append(vendor_id)
        
    # Default sorting by Display ID
    query += " ORDER BY f.display_id ASC"
    
    # Optional pagination
    try:
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params += [limit, offset]
    except (ValueError, TypeError):
        pass
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    faces = []
    for row in rows:
        r = dict(row)
        face_item = {
            "id": r.get("id"),
            "display_id": r.get("display_id") or r.get("id"),
            "name": r.get("name"),
            "templates": r.get("templates"),
            "face_image": r.get("face_image"),
            "phone": r.get("phone", ""),
            "department": r.get("department", ""),
            "designation": r.get("designation", ""),
            "shift": r.get("shift", ""),
            "role": r.get("system_role"),
            "custom_data": json.loads(r["custom_data"]) if r.get("custom_data") else {}
        }
        try:
            if face_item["face_image"] and isinstance(face_item["face_image"], str) and face_item["face_image"].startswith("s3://"):
                url = presigned_url_for_key(face_item["face_image"])
                if url:
                    face_item["image_url"] = url
            elif face_item["face_image"] and isinstance(face_item["face_image"], str) and face_item["face_image"].startswith("http"):
                face_item["image_url"] = face_item["face_image"]
        except Exception:
            pass
        faces.append(face_item)
    
    return jsonify({"faces": faces})


@faces_bp.route("/sync/delete/<name>", methods=["DELETE"])
@require_feature("mobile_app")
def delete_face(name):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    if not name:
        return jsonify({"error": "Missing name"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        face_rows = []
        if vendor_id:
            c.execute("SELECT id, vendor_id, display_id, phone, custom_data FROM faces WHERE name = ? AND vendor_id = ?", (name, vendor_id))
            face_rows = c.fetchall() or []
        else:
            c.execute("SELECT id, vendor_id, display_id, phone, custom_data FROM faces WHERE name = ?", (name,))
            face_rows = c.fetchall() or []
        
        if not face_rows:
            return jsonify({"error": "User not found"}), 404

        # Track affected vendors and their deleted display_ids for re-indexing
        affected_vendors = {} # vendor_id -> list of deleted_display_ids
        for r in face_rows:
            v_id = r[1]
            d_id = r[2]
            p_id = r[0]
            if v_id not in affected_vendors: affected_vendors[v_id] = []
            affected_vendors[v_id].append(d_id)
            # CRITICAL: Clean up embeddings for this person
            c.execute("DELETE FROM person_embeddings WHERE person_id = ?", (p_id,))
            # If this face is a faculty member, unassign from classes
            try:
                c.execute("SELECT username FROM system_users WHERE person_id = ? AND role = 'faculty'", (p_id,))
                fac_rows = c.fetchall() or []
                fac_usernames = [row[0] for row in fac_rows if row[0]]
                if fac_usernames and v_id:
                    _unassign_faculty_from_classes(c, conn, v_id, fac_usernames)
            except Exception:
                pass

        if vendor_id:
            c.execute("DELETE FROM faces WHERE name = ? AND vendor_id = ?", (name, vendor_id))
        else:
            c.execute("DELETE FROM faces WHERE name = ?", (name,))
        deleted_faces = c.rowcount

        # Re-index for each affected vendor
        for v_id, deleted_ids in affected_vendors.items():
            # For each deleted ID, we shift everything above it down.
            # Shifting in reverse order of deleted_ids (highest first) avoids double-counting if we do it one by one, 
            # but it's simpler to just do a full re-index if multiple were deleted, or just loop correctly.
            # Best way: for each vendor, we know which IDs were removed. 
            # We can run a single query like:
            # UPDATE faces SET display_id = (SELECT COUNT(*) FROM faces f2 WHERE f2.vendor_id = faces.vendor_id AND f2.id <= faces.id) WHERE vendor_id = ?
            # But that's O(N^2). 
            # Better: just decrement for each deleted ID.
            for d_id in sorted(deleted_ids, reverse=True):
                c.execute("UPDATE faces SET display_id = display_id - 1 WHERE vendor_id = ? AND display_id > ?", (v_id, d_id))

        try:
            by_vendor = {}
            student_numbers_by_vendor = {}
            phones_by_vendor = {}
            for r in face_rows:
                pid = r[0]
                vid = r[1]
                if vid is None:
                    continue
                by_vendor.setdefault(int(vid), []).append(int(pid))
                sn = None
                try:
                    c_data = r[4]  # custom_data is column index 4
                    if c_data:
                        cd = json.loads(c_data) if isinstance(c_data, str) else c_data
                        if isinstance(cd, dict):
                            sn = str(cd.get("student_id") or cd.get("student_number") or cd.get("id_number") or "").strip()
                except Exception:
                    sn = None
                if sn:
                    student_numbers_by_vendor.setdefault(int(vid), set()).add(sn)
                try:
                    ph = r[3]  # phone is column index 3
                    if ph:
                        phones_by_vendor.setdefault(int(vid), set()).add(str(ph).strip())
                except Exception:
                    pass
            for vid, ids in by_vendor.items():
                placeholders = ",".join(["?"] * len(ids))
                c.execute(
                    f"DELETE FROM attendance WHERE vendor_id = ? AND (name = ? OR person_id IN ({placeholders}))",
                    [vid, name, *ids],
                )
                c.execute(
                    f"DELETE FROM student_parents WHERE vendor_id = ? AND person_id IN ({placeholders})",
                    [vid, *ids],
                )
                c.execute(
                    f"UPDATE parent_users SET selected_person_id = NULL WHERE vendor_id = ? AND selected_person_id IN ({placeholders})",
                    [vid, *ids],
                )
                c.execute(
                    f"DELETE FROM parent_users WHERE vendor_id = ? AND selected_person_id IN ({placeholders}) AND NOT EXISTS (SELECT 1 FROM student_parents WHERE parent_id = parent_users.id)",
                    [vid, *ids],
                )
                # Delete leave requests and lecture attendance for the deleted person(s)
                try:
                    c.execute(
                        f"DELETE FROM leave_requests WHERE vendor_id = ? AND student_id IN ({placeholders})",
                        [vid, *ids],
                    )
                except Exception:
                    pass
                try:
                    c.execute(
                        f"DELETE FROM lecture_attendance WHERE vendor_id = ? AND person_id IN ({placeholders})",
                        [vid, *ids],
                    )
                except Exception:
                    pass
                # Delete all embeddings for the deleted person(s)
                c.execute(
                    f"DELETE FROM person_embeddings WHERE vendor_id = ? AND person_id IN ({placeholders})",
                    [vid, *ids],
                )
                # Delete system_users (student logins) for the deleted person(s)
                try:
                    c.execute(
                        f"DELETE FROM system_users WHERE person_id IN ({placeholders})",
                        ids,
                    )
                except Exception:
                    pass
                # Invalidate embedding cache for this vendor
                for k in list(_VENDOR_EMB_CACHE.keys()):
                    if isinstance(k, (int, str)) and str(k).startswith(str(vid)):
                        del _VENDOR_EMB_CACHE[k]
                    elif isinstance(k, tuple) and len(k) > 0 and k[0] == vid:
                        del _VENDOR_EMB_CACHE[k]
                for sn in sorted(student_numbers_by_vendor.get(int(vid), set())):
                    c.execute("DELETE FROM parent_tokens WHERE vendor_id = ? AND student_number = ?", (vid, sn))
                    c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND student_number = ? AND NOT EXISTS (SELECT 1 FROM student_parents WHERE parent_id = parent_users.id)", (vid, sn))
                for ph in sorted(phones_by_vendor.get(int(vid), set())):
                    try:
                        c.execute("SELECT id, student_number FROM parent_users WHERE vendor_id = ? AND contact_phone = ?", (vid, ph))
                        rows_pu = c.fetchall() or []
                        parent_ids = [row[0] for row in rows_pu if row and row[0] is not None]
                        if parent_ids:
                            ph_placeholders = ",".join(["?"] * len(parent_ids))
                            c.execute(f"DELETE FROM student_parents WHERE vendor_id = ? AND parent_id IN ({ph_placeholders})", [vid, *parent_ids])
                        for pu_row in rows_pu:
                            try:
                                sn_val = pu_row[1]
                                if sn_val:
                                    c.execute("DELETE FROM parent_tokens WHERE vendor_id = ? AND student_number = ?", (vid, str(sn_val).strip()))
                            except Exception:
                                pass
                        c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND contact_phone = ? AND NOT EXISTS (SELECT 1 FROM student_parents WHERE parent_id = parent_users.id)", (vid, ph))
                    except Exception:
                        pass
        except Exception:
            pass
            
        conn.commit()
        try:
            # Re-index all affected vendors
            for vid in by_vendor.keys():
                reindex_vendor_faces(conn, vid)
            reset_sequence("faces")
        except Exception:
            pass

        if deleted_faces > 0:
            # Real-time update
            if vendor_id:
                socketio.emit('persons_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
                socketio.emit('attendance_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
                socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
            
            return jsonify({"status": "success", "message": f"Face for {name} deleted."})
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@faces_bp.route("/sync/delete/id/<int:person_id>", methods=["DELETE"])
@require_feature("mobile_app")
def delete_face_by_id(person_id):
    from app import get_db_connection, socketio, is_testing
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Get name for message and scoping
        target_vendor_id = vendor_id
        phone = None
        custom_data = None
        if vendor_id:
            c.execute("SELECT name, phone, custom_data FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        else:
            c.execute("SELECT name, vendor_id, phone, custom_data FROM faces WHERE id = ?", (person_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        name = row[0]
        if not target_vendor_id:
            try:
                target_vendor_id = row[1]
            except Exception:
                target_vendor_id = None
        try:
            phone = row[2] if not vendor_id else row[1]
        except Exception:
            phone = None
        try:
            custom_data = row[3] if not vendor_id else row[2]
        except Exception:
            custom_data = None
        sn = None
        try:
            if custom_data:
                cd = json.loads(custom_data) if isinstance(custom_data, str) else custom_data
                if isinstance(cd, dict):
                    sn = str(cd.get("student_id") or cd.get("id_number") or "").strip()
        except Exception:
            sn = None
        # Get display_id and vendor_id for re-indexing
        c.execute("SELECT display_id, vendor_id FROM faces WHERE id = ?", (person_id,))
        del_row = c.fetchone()
        deleted_display_id = del_row[0] if del_row else None
        target_vendor_id = del_row[1] if del_row else None

        # 1. Cleanup related records FIRST to avoid FK violations in PostgreSQL.
        #    Each statement is individually guarded so one missing table never
        #    skips the critical system_users delete that causes the FK violation.
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Cleaning up associated records for person_id={person_id}")

        # If this person is a faculty member, unassign them from classes before deletion
        try:
            c.execute("SELECT username FROM system_users WHERE person_id = ? AND role = 'faculty'", (person_id,))
            fac_rows = c.fetchall() or []
            fac_usernames = [r[0] for r in fac_rows if r[0]]
            if fac_usernames and target_vendor_id:
                _unassign_faculty_from_classes(c, conn, target_vendor_id, fac_usernames)
        except Exception as _e:
            logger.warning(f"Faculty class unassign skipped for person_id={person_id}: {_e}")

        for _sql, _args in [
            ("DELETE FROM attendance WHERE person_id = ?",                          (person_id,)),
            ("DELETE FROM student_parents WHERE person_id = ?",                     (person_id,)),
            ("UPDATE parent_users SET selected_person_id = NULL WHERE selected_person_id = ?", (person_id,)),
            ("DELETE FROM leave_requests WHERE student_id = ?",                     (person_id,)),
            ("DELETE FROM lecture_attendance WHERE person_id = ?",                  (person_id,)),
            ("DELETE FROM person_embeddings WHERE person_id = ?",                   (person_id,)),
            # system_users MUST be deleted before faces due to FK constraint
            ("DELETE FROM system_users WHERE person_id = ?",                        (person_id,)),
        ]:
            try:
                c.execute(_sql, _args)
            except Exception as _e:
                logger.warning(f"Cleanup step skipped (person_id={person_id}): {_sql!r} → {_e}")

        if sn:
            for _sql, _args in [
                ("DELETE FROM system_users WHERE username = ?", (sn,)),
            ]:
                try:
                    c.execute(_sql, _args)
                except Exception as _e:
                    logger.warning(f"Cleanup (sn) skipped: {_sql!r} → {_e}")

        # Clear embedding cache for this vendor
        try:
            for k in list(_VENDOR_EMB_CACHE.keys()):
                if isinstance(k, (int, str)) and str(k).startswith(str(target_vendor_id)):
                    del _VENDOR_EMB_CACHE[k]
                elif isinstance(k, tuple) and len(k) > 0 and k[0] == target_vendor_id:
                    del _VENDOR_EMB_CACHE[k]
        except Exception:
            pass

        # Clean up parent/token relations — each guarded independently
        if sn:
            for _sql, _args in [
                ("DELETE FROM parent_tokens WHERE vendor_id = ? AND student_number = ?", (target_vendor_id, sn)),
                ("DELETE FROM parent_users WHERE vendor_id = ? AND student_number = ? AND NOT EXISTS (SELECT 1 FROM student_parents WHERE parent_id = parent_users.id)",  (target_vendor_id, sn)),
            ]:
                try:
                    c.execute(_sql, _args)
                except Exception as _e:
                    logger.warning(f"Parent cleanup skipped: {_sql!r} → {_e}")

        if phone:
            try:
                c.execute("SELECT id, student_number FROM parent_users WHERE vendor_id = ? AND contact_phone = ?", (target_vendor_id, str(phone).strip()))
                rows_pu = c.fetchall() or []
                parent_ids = [row[0] for row in rows_pu if row and row[0] is not None]
                if parent_ids:
                    ph_placeholders = ",".join(["?"] * len(parent_ids))
                    c.execute(f"DELETE FROM student_parents WHERE vendor_id = ? AND parent_id IN ({ph_placeholders})", [target_vendor_id, *parent_ids])
                for pu_row in rows_pu:
                    try:
                        sn_val = pu_row[1]
                        if sn_val:
                            c.execute("DELETE FROM parent_tokens WHERE vendor_id = ? AND student_number = ?", (target_vendor_id, str(sn_val).strip()))
                    except Exception:
                        pass
                c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND contact_phone = ? AND NOT EXISTS (SELECT 1 FROM student_parents WHERE parent_id = parent_users.id)", (target_vendor_id, str(phone).strip()))
            except Exception as e:
                logger.warning(f"Phone-based parent cleanup skipped for person_id={person_id}: {e}")

        # 2. Finally delete the face record
        if vendor_id:
            c.execute("DELETE FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        else:
            c.execute("DELETE FROM faces WHERE id = ?", (person_id,))
        deleted_faces = c.rowcount

        # 3. Re-index remaining faces for this vendor
        if deleted_faces > 0 and target_vendor_id is not None:
            reindex_vendor_faces(conn, target_vendor_id)
            
            # Reset registration config if 0 users remain as per user request
            c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (target_vendor_id,))
            if c.fetchone()[0] == 0:
                c.execute("UPDATE bulk_attendance_config SET fields = '[]' WHERE vendor_id = ?", (target_vendor_id,))
                c.execute("UPDATE vendors SET registration_config = '[]' WHERE id = ?", (target_vendor_id,))
                logger.info(f"Zero students remain for vendor {target_vendor_id}. Registration config cleared.")

        conn.commit()
        
        # Invalidate vendor-specific caches and global stats
        if vendor_id:
            cache_delete_vendor_prefix(vendor_id)
        cache_delete("admin_stats")
        
        try:
            reset_sequence("faces")
        except Exception:
            pass

        if deleted_faces > 0:
            if vendor_id:
                socketio.emit('persons_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
                socketio.emit('attendance_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
                socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
            return jsonify({"status": "success", "message": f"Face for {name} deleted.", "person_id": person_id})
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@faces_bp.route("/sync/delete-all", methods=["DELETE"])
@vendor_required
def delete_all_faces():
    from app import get_db_connection, socketio
    vendor_id = request.vendor_id
    target = request.args.get('target', 'people')
    
    if not vendor_id:
        return jsonify({"error": "Vendor ID required"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        if target == 'faculty':
            # Collect faculty usernames before deletion so we can unassign from classes
            c.execute("SELECT username FROM system_users WHERE vendor_id = ? AND role = 'faculty'", (vendor_id,))
            faculty_usernames = [r[0] for r in (c.fetchall() or []) if r[0]]

            # Unassign these faculty from all class subject mappings
            _unassign_faculty_from_classes(c, conn, vendor_id, faculty_usernames)

            c.execute("DELETE FROM active_sessions WHERE vendor_id = ? AND username IN (SELECT username FROM system_users WHERE vendor_id = ? AND role = 'faculty')", (vendor_id, vendor_id))

            # Delete linked faces first to maintain integrity (if any)
            c.execute("""
                DELETE FROM faces
                WHERE id IN (SELECT person_id FROM system_users WHERE vendor_id = ? AND role = 'faculty' AND person_id IS NOT NULL)
            """, (vendor_id,))

            c.execute("DELETE FROM system_users WHERE vendor_id = ? AND role = 'faculty'", (vendor_id,))
            message = "All faculty logins and profile data cleared."
        else:
            # 1. Cleanup all related records for this vendor (Students)
            c.execute("DELETE FROM attendance WHERE vendor_id = ?", (vendor_id,))
            c.execute("DELETE FROM student_parents WHERE vendor_id = ?", (vendor_id,))
            c.execute("DELETE FROM leave_requests WHERE vendor_id = ?", (vendor_id,))
            c.execute("DELETE FROM lecture_attendance WHERE vendor_id = ?", (vendor_id,))
            c.execute("DELETE FROM parent_tokens WHERE vendor_id = ?", (vendor_id,))
            c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND NOT EXISTS (SELECT 1 FROM student_parents WHERE parent_id = parent_users.id)", (vendor_id,))
            c.execute("DELETE FROM system_users WHERE vendor_id = ? AND role = 'student'", (vendor_id,))

            # 2. Delete student faces only — preserve faces linked to faculty accounts
            c.execute("""
                DELETE FROM faces WHERE vendor_id = ?
                AND id NOT IN (
                    SELECT person_id FROM system_users
                    WHERE vendor_id = ? AND role = 'faculty' AND person_id IS NOT NULL
                )
            """, (vendor_id, vendor_id))
            # Also scope embeddings to student-only faces
            c.execute("""
                DELETE FROM person_embeddings WHERE vendor_id = ?
                AND person_id NOT IN (
                    SELECT person_id FROM system_users
                    WHERE vendor_id = ? AND role = 'faculty' AND person_id IS NOT NULL
                )
            """, (vendor_id, vendor_id))
            
            # 3. Reset registration configuration as requested
            c.execute("UPDATE bulk_attendance_config SET fields = '[]' WHERE vendor_id = ?", (vendor_id,))
            c.execute("UPDATE vendors SET registration_config = '[]' WHERE id = ?", (vendor_id,))
            message = "All students and configurations cleared."
        
        conn.commit()
        
        cache_delete_vendor_prefix(vendor_id)
        cache_delete("admin_stats")
        
        socketio.emit('persons_updated', {'vendor_id': vendor_id, 'target': target}, room=f"vendor_{vendor_id}")
        socketio.emit('attendance_updated', {'vendor_id': vendor_id}, room=f"vendor_{vendor_id}")
        socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')
        
        return jsonify({"status": "success", "message": message})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@faces_bp.route("/regenerate", methods=["POST"])
@vendor_required
def regenerate_face():
    """
    Identity-Based Restoration API:
    Input: person_id, image (base64 of the blurry crop)
    Output: restored_image (base64)
    """
    data = request.get_json()
    person_id = data.get('person_id')
    target_b64 = data.get('image') # Base64 data URI or raw base64
    fidelity = float(data.get('fidelity', 1.0))
    
    if not person_id or not target_b64:
        return jsonify({"error": "person_id and image are required"}), 400
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT face_image FROM faces WHERE id = ? AND vendor_id = ?", (person_id, request.vendor_id))
    row = c.fetchone()
    conn.close()
    
    if not row or not row[0]:
        return jsonify({"error": "HQ reference image not found for this person"}), 404
        
    ref_b64 = row[0]
    
    try:
        # Decode target image
        import numpy as np
        import cv2

        t_b64 = str(target_b64)
        if ',' in t_b64: t_b64 = t_b64.split(',')[1]
        target_bytes = base64.b64decode(t_b64)
        target_arr = np.frombuffer(target_bytes, dtype=np.uint8)
        target_bgr = cv2.imdecode(target_arr, cv2.IMREAD_COLOR)
        if target_bgr is None:
            return jsonify({"error": "Failed to decode target image"}), 400
        target_rgb = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2RGB)

        # Skip enhancement for already-sharp faces — warping a reference onto a clear
        # face usually makes it look worse, not better.
        _REGEN_BLUR_THRESHOLD = 150.0
        gray_t = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray_t, cv2.CV_64F).var())
        if sharpness >= _REGEN_BLUR_THRESHOLD:
            return jsonify({
                "success": True,
                "image": target_b64,
                "skipped": True,
                "sharpness": round(sharpness, 1),
                "reason": "Face is already sharp — enhancement skipped"
            })
        
        # Decode reference image
        r_b64 = str(ref_b64)
        if ',' in r_b64: r_b64 = r_b64.split(',')[1]
        ref_bytes = base64.b64decode(r_b64)
        ref_arr = np.frombuffer(ref_bytes, dtype=np.uint8)
        ref_bgr = cv2.imdecode(ref_arr, cv2.IMREAD_COLOR)
        if ref_bgr is None:
            return jsonify({"error": "Failed to decode reference image"}), 400
        ref_rgb = cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2RGB)
        
        # Call restoration logic from app.py
        from multiple_face_detection.app import restore_from_reference
        restored_rgb = restore_from_reference(target_rgb, ref_rgb, fidelity=fidelity)
        
        # Encode back to base64
        _, buffer = cv2.imencode('.jpg', cv2.cvtColor(restored_rgb, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        restored_result_b64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            "success": True,
            "image": f"data:image/jpeg;base64,{restored_result_b64}"
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Restoration failed: {str(e)}"}), 500


@faces_bp.route("/persons/wages", methods=["PUT"])
@require_feature("payroll")
def update_wages():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    data = request.json
    updates = data.get("updates", []) # List of {person_id|name, daily_wage, late_allowance_days, late_deduction_amount}

    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        for u in updates:
            pid = u.get('person_id')
            name = u.get('name')
            wage = u.get('daily_wage')
            allowance = u.get('late_allowance_days')
            deduction = u.get('late_deduction_amount')
            
            if pid or name:
                query_parts = []
                params = []
                
                if 'daily_wage' in u and wage is not None and str(wage) != '':
                    query_parts.append("daily_wage = ?")
                    params.append(u['daily_wage'])
                if 'late_allowance_days' in u and allowance is not None and str(allowance) != '':
                    query_parts.append("late_allowance_days = ?")
                    params.append(u['late_allowance_days'])
                if 'late_deduction_amount' in u and deduction is not None and str(deduction) != '':
                    query_parts.append("late_deduction_amount = ?")
                    params.append(u['late_deduction_amount'])
                
                # New fields
                for field in ['basic_salary', 'hra', 'conveyance', 'special_allowance', 'pf_enabled', 'esi_enabled', 'gratuity_enabled', 'professional_tax', 'joining_date']:
                    if field in u and u[field] is not None:
                        # Allow 0 or empty string if it's explicitly passed, though frontend usually sends values
                        query_parts.append(f"{field} = ?")
                        params.append(u[field])
                
                if query_parts:
                    if pid:
                        query_str = f"UPDATE faces SET {', '.join(query_parts)} WHERE id = ?"
                        params.append(pid)
                    else:
                        query_str = f"UPDATE faces SET {', '.join(query_parts)} WHERE name = ?"
                        params.append(name)
                    
                    if vendor_id:
                        query_str += " AND vendor_id = ?"
                        params.append(vendor_id)
                    
                    # logger.info(f"[WAGES] Updating {pid or name}: {query_str} with {params}")
                    c.execute(query_str, params)
                 
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@faces_bp.route("/persons/advances", methods=["POST"])
@require_feature("payroll")
def record_advance():
    from app import get_db_connection
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    data = request.json
    person_id = data.get("person_id")
    amount_cash = data.get("amount_cash", 0)
    amount_online = data.get("amount_online", 0)
    amount = data.get("amount") or (float(amount_cash) + float(amount_online))
    date_str = data.get("date") or datetime.now().strftime('%Y-%m-%d')
    deduction_month = data.get("deduction_month") # e.g. "2023-10"

    if not person_id or (not amount and amount != 0):
        return jsonify({"error": "person_id and amount required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO advances (vendor_id, person_id, amount, amount_cash, amount_online, date, status, deduction_month) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                  (vendor_id, person_id, amount, amount_cash, amount_online, date_str, deduction_month))
        conn.commit()
        return jsonify({"success": True, "id": c.lastrowid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@faces_bp.route("/persons/advances/<int:person_id>", methods=["GET"])
@require_feature("payroll")
def get_person_advances(person_id):
    from app import get_db_connection
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT id, amount, amount_cash, amount_online, date, deduction_month, status, created_at FROM advances WHERE person_id = ? AND vendor_id = ? ORDER BY date DESC", (person_id, vendor_id))
        advances = [dict(row) for row in c.fetchall()]
        return jsonify({"success": True, "advances": advances})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@faces_bp.route("/persons/advances/record/<int:record_id>", methods=["PUT"])
@require_feature("payroll")
def update_advance_record(record_id):
    from app import get_db_connection
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    data = request.json
    amount_cash = data.get("amount_cash")
    amount_online = data.get("amount_online")
    amount = data.get("amount")
    date_str = data.get("date")
    deduction_month = data.get("deduction_month")

    if amount is None and amount_cash is None and amount_online is None:
        return jsonify({"error": "amount, amount_cash or amount_online is required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        query_parts = []
        params = []
        
        if amount is not None:
            query_parts.append("amount = ?")
            params.append(amount)
        if amount_cash is not None:
            query_parts.append("amount_cash = ?")
            params.append(amount_cash)
        if amount_online is not None:
            query_parts.append("amount_online = ?")
            params.append(amount_online)
        if date_str:
            query_parts.append("date = ?")
            params.append(date_str)
        if deduction_month:
            query_parts.append("deduction_month = ?")
            params.append(deduction_month)
            
        params.append(record_id)
        params.append(vendor_id)
        
        c.execute(f"UPDATE advances SET {', '.join(query_parts)} WHERE id = ? AND vendor_id = ?", params)
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@faces_bp.route("/persons/advances/record/<int:record_id>", methods=["DELETE"])
@require_feature("payroll")
def delete_advance_record(record_id):
    from app import get_db_connection
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM advances WHERE id = ? AND vendor_id = ?", (record_id, vendor_id))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
