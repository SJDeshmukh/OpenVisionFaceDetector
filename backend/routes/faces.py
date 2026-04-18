from flask import Blueprint, request, jsonify, send_file
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
from services.auth_service import authenticate_vendor_access, extract_token, verify_token, check_vendor_status, hash_password
import db_factory
from db_factory import set_row_factory
from utils import get_db_connection, LOW_RAM_MODE, _VENDOR_EMB_CACHE, reset_sequence, ALL_FEATURES, cache_delete_vendor_prefix, cache_delete, require_feature, cache_get, cache_set
from services.face_service import _ensure_vendor_emb_cache, _normalize_vec, _suggest_from_cache
from storage import upload_base64_image, presigned_url_for_key, OBJECT_STORAGE_ENABLED, compress_image
import db_factory
from db_factory import set_row_factory
from concurrent.futures import ThreadPoolExecutor
def _extract_structural_vector(lmks):
    if lmks is None or len(lmks) != 68:
        return np.array([], dtype=np.float32)
    left_eye_center = np.mean(lmks[36:42], axis=0)
    right_eye_center = np.mean(lmks[42:48], axis=0)
    interocular_dist = np.linalg.norm(left_eye_center - right_eye_center)
    if interocular_dist < 1e-5: return np.array([], dtype=np.float32)
    
    nose = lmks[33]
    vec = []
    for i in range(68):
        if i == 33: continue 
        d = np.linalg.norm(lmks[i] - nose) / interocular_dist
        vec.append(d)
        
    v = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm > 1e-5:
        v = v / norm
    return v

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
        arr = np.frombuffer(file, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            return jsonify({"error": "invalid image"}), 400
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        try:
            from multiple_face_detection import app as mfd_app
        except Exception:
            # Fallback to current pipeline if import fails
            return jsonify({"error": "multiple_face_detection not available in environment"}), 500
        # Robust defaults aligned with multiple_face_detection UI
        # Accept optional overrides from request JSON
        enhancer = (data.get('enhancer') if 'data' in locals() and isinstance(data, dict) else None) or "GFPGAN"
        crop_mode = (data.get('crop_mode') if 'data' in locals() and isinstance(data, dict) else None) or "Portrait"
        lr = LOW_RAM_MODE
        if lr:
            gfp_up = int((data.get('gfpgan_upscale') if 'data' in locals() and isinstance(data, dict) else None) or 1)
            preclean_whole = bool((data.get('preclean_whole') if 'data' in locals() and isinstance(data, dict) else None) if 'data' in locals() else False)
            preclean_level = float((data.get('preclean_level') if 'data' in locals() and isinstance(data, dict) else None) or 0.2)
        else:
            gfp_up = int((data.get('gfpgan_upscale') if 'data' in locals() and isinstance(data, dict) else None) or 2)
            preclean_whole = bool((data.get('preclean_whole') if 'data' in locals() and isinstance(data, dict) else None) if 'data' in locals() else True)
            preclean_level = float((data.get('preclean_level') if 'data' in locals() and isinstance(data, dict) else None) or 0.4)
        # Redis result cache (optional)
        cache_ttl = int(os.environ.get("DETECT_CACHE_TTL", "300"))
        cache_key = f"detect:v1:{vendor_id}:{enhancer}:{gfp_up}:{crop_mode}:{int(preclean_whole)}:{preclean_level}:{img_hash}"
        redis = _get_redis()
        if redis:
            try:
                cached = redis.get(cache_key)
                if cached:
                    return jsonify(json.loads(cached))
            except Exception:
                pass
        def _heavy_detect():
            return mfd_app.detect_faces(
                image_input=rgb,
                enhancer=enhancer,
                enhance_level=0.5,
                gfpgan_upscale=gfp_up,
                codeformer_w=0.5,
                compute_embeddings=True,
                crop_mode=crop_mode,
                portrait_scale=3.0,
                preclean_whole=preclean_whole,
                preclean_level=preclean_level,
                det_max_side=1280
            )
        if eventlet:
            annotated, crops, df, df_emb = eventlet.tpool.execute(_heavy_detect)
        else:
            fut = _INFER_EXECUTOR.submit(_heavy_detect)
            annotated, crops, df, df_emb = fut.result()
        faces = []
        # Build vendor embedding cache once
        class_year = (data.get('class_year') if 'data' in locals() and isinstance(data, dict) else None)
        division = (data.get('division') if 'data' in locals() and isinstance(data, dict) else None)
        branch = (data.get('branch') if 'data' in locals() and isinstance(data, dict) else None)
        vcache = _ensure_vendor_emb_cache(vendor_id, class_year=class_year, division=division, branch=branch)
        if isinstance(annotated, tuple) and len(annotated) == 2:
            img_rgb, anns = annotated
            draw = cv2.cvtColor(img_rgb.copy(), cv2.COLOR_RGB2BGR)
            for i, (box, score_str) in enumerate(anns or []):
                x1, y1, x2, y2 = [int(v) for v in box]
                cv2.rectangle(draw, (x1, y1), (x2, y2), (0, 180, 255), 2)
                # thumbnails from crops list by index alignment
                if i < len(crops):
                    crop_rgb = crops[i]
                    ih, iw = img_rgb.shape[:2]
                    # Get original face bounding box from df (raw detector output, no padding)
                    if df is not None and hasattr(df, 'iloc') and i < len(df):
                        row = df.iloc[i]
                        bx1, by1, bx2, by2 = int(row['x1']), int(row['y1']), int(row['x2']), int(row['y2'])
                    else:
                        bx1, by1, bx2, by2 = x1, y1, x2, y2
                    # Pure face crop - NO padding, just the detector box
                    bx1 = max(0, bx1); by1 = max(0, by1)
                    bx2 = min(iw, bx2); by2 = min(ih, by2)
                    # Use a balanced centered box for the thumbnail crop (1.2x tight for embedding consistency)
                    cx1, cy1, cx2, cy2 = mfd_app._compute_centered_box(bx1, by1, bx2, by2, iw, ih, scale=1.2)
                    pure_face = img_rgb[cy1:cy2, cx1:cx2]


                    # --- Processing Steps ---
                    
                    # 1. 3DDFA-V3 Landmarks (Now GLOBAL from df)
                    landmarks_3d = []
                    struct_vec_val = None
                    struct_vec_b64 = ""
                    try:
                        if df is not None and hasattr(df, 'iloc') and i < len(df):
                            row = df.iloc[i]
                            if 'landmarks_3d' in row and isinstance(row['landmarks_3d'], list) and len(row['landmarks_3d']) > 0:
                                landmarks_3d = row['landmarks_3d']
                                # Draw on full annotated image (landmarks are now GLOBAL)
                                for pt in landmarks_3d:
                                    dx, dy = int(pt[0]), int(pt[1])
                                    cv2.circle(draw, (dx, dy), 1, (0, 255, 0), -1)
                                
                                if 'struct_vec' in row and isinstance(row['struct_vec'], list) and len(row['struct_vec']) > 0:
                                    struct_vec_val = np.array(row['struct_vec'], dtype=np.float32)
                                    struct_vec_b64 = base64.b64encode(struct_vec_val.tobytes()).decode('ascii')
                    except Exception as e:
                        print(f"[FACES] Landmark integration error: {e}", flush=True)

                    # 2. Enhance pure_face for better thumbnail visibility & 3. Embedding and Suggestions (from enhanced face)
                    emb_vec_b64 = ""
                    sugg = []
                    try:
                        if pure_face.size > 0:
                            lmks_local = None
                            if landmarks_3d:
                                try:
                                    lmks_local = np.array(landmarks_3d).copy()
                                    lmks_local[:, 0] -= cx1
                                    lmks_local[:, 1] -= cy1
                                except Exception:
                                    pass
                            pure_face = mfd_app.get_gfpgan_manager().enhance_crop(pure_face, fidelity=0.9, upscale=2, landmarks=lmks_local)
                            if min(pure_face.shape[:2]) < 512:
                                scale_f = 512.0 / min(pure_face.shape[:2])
                                pure_face = cv2.resize(pure_face, (int(pure_face.shape[1] * scale_f), int(pure_face.shape[0] * scale_f)), interpolation=cv2.INTER_LANCZOS4)

                        # 3. Embedding and Suggestions (from enhanced face)
                        # CRITICAL: Use pure_face (enhanced) to match face_service.py cache logic
                        emb = mfd_app.get_embedder().embed(pure_face)
                        emb_norm = _normalize_vec(emb)
                        if emb_norm.size > 0:
                            emb_vec_b64 = base64.b64encode(emb_norm.astype(np.float32).tobytes()).decode('ascii')
                        
                        sugg = _suggest_from_cache(emb_norm, vcache, topk=3, struct_vec=struct_vec_val)
                    except Exception:
                        pass

                    # 4. Portrait Crop (scale=3.0)
                    port_b64 = ""
                    try:
                        px1, py1, px2, py2 = mfd_app._compute_portrait_box(bx1, by1, bx2, by2, iw, ih, scale=3.0, margin=0.5)
                        portrait = img_rgb[py1:py2, px1:px2]
                        if not lr:
                            portrait = mfd_app.get_gfpgan_manager().enhance_crop(portrait, upscale=gfp_up, whole=True) if portrait.size > 0 else portrait
                        okp, bufp = cv2.imencode('.jpg', cv2.cvtColor(portrait, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if okp:
                            port_b64 = base64.b64encode(bufp.tobytes()).decode('ascii')
                    except Exception:
                        pass

                    # 5. Final Thumbnail Encode and Collect
                    okf, buff = cv2.imencode('.jpg', cv2.cvtColor(pure_face, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
                    face_b64 = base64.b64encode(buff.tobytes()).decode('ascii') if okf else ''

                    faces.append({
                        "index": i,
                        "box": [bx1, by1, bx2, by2],
                        "score": float(score_str) if score_str else None,
                        "thumbs": {
                            "face": f"data:image/jpeg;base64,{face_b64}" if face_b64 else None,
                            "portrait": f"data:image/jpeg;base64,{port_b64}" if port_b64 else None
                        },
                        "suggestions": sugg,
                        "emb_vec": emb_vec_b64,
                        "struct_vec": struct_vec_b64,
                        "landmarks_3d": landmarks_3d
                    })

            ok2, ann = cv2.imencode('.jpg', draw, [cv2.IMWRITE_JPEG_QUALITY, 85])
            annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(ann.tobytes()).decode('ascii')}" if ok2 else ''
        else:
            annotated_b64 = ''
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
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
        
    # Optional pagination
    try:
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params += [limit, offset]
    except:
        pass
    try:
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        conn.close()
        return jsonify({"error": f"PostgreSQL Fetch Error: {str(e)}", "query": query, "params": str(params)}), 500
    
    persons = []
    for row in rows:
        persons.append(dict(row))
    
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
        'landmarks_3d', 'landmarks_3d_list', 'struct_vec', 'struct_vec_list',
        'class_year', 'division', 'branch'
    }
    custom_dict = {k: v for k, v in data.items() if k not in standard_fields}
    custom_data = json.dumps(custom_dict) if custom_dict else None

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
            student_number = str(custom_dict.get('student_number') or custom_dict.get('roll_number') or custom_dict.get('admission_number') or '').strip()
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
                    sn = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip()
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
                            student_number_for_parent = str(cd_obj.get("student_number") or cd_obj.get("roll_number") or cd_obj.get("admission_number") or "").strip()
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
                        old_sid = str(cd_old_obj.get("student_number") or cd_old_obj.get("roll_number") or cd_old_obj.get("admission_number") or "").strip()
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
                    student_id = str(cd_obj.get("student_number") or cd_obj.get("roll_number") or cd_obj.get("admission_number") or "").strip()
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
    
    query = "SELECT * FROM faces"
    params = []
    
    if vendor_id:
        query += " WHERE vendor_id = ?"
        params.append(vendor_id)
        
    # Optional pagination
    try:
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params += [limit, offset]
    except:
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
                    c_data = r[3]
                    if c_data:
                        cd = json.loads(c_data) if isinstance(c_data, str) else c_data
                        if isinstance(cd, dict):
                            sn = str(cd.get("student_number") or cd.get("roll_number") or cd.get("admission_number") or "").strip()
                except Exception:
                    sn = None
                if sn:
                    student_numbers_by_vendor.setdefault(int(vid), set()).add(sn)
                try:
                    ph = r[2]
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
                    f"DELETE FROM parent_users WHERE vendor_id = ? AND selected_person_id IN ({placeholders})",
                    [vid, *ids],
                )
                # Delete all embeddings for the deleted person(s)
                c.execute(
                    f"DELETE FROM person_embeddings WHERE vendor_id = ? AND person_id IN ({placeholders})",
                    [vid, *ids],
                )
                # Invalidate embedding cache for this vendor
                for k in list(_VENDOR_EMB_CACHE.keys()):
                    if isinstance(k, (int, str)) and str(k).startswith(str(vid)):
                        del _VENDOR_EMB_CACHE[k]
                    elif isinstance(k, tuple) and len(k) > 0 and k[0] == vid:
                        del _VENDOR_EMB_CACHE[k]
                for sn in sorted(student_numbers_by_vendor.get(int(vid), set())):
                    c.execute("DELETE FROM parent_tokens WHERE vendor_id = ? AND student_number = ?", (vid, sn))
                    c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND student_number = ?", (vid, sn))
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
                        c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND contact_phone = ?", (vid, ph))
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
                    sn = str(cd.get("student_number") or cd.get("roll_number") or cd.get("admission_number") or "").strip()
        except Exception:
            sn = None
        # Get display_id and vendor_id for re-indexing
        c.execute("SELECT display_id, vendor_id FROM faces WHERE id = ?", (person_id,))
        del_row = c.fetchone()
        deleted_display_id = del_row[0] if del_row else None
        target_vendor_id = del_row[1] if del_row else None

        # 1. Cleanup related records FIRST to avoid FK violations in PostgreSQL
        import logging
        logger = logging.getLogger(__name__)
        try:
            # Cleanup using person_id (which is a unique PK for the face)
            logger.info(f"Cleaning up associated records for person_id={person_id}")
            
            c.execute("DELETE FROM attendance WHERE person_id = ?", (person_id,))
            c.execute("DELETE FROM student_parents WHERE person_id = ?", (person_id,))
            c.execute("UPDATE parent_users SET selected_person_id = NULL WHERE selected_person_id = ?", (person_id,))
            c.execute("DELETE FROM parent_users WHERE selected_person_id = ?", (person_id,))
            
            # Cleanup leave requests and system users associated with this person
            c.execute("DELETE FROM leave_requests WHERE student_id = ?", (person_id,))
            c.execute("DELETE FROM system_users WHERE person_id = ?", (person_id,))
            if sn:
                c.execute("DELETE FROM system_users WHERE username = ?", (sn,))
            
            # Delete all embeddings for the deleted person
            c.execute("DELETE FROM person_embeddings WHERE person_id = ?", (person_id,))
            
            logger.info("Cleanup successful for person_id=%s", person_id)
        except Exception as cleanup_err:
            logger.error(f"Cleanup failed for person_id={person_id}: {cleanup_err}")

        try:
            for k in list(_VENDOR_EMB_CACHE.keys()):
                if isinstance(k, (int, str)) and str(k).startswith(str(target_vendor_id)):
                    del _VENDOR_EMB_CACHE[k]
                elif isinstance(k, tuple) and len(k) > 0 and k[0] == target_vendor_id:
                    del _VENDOR_EMB_CACHE[k]
            
            c.execute("DELETE FROM lecture_attendance WHERE person_id = ?", (person_id,))
            c.execute("DELETE FROM person_embeddings WHERE person_id = ?", (person_id,))
            
            if sn:
                c.execute("DELETE FROM parent_tokens WHERE vendor_id = ? AND student_number = ?", (target_vendor_id, sn))
                c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND student_number = ?", (target_vendor_id, sn))
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
                    c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND contact_phone = ?", (target_vendor_id, str(phone).strip()))
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error cleaning up relations for face {person_id}: {e}")

        # 2. Finally delete the face record
        if vendor_id:
            c.execute("DELETE FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        else:
            c.execute("DELETE FROM faces WHERE id = ?", (person_id,))
        deleted_faces = c.rowcount

        # 3. Re-index remaining faces for this vendor
        if deleted_faces > 0 and target_vendor_id is not None:
            reindex_vendor_faces(conn, target_vendor_id)

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
