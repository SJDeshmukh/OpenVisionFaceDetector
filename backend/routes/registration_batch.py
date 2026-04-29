import uuid
import time
import json
import base64
import numpy as np
from flask import Blueprint, request, jsonify, g
from utils import get_db_connection
from services.auth_service import require_auth
from middleware.validation import validate_request
from schemas import (
    RegistrationBatchStartSchema, RegistrationBatchAddSchema, 
    RegistrationBatchStatusSchema, RegistrationBatchCommitSchema
)

registration_batch_bp = Blueprint('registration_batch_bp', __name__)

@registration_batch_bp.route("/registration-batch/start", methods=["POST"])
@require_auth()
@validate_request(RegistrationBatchStartSchema)
def registration_batch_start(valid_data: RegistrationBatchStartSchema):
    vendor_id = g.vendor_id
    bid = str(uuid.uuid4())[:12]
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO registration_batches (id, vendor_id, status) VALUES (?, ?, ?)",
              (bid, vendor_id, 'active'))
    conn.commit()
    conn.close()
    return jsonify({"batch_id": bid})

@registration_batch_bp.route("/registration-batch/add", methods=["POST"])
@require_auth()
@validate_request(RegistrationBatchAddSchema)
def registration_batch_add(valid_data: RegistrationBatchAddSchema):
    vendor_id = g.vendor_id
    bid = valid_data.batch_id
    params = {
        "fast": valid_data.fast,
        "det_max_side": valid_data.det_max_side
    }
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM registration_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "batch not found"}), 404
        
    files = request.files.getlist('images')
    if not files and 'image' in request.files:
        files = [request.files['image']]
    if not files:
        conn.close()
        return jsonify({"error": "no images"}), 400
        
    created = []
    seq_base = int(time.time())
    for idx, f in enumerate(files):
        raw = f.read()
        img_b64 = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')
        item_id = uuid.uuid4().hex[:12]
        c.execute("INSERT INTO registration_batch_items (id, batch_id, seq, image_b64, annotated_b64, faces_json, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (item_id, bid, seq_base + idx, img_b64, '', '[]', 'pending'))
        created.append(item_id)
    conn.commit()
    conn.close()
    
    from celery_app import celery
    if celery:
        from tasks import process_registration_batch_items
        process_registration_batch_items.delay(bid, vendor_id, params)
    else:
        def _worker():
            from tasks import process_registration_batch_items
            try:
                process_registration_batch_items(bid, vendor_id, params)
            except Exception:
                pass
        import threading
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        
    return jsonify({"ok": True, "created": created})

@registration_batch_bp.route("/registration-batch/status", methods=["GET"])
@require_auth()
@validate_request(RegistrationBatchStatusSchema)
def registration_batch_status(valid_data: RegistrationBatchStatusSchema):
    vendor_id = g.vendor_id
    bid = valid_data.batch_id
    exclude_images = request.args.get('exclude_images', '0').lower() in ('1', 'true', 'yes')
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, status FROM registration_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    b = c.fetchone()
    if not b:
        conn.close()
        return jsonify({"error": "batch not found"}), 404
    
    if exclude_images:
        c.execute("SELECT id, seq, faces_json, status FROM registration_batch_items WHERE batch_id = ? ORDER BY seq ASC", (bid,))
        rows = c.fetchall() or []
        items = [{"id": r[0], "seq": r[1], "faces": json.loads(r[2] or "[]"), "status": r[3]} for r in rows]
    else:
        c.execute("SELECT id, seq, image_b64, annotated_b64, faces_json, status FROM registration_batch_items WHERE batch_id = ? ORDER BY seq ASC", (bid,))
        rows = c.fetchall() or []
        items = [{"id": r[0], "seq": r[1], "image": r[2], "annotated": r[3], "faces": json.loads(r[4] or "[]"), "status": r[5]} for r in rows]
    
    conn.close()
    return jsonify({"batch": {"id": b[0], "status": b[1]}, "items": items})

@registration_batch_bp.route("/registration-batch/commit", methods=["POST"])
@require_auth()
@validate_request(RegistrationBatchCommitSchema)
def registration_batch_commit(valid_data: RegistrationBatchCommitSchema):
    vendor_id = g.vendor_id
    bid = valid_data.batch_id
    assigns = valid_data.assignments
    
    conn = get_db_connection()
    # Use DictCursor for both if possible, or handle row mapping
    import sqlite3
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        from multiple_face_detection import app as mfd_app
    except Exception:
        return jsonify({"error": "embedder unavailable"}), 500
        
    saved = 0
    from services.face_service import _normalize_vec, _decode_data_uri_to_rgb, _VENDOR_EMB_CACHE
    from utils import get_face_augmentations
    
    for a in assigns:
        try:
            item_id, face_index = a.item_id, a.face_index
            name = a.name
            if not item_id or not name or face_index is None:
                continue
                
            c.execute("SELECT faces_json FROM registration_batch_items WHERE id = ? AND batch_id = ?", (item_id, bid))
            row = c.fetchone()
            if not row:
                continue
                
            faces = json.loads(row['faces_json'] if hasattr(row, 'keys') else row[0] or '[]')
            face = next((f for f in faces if int(f.get('index', -1)) == int(face_index)), None)
            if not face:
                continue
                
            uri = (face['thumbs'].get('face') if isinstance(face.get('thumbs'), dict) else None) or face.get('thumb')
            if not uri:
                continue
                
            # Check if student exists or create
            phone = a.phone
            student_number = a.student_number
            custom_data = a.custom_data or {}
            if student_number:
                custom_data['student_number'] = student_number
            if a.class_year:
                custom_data['class_year'] = a.class_year
            if a.division:
                custom_data['division'] = a.division
            if a.branch:
                custom_data['branch'] = a.branch
                
            # Try to find existing person by student_number or name+phone
            person_id = None
            if student_number:
                # This is a bit slow in SQLite for large DBs but fine for now
                # This handles both spaced and compact JSON formats
                pattern_compact = f'%"student_number":"{student_number}"%'
                pattern_spaced = f'%"student_number": "{student_number}"%'
                c.execute("SELECT id FROM faces WHERE vendor_id = ? AND (custom_data LIKE ? OR custom_data LIKE ?)", 
                          (vendor_id, pattern_compact, pattern_spaced))
                r = c.fetchone()
                if r:
                    person_id = r[0]
            
            if not person_id:
                # Create new person
                c.execute("""
                    INSERT INTO faces (name, face_image, phone, vendor_id, custom_data) 
                    VALUES (?, ?, ?, ?, ?)
                """, (name, uri, phone, vendor_id, json.dumps(custom_data, separators=(',', ':'))))
                # Extract the last insert ID correctly for both SQLite and PG
                if hasattr(c, 'lastrowid') and c.lastrowid:
                    person_id = c.lastrowid
                else:
                    # In PG, our PostgresCursorWrapper handles RETURNING id and sets lastrowid
                    person_id = c.lastrowid
            else:
                # Update existing person image
                c.execute("UPDATE faces SET face_image = ?, name = ?, phone = ?, custom_data = ? WHERE id = ? AND vendor_id = ?",
                          (uri, name, phone, json.dumps(custom_data, separators=(',', ':')), person_id, vendor_id))

            # Process Embedding
            # uri is the face thumbnail — already a detected+refined crop from the pipeline.
            # Augment the crop directly without re-detecting.
            img_rgb_base = _decode_data_uri_to_rgb(uri)
            all_embs = []
            if img_rgb_base is not None:
                for aug_img in get_face_augmentations(img_rgb_base):
                    emb = mfd_app.get_embedder().embed(aug_img)
                    if emb is not None and emb.size > 0:
                        all_embs.append(_normalize_vec(emb))
            
            if all_embs:
                # Update embedding
                c.execute("DELETE FROM person_embeddings WHERE person_id = ? AND vendor_id = ?", (person_id, vendor_id))
                
                for idx, emb in enumerate(all_embs):
                    vec_blob, dim = emb.astype(np.float32).tobytes(), int(emb.size)
                    
                    # Store structural data only for the primary (original) image
                    struct_blob = None
                    lmks_json = None
                    
                    if idx == 0:
                        struct_vec_b64 = face.get('struct_vec') or ''
                        if struct_vec_b64:
                            try:
                                s_bytes = base64.b64decode(struct_vec_b64)
                                s_emb = np.frombuffer(s_bytes, dtype=np.float32).copy()
                                if s_emb.size > 0:
                                    struct_blob = s_emb.astype(np.float32).tobytes()
                            except Exception:
                                pass
                        landmarks_3d = face.get('landmarks_3d') or []
                        lmks_json = json.dumps(landmarks_3d) if landmarks_3d else None

                    c.execute("""
                        INSERT INTO person_embeddings (vendor_id, person_id, class_year, division, branch, vec, dim, struct_vec, landmarks_3d) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (vendor_id, person_id, a.class_year or "", a.division or "", a.branch or "", vec_blob, dim, struct_blob, lmks_json))

            saved += 1
        except Exception as e:
            print(f"Error committing registration: {e}")
            continue
            
    conn.commit()

    # Schedule async metric projection retrain (debounced 3 s).
    # Batch commits may register 30+ people at once; the debounce means we
    # train once on the complete dataset rather than 30 overlapping times.
    try:
        from metric_learning import schedule_retrain as _sched_retrain
        _sched_retrain(int(vendor_id or 0))
    except Exception:
        pass

    # Invalidate cache for this vendor
    try:
        prefix = f"{int(vendor_id or 0)}_"
        keys_to_delete = [k for k in _VENDOR_EMB_CACHE.keys() if str(k).startswith(prefix)]
        for k in keys_to_delete:
            del _VENDOR_EMB_CACHE[k]
    except Exception:
        pass
    conn.close()
    return jsonify({"ok": True, "saved": saved})

@registration_batch_bp.route("/registration-batch/clear", methods=["POST"])
@require_auth()
def registration_batch_clear():
    vendor_id = g.vendor_id
    bid = (request.get_json(silent=True) or {}).get('batch_id')
    if not bid:
        return jsonify({"error": "batch_id required"}), 400
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM registration_batch_items WHERE batch_id = ?", (bid,))
    c.execute("DELETE FROM registration_batches WHERE id = ? AND vendor_id = ?", (bid, vendor_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
