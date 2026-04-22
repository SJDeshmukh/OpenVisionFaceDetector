import uuid
import time
import json
import base64
import numpy as np
import threading
from flask import Blueprint, request, jsonify
from utils import (
    get_db_connection, _ensure_class_batch_tables, 
    _VENDOR_EMB_CACHE, decode_image_to_bgr
)
import cv2
from services.face_service import (
    _normalize_vec, _decode_data_uri_to_rgb, _ensure_vendor_emb_cache, _suggest_from_cache
)
from services.auth_service import require_auth
from middleware.validation import validate_request
from schemas import (
    ClassBatchStartSchema, ClassBatchAddSchema, 
    ClassBatchCommitSchema, ClassBatchStatusSchema
)
from flask import Blueprint, request, jsonify, g

attendance_class_bp = Blueprint('attendance_class_bp', __name__)

@attendance_class_bp.route("/class-batch/start", methods=["POST"])
@require_auth()
@validate_request(ClassBatchStartSchema)
def class_batch_start(valid_data: ClassBatchStartSchema):
    vendor_id = g.vendor_id
    bid = str(uuid.uuid4())[:12]
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("INSERT INTO class_batches (id, vendor_id, class_year, division, branch, status) VALUES (?, ?, ?, ?, ?, ?)",
              (bid, vendor_id, valid_data.class_year, valid_data.division, valid_data.branch, 'active'))
    conn.commit(); conn.close()
    return jsonify({"batch_id": bid})

