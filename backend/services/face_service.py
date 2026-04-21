from __future__ import annotations
import numpy as np
import cv2
import base64
import time
import sqlite3
from threading import Lock

# Local imports to avoid circular dependencies where needed
# In a real refactor, these caches should probably live here.

from utils import get_db_connection, _VENDOR_EMB_CACHE, _now_ts, USE_FAISS, _faiss, _FAISS_LOCK, LOW_RAM_MODE, decode_image_to_rgb
from db_factory import get_table_columns

def get_realtime_engine():
    from app import get_realtime_engine as _get
    return _get()

def _extract_structural_vector(lmks):
    """
    Extracts a pose-invariant geometric ratio vector from 68-point landmarks.
    Focuses on physiological proportions (ratios) rather than absolute distances.
    """
    if lmks is None or len(lmks) != 68:
        return np.array([], dtype=np.float32)
    
    # Key Anchor Points
    le = np.mean(lmks[36:42], axis=0)  # Left Eye Center
    re = np.mean(lmks[42:48], axis=0)  # Right Eye Center
    nose_tip = lmks[33]
    mouth_l = lmks[48]
    mouth_r = lmks[54]
    chin = lmks[8]
    forehead_top = lmks[27] # Reference point on nose bridge
    
    # Fundamental distances for ratios
    iod = np.linalg.norm(le - re)  # Interocular Distance (Base Unit)
    if iod < 1e-5: return np.array([], dtype=np.float32)
    
    # 1. Broad Facial Ratios
    nose_to_chin = np.linalg.norm(nose_tip - chin) / iod
    eye_to_nose = np.linalg.norm((le + re)/2 - nose_tip) / iod
    mouth_width = np.linalg.norm(mouth_l - mouth_r) / iod
    face_height = np.linalg.norm(forehead_top - chin) / iod
    jaw_breadth = np.linalg.norm(lmks[4] - lmks[12]) / iod
    
    # 2. Key landmark relative distances to nose tip (normalized by IOD)
    # We take 20 key points to avoid noise from individual jitter
    key_indices = [0, 4, 8, 12, 16, 17, 21, 22, 26, 36, 39, 42, 45, 48, 51, 54, 57, 60, 64, 66]
    vec = [nose_to_chin, eye_to_nose, mouth_width, face_height, jaw_breadth]
    
    for idx in key_indices:
        d = np.linalg.norm(lmks[idx] - nose_tip) / iod
        vec.append(d)
        
    v = np.array(vec, dtype=np.float32)
    # Final normalization into a unit vector for dot product similarity
    n = np.linalg.norm(v)
    return (v / n) if n > 1e-6 else v

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
        return decode_image_to_rgb(raw)
    except Exception:
        return None

def _apply_contrastive_refinement(sims: list, penalty_scale: float = 0.2) -> list:
    """
    Pushes dissimilar identities apart if they are too close (Embedding Separation).
    """
    if len(sims) < 2:
        return sims
        
    top1 = sims[0]
    top2 = sims[1]
    
    # Only refine if they are different identities and both have significant similarity
    if top1['person_id'] != top2['person_id'] and top1['similarity'] > 0.4:
        s1 = top1['similarity']
        s2 = top2['similarity']
        
        gap = s1 - s2
        
        # AMBIGUITY DETECTION: If the model is collapsed (both high sim) 
        # but the gap is tiny (< 5%), flag it.
        if s1 > 0.7 and gap < 0.05:
            top1['is_ambiguous'] = True
            top2['is_ambiguous'] = True
        
        # If the gap is small (< 10%), the identification is ambiguous.
        # We push them away from each other mathematically.
        overlap = max(0.0, 1.0 - gap)
        penalty = overlap * penalty_scale
        
        # Accentuate the winner, penalize the runner-up if they are too close
        top1['similarity'] = min(1.0, float(s1 + (gap * 0.1))) 
        top2['similarity'] = max(0.0, float(s2 - penalty))
        
    return sorted(sims, key=lambda x: x['similarity'], reverse=True)

