from __future__ import annotations
import numpy as np
import cv2
import base64
import time
import sqlite3
from threading import Lock

# Local imports to avoid circular dependencies where needed
# In a real refactor, these caches should probably live here.

from utils import get_db_connection, _VENDOR_EMB_CACHE, _now_ts, USE_FAISS, _faiss, _FAISS_LOCK, LOW_RAM_MODE

def get_realtime_engine():
    from app import get_realtime_engine as _get
    return _get()

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

def _normalize_vec(v: np.ndarray) -> np.ndarray:
    if v is None or v.size == 0:
        return np.zeros((0,), dtype=np.float32)
    v = v.astype(np.float32)
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n <= 1e-12:
        return v
    return (v / n).astype(np.float32)

def _decode_data_uri_to_rgb(uri: str):
    try:
        if not uri:
            return None
        if uri.startswith('data:'):
            b64 = uri.split(',', 1)[1] if ',' in uri else ''
            raw = base64.b64decode(b64)
        else:
            raw = base64.b64decode(uri)
        arr = np.frombuffer(raw, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return None

def _ensure_vendor_emb_cache(vendor_id: int, ttl_sec: int = 300, class_year: str | None = None, division: str | None = None, branch: str | None = None):
    try:
        class_y = str(class_year or "")
        div = str(division or "")
        br = str(branch or "")
        key = f"{vendor_id}_{class_y}_{div}_{br}"
        
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Fast multi-process staleness check
        try:
            c.execute("SELECT MAX(id), COUNT(id) FROM person_embeddings WHERE vendor_id = ?", (int(vendor_id or 0),))
            sig_row = c.fetchone()
            current_sig = f"{sig_row[0]}_{sig_row[1]}" if sig_row and sig_row[0] is not None else "0_0"
        except Exception:
            current_sig = "0_0"

        ent = _VENDOR_EMB_CACHE.get(key)
        if ent and ent.get('sig') == current_sig and (_now_ts() - ent.get('ts', 0.0)) < ttl_sec and ent.get('items'):
            conn.close()
            return ent
            
        from multiple_face_detection import app as mfd_app
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS person_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER,
                person_id INTEGER,
                class_year TEXT,
                division TEXT,
                branch TEXT,
                vec BLOB,
                dim INTEGER,
                struct_vec BLOB,
                landmarks_3d TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_person_embeddings_vid ON person_embeddings(vendor_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_person_embeddings_classes ON person_embeddings(class_year, division, branch)")
            
            # Migration: drop old UNIQUE constraint if present
            try:
                c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='person_embeddings'")
                trow = c.fetchone()
                if trow:
                    tsql = trow[0] if isinstance(trow, (list, tuple)) else trow['sql']
                    if tsql and 'UNIQUE' in str(tsql):
                        c.execute("ALTER TABLE person_embeddings RENAME TO _person_embeddings_old")
                        c.execute("""CREATE TABLE person_embeddings (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            vendor_id INTEGER,
                            person_id INTEGER,
                            class_year TEXT,
                            division TEXT,
                            branch TEXT,
                            vec BLOB,
                            dim INTEGER,
                            struct_vec BLOB,
                            landmarks_3d TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )""")
                        # Need exact column mapping since struct_vec/landmarks_3d may not exist
                        try:
                            c.execute("INSERT INTO person_embeddings (id, vendor_id, person_id, class_year, division, branch, vec, dim, created_at) SELECT id, vendor_id, person_id, class_year, division, branch, vec, dim, created_at FROM _person_embeddings_old")
                        except Exception:
                            c.execute("INSERT INTO person_embeddings SELECT * FROM _person_embeddings_old")
                        c.execute("DROP TABLE _person_embeddings_old")
                        conn.commit()
                    elif tsql and 'struct_vec' not in str(tsql):
                        c.execute("ALTER TABLE person_embeddings ADD COLUMN struct_vec BLOB")
                        try: c.execute("ALTER TABLE person_embeddings ADD COLUMN landmarks_3d TEXT")
                        except Exception: pass
                        conn.commit()
            except Exception:
                pass
        except Exception:
            pass
        items = []
        try:
            q = "SELECT person_id, vec, dim, struct_vec FROM person_embeddings WHERE vendor_id = ?"
            args = [int(vendor_id or 0)]
            if class_year:
                q += " AND (class_year = ?)"
                args.append(str(class_year))
            if division:
                q += " AND (division = ?)"
                args.append(str(division))
            if branch:
                q += " AND (branch = ?)"
                args.append(str(branch))
            c.execute(q, args)
            rows_emb = c.fetchall() or []
            id_set = set()
            for r in rows_emb:
                try:
                    pid = int(r['person_id'] if isinstance(r, sqlite3.Row) else r[0])
                    vb = r['vec'] if isinstance(r, sqlite3.Row) else r[1]
                    dim = int(r['dim'] if isinstance(r, sqlite3.Row) else r[2])
                    sb = r['struct_vec'] if isinstance(r, sqlite3.Row) else r[3]
                    s_vec = None
                    if sb:
                        sd = np.frombuffer(sb, dtype=np.float32)
                        if sd.size > 0:
                            s_vec = sd
                            
                    if vb and dim > 0:
                        v = np.frombuffer(vb, dtype=np.float32)
                        if v.size == dim:
                            v = _normalize_vec(v)
                            items.append({'person_id': pid, 'name': '', 'vec': v, 'struct_vec': s_vec})
                            id_set.add(pid)
                except Exception:
                    continue
            if id_set:
                pid_list = list(id_set)
                ph = ",".join(["?"] * len(pid_list))
                try:
                    c.execute(f"SELECT id, name FROM faces WHERE id IN ({ph})", pid_list)
                    nmrows = c.fetchall() or []
                    nmap = {}
                    for nr in nmrows:
                        nid = nr['id'] if isinstance(nr, sqlite3.Row) else nr[0]
                        nmap[int(nid)] = nr['name'] if isinstance(nr, sqlite3.Row) else nr[1]
                    for it in items:
                        it['name'] = nmap.get(it['person_id'], '')
                except Exception:
                    pass
        except Exception:
            pass
        c.execute("PRAGMA table_info(faces)")
        cols = [r[1] if isinstance(r, (list, tuple)) else r['name'] for r in c.fetchall() or []]
        face_img_col = 'face_image'
        has_face_img = face_img_col in cols
        # Build set of person_ids that already have pre-computed embeddings
        emb_pid_set = set(it['person_id'] for it in items)
        # Load people from faces table if face_image column exists, skipping those with pre-computed embeddings
        if has_face_img:
            base_query = f"SELECT id, name, {face_img_col}, department, custom_data FROM faces"
            params = []
            where = []
            if vendor_id:
                where.append("vendor_id = ?"); params.append(vendor_id)
            if class_year:
                where.append("(custom_data LIKE ?)")
                params.append(f'%\"class_year\":\"{class_year}\"%')
            if division:
                where.append("(custom_data LIKE ?)")
                params.append(f'%\"division\":\"{division}\"%')
            if branch:
                where.append("(custom_data LIKE ?)")
                params.append(f'%\"branch\":\"{branch}\"%')
            if where:
                base_query += " WHERE " + " AND ".join(where)
            c.execute(base_query, params)
            rows = c.fetchall() or []
            conn.close()
            for r in rows:
                try:
                    pid = int(r['id'] if isinstance(r, sqlite3.Row) else r[0])
                    if pid in emb_pid_set:
                        continue  # already have pre-computed embedding
                    nm = r['name'] if isinstance(r, sqlite3.Row) else r[1]
                    uri = r[face_img_col] if isinstance(r, sqlite3.Row) else r[2]
                    img_rgb = _decode_data_uri_to_rgb(uri)
                    if img_rgb is None:
                        continue
                    try:
                        det_ann, det_crops, _, _ = mfd_app.detect_faces(
                            image_input=img_rgb,
                            enhancer="GFPGAN",
                            enhance_level=0.5,
                            gfpgan_upscale=1,
                            codeformer_w=0.5,
                            compute_embeddings=False,
                            crop_mode="Portrait",
                            portrait_scale=3.0,
                            preclean_whole=False,
                            preclean_level=0.2,
                            det_max_side=640
                        )
                        crop = det_crops[0] if (isinstance(det_crops, list) and len(det_crops) > 0) else img_rgb
                    except Exception:
                        crop = img_rgb
                    emb = mfd_app.get_embedder().embed(crop)
                    emb = _normalize_vec(emb)
                    if emb.size > 0:
                        items.append({'person_id': int(pid), 'name': str(nm), 'vec': emb})
                except Exception:
                    continue
        _VENDOR_EMB_CACHE[key] = {'ts': _now_ts(), 'sig': current_sig, 'items': items, 'dim': (items[0]['vec'].size if items else 0)}
        if USE_FAISS and items and _VENDOR_EMB_CACHE[key]['dim'] > 0:
            try:
                dim = _VENDOR_EMB_CACHE[key]['dim']
                xb = np.vstack([it['vec'] for it in items]).astype(np.float32)
                index = _faiss.IndexFlatIP(dim)
                if _FAISS_LOCK:
                    with _FAISS_LOCK:
                        index.add(xb)
                else:
                    index.add(xb)
                _VENDOR_EMB_CACHE[key]['faiss_index'] = index
                _VENDOR_EMB_CACHE[key]['faiss_map'] = [(it['person_id'], it.get('name', '')) for it in items]
            except Exception:
                pass
        if LOW_RAM_MODE:
            try:
                max_items = int(os.environ.get("EMB_CACHE_MAX_ITEMS", "200") or "200")
            except Exception:
                max_items = 200
            _VENDOR_EMB_CACHE[key]['items'] = _VENDOR_EMB_CACHE[key]['items'][:max_items]
            try:
                max_vendors = int(os.environ.get("EMB_CACHE_MAX_VENDORS", "20") or "20")
            except Exception:
                max_vendors = 20
            if len(_VENDOR_EMB_CACHE) > max_vendors:
                ks = sorted(_VENDOR_EMB_CACHE.items(), key=lambda kv: kv[1].get('ts', 0.0))
                for kdrop, _ in ks[:-max_vendors]:
                    try:
                        del _VENDOR_EMB_CACHE[kdrop]
                    except Exception:
                        pass
        return _VENDOR_EMB_CACHE[key]
    except Exception:
        return None

def _suggest_from_cache(vec: np.ndarray, cache: dict, topk: int = 3, struct_vec=None) -> list:
    try:
        v = _normalize_vec(vec)
        if cache is None or not cache.get('items') or v.size == 0:
            return []
        # Helper to deduplicate by person_id, keeping highest similarity
        def _dedup(raw, topk):
            best = {}
            for entry in raw:
                pid = entry['person_id']
                if pid not in best or entry['similarity'] > best[pid]['similarity']:
                    best[pid] = entry
            return sorted(best.values(), key=lambda x: x['similarity'], reverse=True)[:topk]
        if cache.get('faiss_index') is not None and USE_FAISS:
            try:
                q = v.reshape(1, -1).astype(np.float32)
                # Search more than topk to account for duplicate person_ids
                search_k = min(topk * 5, len(cache['items']))
                if _FAISS_LOCK:
                    with _FAISS_LOCK:
                        D, I = cache['faiss_index'].search(q, search_k)
                else:
                    D, I = cache['faiss_index'].search(q, search_k)
                raw = []
                fmap = cache.get('faiss_map') or []
                for rank, idx in enumerate(I[0].tolist()):
                    if idx < 0 or idx >= len(fmap):
                        continue
                    pid, nm = fmap[idx]
                    sim = float(D[0][rank]) if D is not None else 0.0
                    
                    if struct_vec is not None:
                        match_item = next((x for x in cache['items'] if x['person_id'] == int(pid)), None)
                        if match_item and match_item.get('struct_vec') is not None:
                            s_u = match_item['struct_vec']
                            if s_u.size == struct_vec.size:
                                struct_sim = float(np.dot(s_u, struct_vec))
                                sim = (sim * 0.70) + (struct_sim * 0.30)
                    
                    raw.append({'person_id': int(pid), 'name': str(nm), 'similarity': sim})
                return _dedup(raw, topk)
            except Exception:
                pass
        sims = []
        for it in cache['items']:
            u = it['vec']
            if u.size != v.size:
                continue
            sim = float(np.dot(u, v))
            
            if struct_vec is not None and it.get('struct_vec') is not None:
                s_u = it['struct_vec']
                if s_u.size == struct_vec.size:
                    struct_sim = float(np.dot(s_u, struct_vec))
                    sim = (sim * 0.70) + (struct_sim * 0.30)
                    
            sims.append({'person_id': it['person_id'], 'name': it['name'], 'similarity': sim})
        return _dedup(sims, topk)
    except Exception:
        return []

def _detect_faces_from_bytes(image_bytes: bytes, params: dict, vendor_id):
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            return [], ''
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        from multiple_face_detection import app as mfd_app
        enhancer = params.get('enhancer') or "GFPGAN"
        crop_mode = params.get('crop_mode') or "Portrait"
        lr = LOW_RAM_MODE
        portrait_scale = float(params.get('portrait_scale') or (1.2 if lr else 1.5))
        gfp_up = int(params.get('gfpgan_upscale') or (1 if lr else 2))
        preclean_whole = bool(params.get('preclean_whole') if 'preclean_whole' in params else (False if lr else True))
        preclean_level = float(params.get('preclean_level') or (0.2 if lr else 0.4))
        annotated, crops, df, df_emb = mfd_app.detect_faces(
            image_input=rgb,
            enhancer=enhancer,
            enhance_level=0.5,
            gfpgan_upscale=gfp_up,
            codeformer_w=0.5,
            compute_embeddings=True,
            crop_mode=crop_mode,
            portrait_scale=portrait_scale,
            preclean_whole=preclean_whole,
            preclean_level=preclean_level,
            det_max_side=1280
        )
        faces = []
        class_year = params.get('class_year'); division = params.get('division'); branch = params.get('branch')
        vcache = _ensure_vendor_emb_cache(vendor_id, class_year=class_year, division=division, branch=branch)
        if isinstance(annotated, tuple) and len(annotated) == 2:
            img_rgb, anns = annotated
            draw = cv2.cvtColor(img_rgb.copy(), cv2.COLOR_RGB2BGR)
            for i, (box, score_str) in enumerate(anns or []):
                x1, y1, x2, y2 = [int(v) for v in box]
                cv2.rectangle(draw, (x1, y1), (x2, y2), (0, 180, 255), 2)
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
                    cx1, cy1, cx2, cy2 = mfd_app._compute_centered_box(bx1, by1, bx2, by2, img_rgb.shape[1], img_rgb.shape[0], scale=1.8)
                    pure_face = img_rgb[cy1:cy2, cx1:cx2]

                    # Compute embedding and 3D from PURE face crop (the padded one)
                    emb_vec_b64 = ''
                    struct_vec_b64 = ''
                    landmarks_3d = []
                    try:
                        if df is not None and hasattr(df, 'iloc') and i < len(df):
                            row = df.iloc[i]
                            if 'landmarks_3d' in row and isinstance(row['landmarks_3d'], list) and len(row['landmarks_3d']) > 0:
                                landmarks_3d = row['landmarks_3d']
                                # Draw on full annotated image (landmarks are now GLOBAL)
                                for pt in landmarks_3d:
                                    dx, dy = int(pt[0]), int(pt[1])
                                    cv2.circle(draw, (dx, dy), 1, (0, 255, 0), -1)

                        # Now professionally restore pure_face using GFPGAN for the thumbnail and embedding
                        if pure_face.size > 0:
                            lmks_local = None
                            if landmarks_3d:
                                try:
                                    lmks_local = np.array(landmarks_3d).copy()
                                    lmks_local[:, 0] -= cx1
                                    lmks_local[:, 1] -= cy1
                                except Exception:
                                    pass
                            
                            # Revert to GFPGAN for the sharp, professional look the user prefers
                            pure_face = mfd_app.get_gfpgan_manager().enhance_crop(pure_face, fidelity=0.9, upscale=2, landmarks=lmks_local)
                            if min(pure_face.shape[:2]) < 512:
                                scale_f = 512.0 / min(pure_face.shape[:2])
                                pure_face = cv2.resize(pure_face, (int(pure_face.shape[1] * scale_f), int(pure_face.shape[0] * scale_f)), interpolation=cv2.INTER_LANCZOS4)

                        emb = mfd_app.get_embedder().embed(pure_face)
                        vcache = _ensure_vendor_emb_cache(vendor_id, class_year=class_year, division=division, branch=branch)
                        
                        # Store base64 for UI preview
                        _, buffer = cv2.imencode('.jpg', cv2.cvtColor(pure_face, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                        # face_b64 = base64.b64encode(buffer).decode('utf-8') # Removed redundant assignment

                        # Compute structural vector if landmarks available
                        struct_vec_val = None
                        if landmarks_3d:
                            try:
                                lmks_local_sv = np.array(landmarks_3d).copy()
                                lmks_local_sv[:, 0] -= cx1
                                lmks_local_sv[:, 1] -= cy1
                                struct_vec_val = _extract_structural_vector(lmks_local_sv)
                                if struct_vec_val.size > 0:
                                    struct_vec_b64 = base64.b64encode(struct_vec_val.astype(np.float32).tobytes()).decode('ascii')
                            except Exception:
                                pass

                        emb_norm = _normalize_vec(emb)
                        if emb_norm.size > 0:
                            emb_vec_b64 = base64.b64encode(emb_norm.astype(np.float32).tobytes()).decode('ascii')
                        
                        sugg = _suggest_from_cache(emb, vcache, topk=3, struct_vec=struct_vec_val)
                    except Exception:
                        sugg = []

                    try:
                        px1, py1, px2, py2 = mfd_app._compute_portrait_box(bx1, by1, bx2, by2, img_rgb.shape[1], img_rgb.shape[0], scale=3.0, margin=0.5)
                        portrait = img_rgb[py1:py2, px1:px2]
                        if lr:
                            portrait_enh = portrait
                        else:
                            portrait_enh = mfd_app.get_gfpgan_manager().enhance_crop(portrait, upscale=gfp_up, whole=True) if portrait.size > 0 else portrait
                    except Exception:
                        portrait_enh = None

                    # Encode pure face crop as thumbs.face (used for display AND saving embeddings)
                    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(pure_face, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
                    face_b64 = base64.b64encode(buf.tobytes()).decode('ascii') if ok else ''
                    if portrait_enh is not None and portrait_enh.size > 0:
                        okp, bufp = cv2.imencode('.jpg', cv2.cvtColor(portrait_enh, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
                        port_b64 = base64.b64encode(bufp.tobytes()).decode('ascii') if okp else ''
                    else:
                        port_b64 = ''

                    faces.append({
                        "index": i,
                        "box": [bx1, by1, bx2, by2],
                        "score": float(score_str) if score_str else None,
                        "thumbs": {"face": f"data:image/jpeg;base64,{face_b64}" if face_b64 else None, "portrait": f"data:image/jpeg;base64,{port_b64}" if port_b64 else None},
                        "suggestions": sugg,
                        "emb_vec": emb_vec_b64,
                        "struct_vec": struct_vec_b64,
                        "landmarks_3d": landmarks_3d
                    })

            ok2, ann = cv2.imencode('.jpg', draw, [cv2.IMWRITE_JPEG_QUALITY, 85])
            annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(ann.tobytes()).decode('ascii')}" if ok2 else ''
        else:
            annotated_b64 = ''
        return faces, annotated_b64
    except Exception as e:
        import traceback
        pass # print(f"[FACE_DETECT] ERROR: {e}", flush=True)
        traceback.print_exc()
        return [], ''