@attendance_class_bp.route("/class-batch/add", methods=["POST"])
@require_auth()
@validate_request(ClassBatchAddSchema)
def class_batch_add(valid_data: ClassBatchAddSchema):
    vendor_id = g.vendor_id
    bid = valid_data.batch_id
    params = {
        "class_year": valid_data.class_year,
        "division": valid_data.division,
        "branch": valid_data.branch,
        "fast": valid_data.fast,
        "det_max_side": valid_data.det_max_side
    }
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    if not c.fetchone():
        conn.close(); return jsonify({"error": "batch not found"}), 404
    files = request.files.getlist('images')
    if not files and 'image' in request.files: files = [request.files['image']]
    if not files: conn.close(); return jsonify({"error": "no images"}), 400
    created = []
    seq_base = int(time.time())
    _t_upload_total = time.time()
    for idx, f in enumerate(files):
        _t_img = time.time()
        raw = f.read()
        raw_kb = len(raw) / 1024
        # Ensure image is in a browser-supported format (convert HEIC/etc to JPEG)
        _t_decode = time.time()
        bgr = decode_image_to_bgr(raw)
        if bgr is not None:
            ok, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                img_b64 = 'data:image/jpeg;base64,' + base64.b64encode(buf).decode('ascii')
            else:
                img_b64 = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')
        else:
            img_b64 = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')
            
        _t_encode_done = time.time()
        item_id = uuid.uuid4().hex[:12]
        _t_db = time.time()
        c.execute("INSERT INTO class_batch_items (id, batch_id, seq, image_b64, annotated_b64, faces_json, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (item_id, bid, seq_base + idx, img_b64, '', '[]', 'pending'))
        created.append(item_id)
        _decode_ms = (_t_encode_done - _t_decode) * 1000
        _db_ms     = (time.time() - _t_db) * 1000
        _total_ms  = (time.time() - _t_img) * 1000
        import logging as _lg
        _lg.getLogger(__name__).info(
            f"[UPLOAD_TIMING] img={idx} size={raw_kb:.0f}KB "
            f"decode={_decode_ms:.0f}ms db_write={_db_ms:.0f}ms total={_total_ms:.0f}ms"
        )
    _all_ms = (time.time() - _t_upload_total) * 1000
    import logging as _lg2
    _lg2.getLogger(__name__).info(
        f"[UPLOAD_TIMING] {len(files)} images stored in {_all_ms:.0f}ms total"
    )
    conn.commit(); conn.close()
    
    import threading, logging as _log
    _dispatched = False
    try:
        from celery_app import celery
        if celery:
            from tasks import process_class_batch_items
            process_class_batch_items.delay(bid, vendor_id, params)
            _dispatched = True
            _log.getLogger(__name__).info(f"[CELERY] Task dispatched for batch {bid}")
    except Exception as _ce:
        _log.getLogger(__name__).warning(f"[CELERY] Dispatch failed ({_ce}), falling back to thread")

    if not _dispatched:
        def _worker():
            try:
                from tasks import process_class_batch_items
                _log.getLogger(__name__).info(f"[THREAD] Starting process for batch {bid}")
                process_class_batch_items(bid, vendor_id, params)
                _log.getLogger(__name__).info(f"[THREAD] Finished batch {bid}")
            except Exception as _e:
                _log.getLogger(__name__).error(f"[THREAD] process_class_batch_items failed: {_e}", exc_info=True)
        t = threading.Thread(target=_worker, daemon=False)
        t.start()
    return jsonify({"ok": True, "created": created})

@attendance_class_bp.route("/class-batch/add-inferred", methods=["POST"])
@require_auth()
def class_batch_add_inferred():
    vendor_id = g.vendor_id
    data = request.get_json(silent=True) or {}
    bid = data.get('batch_id')
    items_data = data.get('items') or []
    if not bid: return jsonify({"error": "batch_id required"}), 400
    if not items_data: return jsonify({"error": "No items provided"}), 400
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id, class_year, division, branch FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    batch_row = c.fetchone()
    if not batch_row: conn.close(); return jsonify({"error": "batch not found"}), 404
    class_year, division, branch = batch_row[1], batch_row[2], batch_row[3]
    vcache = _ensure_vendor_emb_cache(vendor_id, class_year=class_year, division=division, branch=branch)
    created_ids = []
    for item in items_data:
        image_b64 = item.get('image_b64')
        # Ensure image is in a browser-supported format
        header, encoded = image_b64.split(',', 1) if ',' in image_b64 else ('', image_b64)
        raw = base64.b64decode(encoded)
        bgr = decode_image_to_bgr(raw)
        if bgr is not None:
            ok, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                image_b64 = 'data:image/jpeg;base64,' + base64.b64encode(buf).decode('ascii')
        
        faces_inferred = item.get('faces') or []
        seq = item.get('seq') or int(time.time())
        item_id = uuid.uuid4().hex[:12]
        processed_faces = []
        for f in faces_inferred:
            emb = f.get('embedding')
            if emb and len(emb) > 0:
                vec = np.array(emb, dtype=np.float32)
                suggestions = _suggest_from_cache(vec, vcache, topk=3, class_year=class_year, division=division, branch=branch)
                f['suggestions'] = suggestions
                f['emb_vec'] = base64.b64encode(vec.tobytes()).decode('ascii')
            processed_faces.append(f)
        faces_json = json.dumps(processed_faces)
        c.execute("INSERT INTO class_batch_items (id, batch_id, seq, image_b64, annotated_b64, faces_json, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (item_id, bid, seq, image_b64, '', faces_json, 'done'))
        created_ids.append(item_id)
    conn.commit(); conn.close()
    return jsonify({"ok": True, "created": created_ids})

@attendance_class_bp.route("/class-batch/commit", methods=["POST"])
@require_auth()
@validate_request(ClassBatchCommitSchema)
def class_batch_commit(valid_data: ClassBatchCommitSchema):
    vendor_id = g.vendor_id
    bid = valid_data.batch_id
    assigns = valid_data.assignments
    class_year, division, branch = valid_data.class_year, valid_data.division, valid_data.branch
    threshold = valid_data.threshold
    
    conn = get_db_connection()
    import sqlite3
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if threshold is not None:
        try:
            c.execute("INSERT INTO class_thresholds (vendor_id, class_year, division, branch, threshold) VALUES (?, ?, ?, ?, ?) ON CONFLICT(vendor_id, class_year, division, branch) DO UPDATE SET threshold=excluded.threshold, updated_at=CURRENT_TIMESTAMP", (vendor_id, str(class_year), str(division), str(branch), float(threshold)))
            conn.commit()
        except Exception: pass
    try: from multiple_face_detection import app as mfd_app
    except Exception: return jsonify({"error": "embedder unavailable"}), 500
    saved = 0
    person_name_cache = {}
    # Track which persons had their old embeddings cleared in this session.
    # On first encounter of a person, clear ALL their previous embeddings so this
    # batch fully replaces the prior registration. On subsequent encounters of the
    # same person within the same batch, just INSERT (accumulate multiple views).
    _cleared_persons = set()
    for a in assigns:
        try:
            item_id, face_index, person_id = a.item_id, a.face_index, a.person_id
            if not item_id or person_id in (None, '', 0) or face_index is None: continue
            c.execute("SELECT faces_json FROM class_batch_items WHERE id = ? AND batch_id = ?", (item_id, bid))
            row = c.fetchone()
            if not row: continue
            faces = json.loads(row['faces_json'] if isinstance(row, sqlite3.Row) else row[0] or '[]')
            face = next((f for f in faces if int(f.get('index', -1)) == int(face_index)), None)
            if not face: continue
            uri = (face['thumbs'].get('face') if isinstance(face.get('thumbs'), dict) else None) or face.get('thumb')
            if not uri: continue
            emb_vec_b64 = face.get('emb_vec') or ''
            if emb_vec_b64:
                try:
                    raw_bytes = base64.b64decode(emb_vec_b64)
                    emb = np.frombuffer(raw_bytes, dtype=np.float32).copy()
                    emb = _normalize_vec(emb)
                except Exception: emb = None
            else: emb = None
            if emb is None or emb.size == 0:
                img_rgb = _decode_data_uri_to_rgb(uri)
                if img_rgb is None: continue
                emb = mfd_app.get_embedder().embed(img_rgb)
                emb = _normalize_vec(emb)
            if emb is None or emb.size == 0: continue
            vec_blob, dim = emb.astype(np.float32).tobytes(), int(emb.size)
            pid_key = int(person_id)
            if pid_key not in person_name_cache:
                c.execute("SELECT name FROM faces WHERE id = ? AND vendor_id = ?", (pid_key, vendor_id))
                rname = c.fetchone()
                person_name_cache[pid_key] = (rname['name'] if isinstance(rname, sqlite3.Row) else (rname[0] if rname else '')) if rname else ''
            assigned_name = person_name_cache.get(pid_key, '')
            face['assigned_person_id'], face['assigned_name'] = int(person_id), assigned_name
            c.execute("UPDATE class_batch_items SET faces_json = ? WHERE id = ? AND batch_id = ?", (json.dumps(faces), item_id, bid))
            struct_vec_b64, landmarks_3d = face.get('struct_vec') or '', face.get('landmarks_3d') or []
            struct_blob = None
            if struct_vec_b64:
                try:
                    s_bytes = base64.b64decode(struct_vec_b64); s_emb = np.frombuffer(s_bytes, dtype=np.float32).copy()
                    if s_emb.size > 0: struct_blob = s_emb.astype(np.float32).tobytes()
                except Exception: pass
            lmks_json = json.dumps(landmarks_3d) if landmarks_3d else None

            # First time we see this person in the commit: replace ALL their old embeddings
            # so this session's photos become the authoritative registration set.
            if pid_key not in _cleared_persons:
                c.execute("DELETE FROM person_embeddings WHERE person_id = ? AND vendor_id = ?", (pid_key, vendor_id))
                _cleared_persons.add(pid_key)

            # INSERT: accumulates multiple face embeddings per person within this batch
            c.execute("INSERT INTO person_embeddings (vendor_id, person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (vendor_id, int(person_id), str(class_year), str(division), str(branch), vec_blob, dim, struct_blob, lmks_json))
            
            # Update the main student profile image with this "labeling" crop if they don't have one,
            # or to ensure the People Management UI shows the image used for this session.
            if uri:
                c.execute("UPDATE faces SET face_image = ? WHERE id = ? AND vendor_id = ?", (uri, pid_key, vendor_id))

            saved += 1
        except Exception: continue
    conn.commit()
    try:
        prefix = f"{int(vendor_id or 0)}_"
        keys_to_delete = [k for k in _VENDOR_EMB_CACHE.keys() if str(k).startswith(prefix)]
        for k in keys_to_delete: del _VENDOR_EMB_CACHE[k]
    except Exception: pass
    conn.close()
    return jsonify({"ok": True, "saved": saved})

@attendance_class_bp.route("/class-batch/status", methods=["GET"])
@require_auth()
@validate_request(ClassBatchStatusSchema)
def class_batch_status(valid_data: ClassBatchStatusSchema):
    vendor_id = g.vendor_id
    bid = valid_data.batch_id
    exclude_images = request.args.get('exclude_images', '0').lower() in ('1', 'true', 'yes')
    
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id, class_year, division, branch, status FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    b = c.fetchone()
    if not b: conn.close(); return jsonify({"error": "batch not found"}), 404
    
    if exclude_images:
        c.execute("SELECT id, seq, faces_json, status FROM class_batch_items WHERE batch_id = ? ORDER BY seq ASC", (bid,))
        rows = c.fetchall() or []
        conn.close()
        items = [{"id": r[0], "seq": r[1], "faces": json.loads(r[2] or "[]"), "status": r[3]} for r in rows]
    else:
        c.execute("SELECT id, seq, image_b64, annotated_b64, faces_json, status FROM class_batch_items WHERE batch_id = ? ORDER BY seq ASC", (bid,))
        rows = c.fetchall() or []
        conn.close()
        items = [{"id": r[0], "seq": r[1], "image": r[2], "annotated": r[3], "faces": json.loads(r[4] or "[]"), "status": r[5]} for r in rows]
        
    return jsonify({"batch": {"id": b[0], "class_year": b[1], "division": b[2], "branch": b[3], "status": b[4]}, "items": items})

@attendance_class_bp.route("/class-batch/item-image/<item_id>", methods=["GET"])
def class_batch_item_image(item_id):
    # Support token in query params for <img> tags
    token = request.args.get('token')
    if token:
        # Manually verify token or just use it if provided
        # For simplicity and consistency, let's try to populate g.vendor_id
        from services.auth_service import verify_token
        user_data = verify_token(token)
        if not user_data:
            return jsonify({"error": "unauthorized"}), 401
        vendor_id = user_data.get('vendor_id')
    else:
        # Fallback to standard require_auth logic (implicit)
        @require_auth()
        def _protected():
            return g.vendor_id
        try:
            vendor_id = _protected()
            if isinstance(vendor_id, tuple): # error response
                return vendor_id
        except Exception:
            return jsonify({"error": "unauthorized"}), 401

    image_type = request.args.get('type', 'raw') # 'raw' or 'annotated'
    
    conn = get_db_connection()
    _ensure_class_batch_tables(conn)
    c = conn.cursor()
    
    # Verify that the item belongs to a batch owned by this vendor
    c.execute("""
        SELECT i.image_b64, i.annotated_b64 
        FROM class_batch_items i
        JOIN class_batches b ON i.batch_id = b.id
        WHERE i.id = ? AND b.vendor_id = ?
    """, (item_id, vendor_id))
    
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "item not found"}), 404
        
    img_b64 = row[1] if image_type == 'annotated' else row[0]
    
    if not img_b64:
        return jsonify({"error": "image not available"}), 404
        
    # If it's a data URI, strip the header
    if ',' in img_b64:
        header, encoded = img_b64.split(',', 1)
        mime_type = header.split(':')[1].split(';')[0]
        raw_data = base64.b64decode(encoded)
    else:
        mime_type = "image/jpeg"
        raw_data = base64.b64decode(img_b64)
        
    from flask import Response
    return Response(raw_data, mimetype=mime_type)

@attendance_class_bp.route("/class-batch/clear", methods=["POST"])
@require_auth()
def class_batch_clear():
    vendor_id = g.vendor_id
    bid = (request.get_json(silent=True) or {}).get('batch_id')
    if not bid: return jsonify({"error": "batch_id required"}), 400
    conn = get_db_connection(); _ensure_class_batch_tables(conn); c = conn.cursor()
    c.execute("DELETE FROM class_batch_items WHERE batch_id = ?", (bid,))
    c.execute("DELETE FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@attendance_class_bp.route("/class-batch/refresh", methods=["POST"])
@require_auth()
def class_batch_refresh():
    vendor_id = g.vendor_id
    data = request.get_json(silent=True) or {}
    bid = data.get('batch_id')
    if not bid: return jsonify({"error": "batch_id required"}), 400
    conn = get_db_connection(); _ensure_class_batch_tables(conn); c = conn.cursor()
    c.execute("SELECT id, vendor_id, class_year, division, branch FROM class_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    row = c.fetchone()
    if not row: conn.close(); return jsonify({"error": "batch not found"}), 404
    params = {"class_year": str(row[2] or ""), "division": str(row[3] or ""), "branch": str(row[4] or "")}
    try:
        if 'fast' in data: params["fast"] = bool(data.get('fast'))
        if 'det_max_side' in data and data.get('det_max_side') is not None: params["det_max_side"] = int(data.get('det_max_side'))
    except Exception: pass
    conn.close()
    from tasks import refresh_class_batch_items
    refresh_class_batch_items.delay(bid, vendor_id, params)
    return jsonify({"ok": True})