def _cluster_batch_embeddings(embeddings_map: dict, threshold: float = 0.90) -> list:
    """
    Groups embeddings that belong to the same person within a batch (Intra-batch Clustering).
    embeddings_map: {global_index: embedding_vector}
    Returns: List of {'centroid': vec, 'indices': [global_indices]}
    """
    clusters = []
    for idx, vec in embeddings_map.items():
        v = _normalize_vec(vec)
        if v.size == 0: continue
        
        top_sim = -1.0
        target_cluster = None
        
        for c in clusters:
            sim = float(np.dot(c['centroid'], v))
            if sim > threshold and sim > top_sim:
                top_sim = sim
                target_cluster = c
        
        if target_cluster:
            target_cluster['indices'].append(idx)
            # Update centroid (moving average)
            target_cluster['centroid'] = _normalize_vec((target_cluster['centroid'] * (len(target_cluster['indices']) - 1) + v))
        else:
            clusters.append({'centroid': v, 'indices': [idx]})
    return clusters

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
            # Table may not exist yet in Postgres; rollback aborted txn before DDL
            try:
                if hasattr(conn, "rollback"): 
                    conn.rollback()
            except Exception:
                pass
            current_sig = "0_0"

        ent = _VENDOR_EMB_CACHE.get(key)
        if ent and ent.get('sig') == current_sig and (_now_ts() - ent.get('ts', 0.0)) < ttl_sec and ent.get('items'):
            conn.close()
            return ent
            
        from multiple_face_detection import app as mfd_app
        items = []
        try:
            q = "SELECT person_id, vec, dim, struct_vec, class_year, division, branch FROM person_embeddings WHERE vendor_id = ?"
            args = [int(vendor_id or 0)]
            if class_year:
                # STRICT FILTERING: Only include students from the EXACT class if one is specified
                q += " AND class_year = ?"
                args.append(str(class_year))
            if division:
                q += " AND division = ?"
                args.append(str(division))
            if branch:
                q += " AND branch = ?"
                args.append(str(branch))
            c.execute(q, args)
            rows_emb = c.fetchall() or []
            
            # The primary query already filters by class_year, division, and branch.
            # We don't need to secondary-filter by faces.custom_data as it's often out of sync.
            valid_person_ids = None

            id_set = set()
            for r in rows_emb:
                try:
                    pid = int(r['person_id'] if isinstance(r, sqlite3.Row) else r[0])
                    if valid_person_ids is not None and pid not in valid_person_ids:
                        continue

                    vb = r['vec'] if isinstance(r, sqlite3.Row) else r[1]
                    dim = int(r['dim'] if isinstance(r, sqlite3.Row) else r[2])
                    sb = r['struct_vec'] if isinstance(r, sqlite3.Row) else r[3]
                    class_y = r['class_year'] if isinstance(r, sqlite3.Row) else r[4]
                    div = r['division'] if isinstance(r, sqlite3.Row) else r[5]
                    br = r['branch'] if isinstance(r, sqlite3.Row) else r[6]
                    
                    s_vec = None
                    if sb:
                        sd = np.frombuffer(sb, dtype=np.float32)
                        if sd.size > 0:
                            s_vec = sd
                    
                    if vb and dim > 0:
                        v = np.frombuffer(vb, dtype=np.float32)
                        if v.size == dim:
                            v = _normalize_vec(v)
                            items.append({'person_id': pid, 'name': '', 'vec': v, 'struct_vec': s_vec, 'class_year': class_y, 'division': div, 'branch': br})
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
        # Check if face_image column exists
        cols = get_table_columns(conn, "faces")
        has_face_img = 'face_image' in cols
        # Build set of person_ids that already have pre-computed embeddings
        emb_pid_set = set(it['person_id'] for it in items)
        # Load people from faces table if face_image column exists, skipping those with pre-computed embeddings
        if has_face_img:
            base_query = f"SELECT id, name, face_image, department, custom_data FROM faces"
            params = []
            where = []
            if vendor_id:
                where.append("vendor_id = ?"); params.append(vendor_id)
            if class_year:
                # STRICT FILTERING: Use LIKE for exact JSON field match to avoid including unassigned students
                where.append("custom_data LIKE ?")
                params.append(f'%\"class_year\":\"{class_year}\"%')
            if division:
                where.append("custom_data LIKE ?")
                params.append(f'%\"division\":\"{division}\"%')
            if branch:
                where.append("custom_data LIKE ?")
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
                    uri = r['face_image'] if isinstance(r, sqlite3.Row) else r[2]
                    img_rgb = _decode_data_uri_to_rgb(uri)
                    if img_rgb is None:
                        continue

                    det_ann, det_crops, det_df, _ = mfd_app.detect_faces(
                        image_input=img_rgb,
                        enhancer="GFPGAN",
                        enhance_level=0.5,
                        gfpgan_upscale=1,
                        codeformer_w=0.5,
                        compute_embeddings=False,
                        crop_mode="Face",
                        portrait_scale=3.0,
                        preclean_whole=False,
                        preclean_level=0.2,
                        det_max_side=640
                    )
                    crop = det_crops[0] if (isinstance(det_crops, list) and len(det_crops) > 0) else img_rgb
                    # Extract local landmarks from detection result.
                    lmks_local_reg = None
                    if det_df is not None and hasattr(det_df, 'iloc') and len(det_df) > 0:
                        row0 = det_df.iloc[0]
                        lmks_global_reg = row0.get('landmarks_3d', [])
                        if lmks_global_reg and len(lmks_global_reg) >= 68:
                            bx1_r, by1_r = int(row0['x1']), int(row0['y1'])
                            lmks_local_reg = np.array(lmks_global_reg, dtype=np.float32)
                            lmks_local_reg[:, 0] -= bx1_r
                            lmks_local_reg[:, 1] -= by1_r
                    
                    struct_vec_reg = None
                    if lmks_local_reg is not None:
                        struct_vec_reg = _extract_structural_vector(lmks_local_reg)

                    emb = mfd_app.get_embedder().embed(crop)
                    emb = _normalize_vec(emb)
                    if emb is not None and emb.size > 0:
                        items.append({
                            'person_id': int(pid), 
                            'name': str(nm), 
                            'vec': emb,
                            'struct_vec': struct_vec_reg
                        })
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
                # Lower defaults for 512MB RAM instances
                max_items = int(os.environ.get("EMB_CACHE_MAX_ITEMS", "200") or "200")
            except Exception:
                max_items = 200
            _VENDOR_EMB_CACHE[key]['items'] = _VENDOR_EMB_CACHE[key]['items'][:max_items]
        return _VENDOR_EMB_CACHE[key]
        return _VENDOR_EMB_CACHE[key]
    except Exception:
        return None

