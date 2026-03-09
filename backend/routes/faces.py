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
from services.auth_service import authenticate_vendor_access, extract_token, verify_token, check_vendor_status
from utils import get_db_connection, LOW_RAM_MODE, _VENDOR_EMB_CACHE, reset_sequence
from services.face_service import _ensure_vendor_emb_cache, _normalize_vec, _suggest_from_cache
from storage import upload_base64_image, presigned_url_for_key, OBJECT_STORAGE_ENABLED
import os
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


def require_feature(feature_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated
    return decorator


def rate_limit(*args, **kwargs):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator

faces_bp = Blueprint('faces_bp', __name__)

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
    from utils import ALL_FEATURES
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
                    # Use a balanced centered box for the thumbnail crop
                    cx1, cy1, cx2, cy2 = mfd_app._compute_centered_box(bx1, by1, bx2, by2, iw, ih, scale=1.8)
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

                        face_only = img_rgb[by1:by2, bx1:bx2]
                        if face_only is None or face_only.size == 0:
                            face_only = pure_face
                        emb = mfd_app.get_embedder().embed(face_only)
                        emb_norm = _normalize_vec(emb)
                        if emb_norm.size > 0:
                            emb_vec_b64 = base64.b64encode(emb_norm.astype(np.float32).tobytes()).decode('ascii')
                        
                        sugg = _suggest_from_cache(emb, vcache, topk=3, struct_vec=struct_vec_val)
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
    from utils import ALL_FEATURES
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT id, name, department, designation, shift, daily_wage, face_image, phone, custom_data FROM faces"
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
    
    persons = []
    for row in rows:
        persons.append(dict(row))
    return jsonify({"persons": persons})


@faces_bp.route("/sync/upload", methods=["POST"])
@require_feature("mobile_app")
def upload_face():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
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
    
    # Extract Custom Data (Dynamic Fields)
    standard_fields = {'person_id', 'name', 'templates', 'face_image', 'phone', 'department', 'designation', 'shift', 'vendor_id'}
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
            max_employees = sub[0] if sub else 50 # Default limit
            
            c.execute("SELECT COUNT(*) FROM faces WHERE vendor_id = ?", (vendor_id,))
            current_count = c.fetchone()[0]
            
            if current_count >= max_employees:
                conn.close()
                return jsonify({"error": f"Employee Limit Reached ({max_employees}). Upgrade your plan."}), 403

        image_url = None
        if face_image and OBJECT_STORAGE_ENABLED:
            try:
                s3_url = upload_base64_image(name or f"face_{datetime.now().timestamp()}", face_image)
                if s3_url:
                    image_url = presigned_url_for_key(s3_url, expires_seconds=3600)
                    face_image = image_url
            except Exception:
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
                
                # If face image or templates are updated, clear accumulated embeddings
                if (face_image is not None and face_image != "") or (templates_list and len(templates_list) > 0) or (templates is not None and templates != ""):
                    try:
                        c.execute("DELETE FROM person_embeddings WHERE person_id = ?", (person_id,))
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
            except Exception:
                pass
        else:
            # Insert New
            to_store_templates = None
            if templates_list and isinstance(templates_list, list) and len(templates_list) > 0:
                to_store_templates = json.dumps(templates_list)
            else:
                to_store_templates = templates or ""
            c.execute("INSERT INTO faces (name, templates, face_image, phone, department, designation, shift, vendor_id, custom_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (name, to_store_templates, face_image, phone or "", department or "", designation or "", shift or "", vendor_id, custom_data))
            new_id = c.lastrowid
            
            # Invalidate cache for new insert as well
            try:
                prefix = f"{int(vendor_id or 0)}_"
                keys_to_delete = [k for k in _VENDOR_EMB_CACHE.keys() if str(k).startswith(prefix)]
                for k in keys_to_delete:
                    del _VENDOR_EMB_CACHE[k]
            except Exception:
                pass

        conn.commit()
        
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
    from utils import ALL_FEATURES
    from services.auth_service import extract_token, verify_token
    vendor_id, error = authenticate_vendor_access()
    if error: return error

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
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
        face_item = {
            "id": row["id"],
            "name": row["name"],
            "templates": row["templates"] if row["templates"] else None,
            "face_image": row["face_image"] if row["face_image"] else None,
            "phone": row["phone"] if "phone" in row.keys() else "",
            "department": row["department"] if "department" in row.keys() else "",
            "designation": row["designation"] if "designation" in row.keys() else "",
            "shift": row["shift"] if "shift" in row.keys() else "",
            "custom_data": json.loads(row["custom_data"]) if "custom_data" in row.keys() and row["custom_data"] else {}
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
    from utils import ALL_FEATURES
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
            c.execute("SELECT id, vendor_id, phone, custom_data FROM faces WHERE name = ? AND vendor_id = ?", (name, vendor_id))
            face_rows = c.fetchall() or []
        else:
            c.execute("SELECT id, vendor_id, phone, custom_data FROM faces WHERE name = ?", (name,))
            face_rows = c.fetchall() or []
        if not face_rows:
            return jsonify({"error": "User not found"}), 404

        if vendor_id:
            c.execute("DELETE FROM faces WHERE name = ? AND vendor_id = ?", (name, vendor_id))
        else:
            c.execute("DELETE FROM faces WHERE name = ?", (name,))
        deleted_faces = c.rowcount

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
    from utils import ALL_FEATURES
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
        # Delete
        if vendor_id:
            c.execute("DELETE FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
        else:
            c.execute("DELETE FROM faces WHERE id = ?", (person_id,))
        deleted_faces = c.rowcount
        try:
            if target_vendor_id:
                c.execute("DELETE FROM attendance WHERE vendor_id = ? AND (person_id = ? OR (person_id IS NULL AND name = ?))", (target_vendor_id, person_id, name))
                c.execute("DELETE FROM student_parents WHERE vendor_id = ? AND person_id = ?", (target_vendor_id, person_id))
                c.execute("UPDATE parent_users SET selected_person_id = NULL WHERE vendor_id = ? AND selected_person_id = ?", (target_vendor_id, person_id))
                c.execute("DELETE FROM parent_users WHERE vendor_id = ? AND selected_person_id = ?", (target_vendor_id, person_id))
                # Delete all embeddings for the deleted person
                c.execute("DELETE FROM person_embeddings WHERE vendor_id = ? AND person_id = ?", (target_vendor_id, person_id))
                # Invalidate embedding cache for this vendor
                for k in list(_VENDOR_EMB_CACHE.keys()):
                    if isinstance(k, (int, str)) and str(k).startswith(str(target_vendor_id)):
                        del _VENDOR_EMB_CACHE[k]
                    elif isinstance(k, tuple) and len(k) > 0 and k[0] == target_vendor_id:
                        del _VENDOR_EMB_CACHE[k]
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
        except Exception:
            pass
        conn.commit()
        
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
                        
                    c.execute(query_str, params)
                 
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