def _suggest_from_cache(vec: np.ndarray, cache: dict, topk: int = 3, struct_vec=None, class_year=None, division=None, branch=None) -> list:
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
                                # Weighting: 60% 3D Structural Mesh, 40% Facial Embeddings (ArcFace)
                                sim = (sim * 0.40) + (struct_sim * 0.60)
                    
                    # Check for perfect scope match
                    is_perfect = True
                    # Find matching item in cache to check scope
                    match_item = next((x for x in cache.get('items', []) if x['person_id'] == int(pid)), None)
                    if match_item:
                        if class_year and str(match_item.get('class_year') or '') != str(class_year): is_perfect = False
                        if division and str(match_item.get('division') or '') != str(division): is_perfect = False
                        if branch and str(match_item.get('branch') or '') != str(branch): is_perfect = False

                    # STRICT FILTERING: If any scope is provided, only include perfect matches
                    if (class_year or division or branch) and not is_perfect:
                        continue

                    raw.append({'person_id': int(pid), 'name': str(nm), 'similarity': sim, 'perfect_scope': is_perfect})
                
                deduped = _dedup(raw, topk * 2) # Get more candidates for refinement
                refined = _apply_contrastive_refinement(deduped)[:topk]
                
                # Fetch images for the results
                try:
                    pids = [int(r['person_id']) for r in refined]
                    if pids:
                        conn = get_db_connection()
                        c = conn.cursor()
                        ph = ",".join(["?"]*len(pids))
                        c.execute(f"SELECT id, face_image, custom_data FROM faces WHERE id IN ({ph})", pids)
                        img_rows = c.fetchall() or []
                        imap = {int(r[0]): (r[1], r[2]) for r in img_rows}
                        for r in refined:
                            img, custom = imap.get(int(r['person_id']), (None, None))
                            r['face_image'] = img
                            if custom:
                                try:
                                    cd = json.loads(custom) if isinstance(custom, str) else custom
                                    r['student_number'] = cd.get('student_number')
                                except Exception:
                                    pass
                        conn.close()
                except Exception:
                    pass
                
                return refined
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
                    # Weighting: 60% 3D Structural Mesh, 40% Facial Embeddings (ArcFace)
                    sim = (sim * 0.40) + (struct_sim * 0.60)
                    
            is_perfect = True
            if class_year and str(it.get('class_year') or '') != str(class_year): is_perfect = False
            if division and str(it.get('division') or '') != str(division): is_perfect = False
            if branch and str(it.get('branch') or '') != str(branch): is_perfect = False
            
            # STRICT FILTERING: If any scope is provided, only include perfect matches
            if (class_year or division or branch) and not is_perfect:
                continue
                    
            sims.append({'person_id': it['person_id'], 'name': it['name'], 'similarity': sim, 'perfect_scope': is_perfect})
        
        deduped = _dedup(sims, topk * 2)
        refined = _apply_contrastive_refinement(deduped)[:topk]
        
        # Fetch images for the results
        try:
            pids = [int(r['person_id']) for r in refined]
            if pids:
                conn = get_db_connection()
                c = conn.cursor()
                ph = ",".join(["?"]*len(pids))
                c.execute(f"SELECT id, face_image, custom_data FROM faces WHERE id IN ({ph})", pids)
                img_rows = c.fetchall() or []
                imap = {int(r[0]): (r[1], r[2]) for r in img_rows}
                for r in refined:
                    img, custom = imap.get(int(r['person_id']), (None, None))
                    r['face_image'] = img
                    if custom:
                        try:
                            cd = json.loads(custom) if isinstance(custom, str) else custom
                            r['student_number'] = cd.get('student_number')
                        except Exception:
                            pass
                conn.close()
        except Exception:
            pass
            
        return refined
    except Exception:
        return []

def _detect_faces_from_bytes(image_bytes: bytes, params: dict, vendor_id):
    try:
        rgb = decode_image_to_rgb(image_bytes)
        if rgb is None:
            return [], ''
        from multiple_face_detection import app as mfd_app
        lr = LOW_RAM_MODE
        # fast=True skips all enhancement — ArcFace is robust on raw crops
        # and GFPGAN adds ~3–5 s per face with no meaningful accuracy gain
        fast = str(params.get('fast', '')).lower() in ('1', 'true', 'yes') or lr
        print(f"[FACE_SVC] fast={fast} raw_fast={params.get('fast')!r} LOW_RAM_MODE={lr}", flush=True)
        crop_mode = params.get('crop_mode') or "Portrait"
        if fast:
            enhancer = "None"
            gfp_up = 1
            preclean_whole = False
            preclean_level = 0.0
            portrait_scale = float(params.get('portrait_scale') or 1.2)
            # fast=True means skip GFPGAN, NOT degrade detection resolution.
            # Keep det_max_side at 1280 so tiling works on group photos.
            det_max_side = int(params.get('det_max_side') or 1280)
        else:
            enhancer = params.get('enhancer') or "GFPGAN"
            portrait_scale = float(params.get('portrait_scale') or 1.5)
            gfp_up = int(params.get('gfpgan_upscale') or 2)
            preclean_whole = bool(params.get('preclean_whole') if 'preclean_whole' in params else True)
            preclean_level = float(params.get('preclean_level') or 0.4)
            det_max_side = int(params.get('det_max_side') or 1280)
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
            det_max_side=det_max_side,
        )
        faces = []
        class_year = params.get('class_year'); division = params.get('division'); branch = params.get('branch')
        vcache = _ensure_vendor_emb_cache(vendor_id, class_year=class_year, division=division, branch=branch)
        if isinstance(annotated, tuple) and len(annotated) == 2:
            img_rgb, anns = annotated
            draw = cv2.cvtColor(img_rgb.copy(), cv2.COLOR_RGB2BGR)
            
            # Step 1: Pre-process all faces to get embeddings and structural vectors
            face_data = []
            embeddings_map = {} # {local_index: emb_norm}
            
            for i, (box, score_str) in enumerate(anns or []):
                x1, y1, x2, y2 = [int(v) for v in box]
                cv2.rectangle(draw, (x1, y1), (x2, y2), (0, 180, 255), 2)
                if i < len(crops):
                    ih, iw = img_rgb.shape[:2]
                    if df is not None and hasattr(df, 'iloc') and i < len(df):
                        row = df.iloc[i]
                        bx1, by1, bx2, by2 = int(row['x1']), int(row['y1']), int(row['x2']), int(row['y2'])
                        landmarks_3d = row.get('landmarks_3d', [])
                    else:
                        bx1, by1, bx2, by2 = x1, y1, x2, y2
                        landmarks_3d = []
                    
                    bx1 = max(0, bx1); by1 = max(0, by1); bx2 = min(iw, bx2); by2 = min(ih, by2)
                    cx1, cy1, cx2, cy2 = mfd_app._compute_centered_box(bx1, by1, bx2, by2, iw, ih, scale=1.2)
                    pure_face = img_rgb[cy1:cy2, cx1:cx2]
                    
                    if pure_face.size > 0:
                        lmks_local = None
                        if landmarks_3d:
                            try:
                                lmks_local = np.array(landmarks_3d).copy()
                                lmks_local[:, 0] -= cx1
                                lmks_local[:, 1] -= cy1
                                # Draw 68-point facial mesh on annotated image (BGR colors)
                                _MESH_REGIONS = [
                                    (list(range(0, 17)),        (160, 160, 160), False),  # jaw
                                    (list(range(17, 22)),       (0, 165, 255),   False),  # left brow
                                    (list(range(22, 27)),       (0, 165, 255),   False),  # right brow
                                    (list(range(27, 31)),       (0, 255, 255),   False),  # nose bridge
                                    (list(range(31, 36)),       (0, 210, 255),   False),  # nose base
                                    (list(range(36, 42)) + [36],(255, 230, 0),   True),   # left eye (closed)
                                    (list(range(42, 48)) + [42],(255, 230, 0),   True),   # right eye (closed)
                                    (list(range(48, 60)) + [48],(80, 50, 255),   True),   # outer lip (closed)
                                    (list(range(60, 68)) + [60],(60, 30, 200),   True),   # inner lip (closed)
                                ]
                                pts_2d = [(int(pt[0]), int(pt[1])) for pt in landmarks_3d]
                                if len(pts_2d) >= 68:
                                    for indices, color, _ in _MESH_REGIONS:
                                        for k in range(len(indices) - 1):
                                            p1 = pts_2d[indices[k]]
                                            p2 = pts_2d[indices[k + 1]]
                                            cv2.line(draw, p1, p2, color, 1, cv2.LINE_AA)
                                    # Z-depth coloring: normalize z to map near=green, far=blue
                                    pts_z = [float(pt[2]) if len(pt) > 2 else 0.0 for pt in landmarks_3d]
                                    z_min, z_max = min(pts_z), max(pts_z)
                                    z_range = max(z_max - z_min, 1.0)
                                    for idx, (px, py) in enumerate(pts_2d):
                                        t = (pts_z[idx] - z_min) / z_range  # 0=near, 1=far
                                        dot_color = (int(255 * t), int(220 * (1 - t)), int(60 + 60 * (1 - t)))
                                        cv2.circle(draw, (px, py), 3, dot_color, -1, cv2.LINE_AA)
                                else:
                                    for pt in pts_2d:
                                        cv2.circle(draw, pt, 2, (0, 255, 0), -1)
                            except Exception:
                                pass
                        
                        # Optimization: Use pre-computed embedding from the batched detect_faces call
                        # This skips TWO redundant heavy AI model passes (Enhancement + Embedding) per face.
                        emb_norm = None
                        if df_emb is not None and i < len(df_emb):
                            emb_norm = df_emb[i]
                        
                        if emb_norm is None:
                            # Fallback if somehow missing, but honor 'fast' mode
                            emb_crop_112, face_display = mfd_app.prepare_embedding_crop(pure_face, lmks_local, skip_enhancement=fast)
                            emb = mfd_app.get_embedder().embed(emb_crop_112)
                            emb_norm = _normalize_vec(emb)
                        else:
                            # We still need face_display for the thumbnail, use fast path
                            _, face_display = mfd_app.prepare_embedding_crop(pure_face, lmks_local, skip_enhancement=fast)

                        # Extract Structural Vector
                        struct_vec_val = None
                        struct_vec_b64 = ''
                        if landmarks_3d:
                            try:
                                struct_vec_val = _extract_structural_vector(lmks_local)
                                if struct_vec_val.size > 0:
                                    struct_vec_b64 = base64.b64encode(struct_vec_val.astype(np.float32).tobytes()).decode('ascii')
                            except Exception:
                                pass

                        emb_vec_b64 = base64.b64encode(emb_norm.astype(np.float32).tobytes()).decode('ascii') if emb_norm.size > 0 else ''

                        # Sharpness score — Laplacian variance on raw face crop (before any enhancement).
                        # Higher = sharper. < 80 = blurry, > 150 = acceptably sharp.
                        _BLUR_THRESHOLD = 80.0
                        try:
                            gray_face = cv2.cvtColor(pure_face, cv2.COLOR_RGB2GRAY)
                            sharpness_score = float(cv2.Laplacian(gray_face, cv2.CV_64F).var())
                        except Exception:
                            sharpness_score = 999.0  # assume sharp on error
                        is_blurry = sharpness_score < _BLUR_THRESHOLD

                        # Portrait thumbnail: selective enhancement for blurry faces.
                        # Even in 'fast' mode, we enhance blurry faces to maintain visual quality
                        # unless the enhancer was explicitly set to 'None'.
                        try:
                            px1, py1, px2, py2 = mfd_app._compute_portrait_box(bx1, by1, bx2, by2, iw, ih, scale=3.0, margin=0.5)
                            portrait = img_rgb[py1:py2, px1:px2]
                            
                            # Only enhance if it's blurry AND the user hasn't explicitly disabled all enhancement
                            should_enhance = is_blurry and params.get('enhancer') != 'None'
                            
                            if portrait.size > 0 and should_enhance:
                                with mfd_app._gfpgan_lock:
                                    portrait_enh = mfd_app.get_gfpgan_manager().enhance_crop(portrait, upscale=1, whole=True, fidelity=0.5)
                            else:
                                portrait_enh = portrait
                        except Exception:
                            portrait_enh = None

                        # Encode thumbnails — face_display is RealESRGAN-enhanced natural crop
                        ok, buf = cv2.imencode('.jpg', cv2.cvtColor(face_display, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
                        okp, bufp = cv2.imencode('.jpg', cv2.cvtColor(portrait_enh, cv2.COLOR_RGB2BGR) if portrait_enh is not None else np.zeros((1,1,3), np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 85])

                        # Landmark mesh thumbnail — crop the face region from the annotated draw buffer
                        lmk_thumb_b64 = None
                        try:
                            pad_lmk = int(max(bx2 - bx1, by2 - by1) * 0.35)
                            lx1 = max(0, bx1 - pad_lmk); ly1 = max(0, by1 - pad_lmk)
                            lx2 = min(draw.shape[1], bx2 + pad_lmk); ly2 = min(draw.shape[0], by2 + pad_lmk)
                            lmk_region = draw[ly1:ly2, lx1:lx2]
                            if lmk_region.size > 0:
                                lmk_resized = cv2.resize(lmk_region, (240, 240), interpolation=cv2.INTER_AREA)
                                ok_lmk, buf_lmk = cv2.imencode('.jpg', lmk_resized, [cv2.IMWRITE_JPEG_QUALITY, 88])
                                if ok_lmk:
                                    lmk_thumb_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf_lmk).decode('ascii')}"
                        except Exception:
                            pass

                        f_entry = {
                            "index": i,
                            "box": [bx1, by1, bx2, by2],
                            "score": float(score_str) if score_str else None,
                            "sharpness": round(sharpness_score, 1),
                            "thumbs": {
                                "face": f"data:image/jpeg;base64,{base64.b64encode(buf).decode('ascii')}" if ok else None,
                                "portrait": f"data:image/jpeg;base64,{base64.b64encode(bufp).decode('ascii')}" if (okp and portrait_enh is not None) else None,
                                "lmk": lmk_thumb_b64
                            },
                            "emb_vec": emb_vec_b64,
                            "struct_vec": struct_vec_b64,
                            "landmarks_3d": landmarks_3d,
                            "emb_norm": emb_norm, # Internal use
                            "struct_vec_val": struct_vec_val # Internal use
                        }
                        face_data.append(f_entry)
                        if emb_norm.size > 0:
                            embeddings_map[len(face_data)-1] = emb_norm

            # Step 2: Intra-batch Clustering
            clusters = _cluster_batch_embeddings(embeddings_map, threshold=0.90)
            
            # Step 3: Identify Clusters and Assign
            for cluster in clusters:
                centroid = cluster['centroid']
                # Pick the best structural vector from the cluster for identification leverage
                best_sv = None
                best_s = -1.0
                for f_idx in cluster['indices']:
                    f = face_data[f_idx]
                    f_score = f.get('score')
                    if f_score is not None and float(f_score) > best_s:
                        best_s = float(f_score)
                        best_sv = f.get('struct_vec_val')
                
                sugg = _suggest_from_cache(centroid, vcache, topk=3, struct_vec=best_sv, class_year=class_year, division=division, branch=branch)
                for f_idx in cluster['indices']:
                    face_data[f_idx]['suggestions'] = sugg
            
            # Step 4: Fallback for any non-clustered faces (should be none, but safe)
            for f in face_data:
                if 'suggestions' not in f:
                    f['suggestions'] = _suggest_from_cache(f['emb_norm'], vcache, topk=3, struct_vec=f['struct_vec_val'], class_year=class_year, division=division, branch=branch)
                # Cleanup internal fields before returning
                if 'emb_norm' in f: del f['emb_norm']
                if 'struct_vec_val' in f: del f['struct_vec_val']

            # Second-stage filter: only keep faces the 3D engine confirmed as real.
            # A face with no landmarks_3d is almost certainly a detector false positive
            # (background blob, partial body part, etc.).
            # Guard: if the 3D engine isn't running at all (no face has landmarks),
            # skip filtering so the UI still shows something.
            has_any_landmarks = any(f.get('landmarks_3d') for f in face_data)
            faces = [f for f in face_data if f.get('landmarks_3d')] if has_any_landmarks else face_data

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
