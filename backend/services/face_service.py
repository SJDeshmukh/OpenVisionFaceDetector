from __future__ import annotations
import numpy as np
import cv2
import base64
import time
import sqlite3
import json
from threading import Lock
import os

# Local imports to avoid circular dependencies where needed
# In a real refactor, these caches should probably live here.

from utils import get_db_connection, _VENDOR_EMB_CACHE, _now_ts, USE_FAISS, _faiss, _FAISS_LOCK, LOW_RAM_MODE, decode_image_to_rgb
from db_factory import get_table_columns

def get_realtime_engine():
    from app import get_realtime_engine as _get
    return _get()

def _align_landmarks_3d(lmks: np.ndarray) -> np.ndarray:
    """
    Remove head pose (yaw/pitch/roll) by rotating the 3D mesh into a
    canonical frontal frame defined by the eye line (X) and the
    orthogonalized nose-bridge→chin vector (Y).
    Handles both 2D (68,2) and 3D (68,3) landmarks by padding 2D→3D.
    Falls back to the original landmarks on degenerate input.
    """
    lmks = np.array(lmks, dtype=np.float32)
    # Pad 2D landmarks to 3D with z=0 so cross product and rotation work
    if lmks.ndim == 2 and lmks.shape[1] == 2:
        lmks = np.column_stack([lmks, np.zeros(len(lmks), dtype=np.float32)])

    if lmks.ndim != 2 or lmks.shape[1] != 3:
        return lmks  # unexpected shape, skip alignment

    le = np.mean(lmks[36:42], axis=0)
    re = np.mean(lmks[42:48], axis=0)

    x_axis = re - le
    x_norm = np.linalg.norm(x_axis)
    if x_norm < 1e-5:
        return lmks
    x_axis /= x_norm

    y_raw = lmks[27] - lmks[8]  # nose bridge → chin
    y_axis = y_raw - np.dot(y_raw, x_axis) * x_axis  # orthogonalize against X
    y_norm = np.linalg.norm(y_axis)
    if y_norm < 1e-5:
        return lmks
    y_axis /= y_norm

    z_axis = np.cross(x_axis, y_axis)
    z_norm = np.linalg.norm(z_axis)
    if z_norm < 1e-5:
        return lmks
    z_axis /= z_norm

    # R columns are face axes in world space; R^T maps face frame → canonical
    R = np.column_stack([x_axis, y_axis, z_axis])
    center = (le + re) / 2.0
    return ((R.T @ (lmks - center).T).T + center).astype(np.float32)


def _extract_structural_vector(lmks):
    # Pose-aligned full-mesh: align to canonical frontal frame first,
    # then 68pts × N coords anchored to nose bridge, scaled by IOD, L2-normalized
    # Output: 204-dim (3D) or 136-dim (2D) depending on input landmark depth
    if lmks is None or len(lmks) != 68:
        return np.array([], dtype=np.float32)
    lmks = np.array(lmks, dtype=np.float32)
    lmks = _align_landmarks_3d(lmks)  # always returns (68, 3) after padding
    anchor = lmks[27]  # nose bridge (after alignment)
    le = np.mean(lmks[36:42], axis=0)
    re = np.mean(lmks[42:48], axis=0)
    iod = float(np.linalg.norm(le - re))
    if iod < 1e-5: iod = 1.0
    mesh_norm = (lmks - anchor) / iod
    v = mesh_norm.flatten().astype(np.float32)
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

def _estimate_pose_yaw(landmarks) -> float:
    """
    Estimates horizontal face turn (yaw proxy) from 2D face landmarks.
    Returns 0.0 (frontal) → 1.0 (full side profile).
    Uses asymmetry of outer-eye-to-nose distances (dlib 68-point layout).
    Robust: returns 0.0 on any error so it never blocks a match.
    """
    try:
        lm = np.asarray(landmarks, dtype=np.float32)
        if lm.ndim != 2 or lm.shape[0] < 46 or lm.shape[1] < 2:
            return 0.0
        left_outer_x  = lm[36, 0]   # outer left-eye corner
        right_outer_x = lm[45, 0]   # outer right-eye corner
        nose_x        = lm[30, 0]   # nose tip
        eye_span = abs(right_outer_x - left_outer_x)
        if eye_span < 1.0:
            return 0.0
        eye_center_x = (left_outer_x + right_outer_x) / 2.0
        return float(min(1.0, abs(nose_x - eye_center_x) / eye_span))
    except Exception:
        return 0.0


def _quality_min_sim(sharpness: float, pose_yaw: float, face_score: float) -> float:
    """
    Minimum ArcFace cosine similarity (0→1 scale) required to emit a suggestion.

    Quality tiers (Laplacian variance):
        CLEAR  (≥150) + frontal → 0.72
        SOFT   (80–150)         → 0.74
        BLUR   (<80)            → 0.78
    Pose penalty:
        yaw 0.30–0.45 → +0.04  (~25-40° turn)
        yaw >0.45     → +0.07  (>40° turn, semi-profile)
    Detector-score penalty:
        score < 0.70  → +0.02
    """
    if sharpness < 80:
        base = 0.76   # BLUR — still strict, just marginally relaxed from 0.78
    elif sharpness < 150:
        base = 0.72   # SOFT — aligned with frontend default threshold
    else:
        base = 0.68   # CLEAR frontal — reliable enough at this score

    if pose_yaw > 0.45:
        base += 0.07
    elif pose_yaw > 0.30:
        base += 0.04

    if face_score < 0.70:
        base += 0.02

    return min(base, 0.92)


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

        # AMBIGUITY DETECTION: flag when top-2 scores are too close (gap < 5%)
        # or when the winner itself is below the reliable-match zone (< 0.78).
        is_ambiguous = (s1 > 0.65 and gap < 0.05) or (s1 < 0.78 and gap < 0.04)
        if is_ambiguous:
            top1['is_ambiguous'] = True
            top2['is_ambiguous'] = True
            # Suppress ambiguous suggestions when top-1 is below reliable zone
            # — returning a wrong label is worse than returning nothing
            if s1 < 0.72:
                return []

        # Accentuate the winner, penalize the runner-up if they are too close
        overlap = max(0.0, 1.0 - gap)
        penalty = overlap * penalty_scale
        top1['similarity'] = min(1.0, float(s1 + (gap * 0.1)))
        top2['similarity'] = max(0.0, float(s2 - penalty))

    return sorted(sims, key=lambda x: x['similarity'], reverse=True)

def _cluster_batch_embeddings(embeddings_map: dict, threshold: float = 0.75) -> list:
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
            sim = (float(np.dot(c['centroid'], v)) + 1.0) / 2.0
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
            
            # Case-insensitive robust filtering for Postgres/SQLite
            if class_year:
                q += " AND (LOWER(TRIM(class_year)) = LOWER(TRIM(?)) OR class_year IS NULL OR class_year = '')"
                args.append(str(class_year))
            if division:
                q += " AND LOWER(TRIM(division)) = LOWER(TRIM(?))"
                args.append(str(division))
            if branch:
                q += " AND LOWER(TRIM(branch)) = LOWER(TRIM(?))"
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
                        sd = np.frombuffer(sb, dtype=np.float32).copy()
                        if sd.size > 0:
                            s_vec = _normalize_vec(sd)
                    
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
                    # Fetch name AND face_image so we can apply gallery TTA to
                    # pre-computed embeddings. The stored vec was generated from a
                    # single frontal capture; averaging it with the flip embedding
                    # of the same image makes the centroid cover mild head turns.
                    c.execute(f"SELECT id, name, face_image FROM faces WHERE id IN ({ph})", pid_list)
                    nmrows = c.fetchall() or []
                    nmap = {}
                    flip_map = {}  # pid → flipped embedding
                    for nr in nmrows:
                        nid = int(nr['id'] if isinstance(nr, sqlite3.Row) else nr[0])
                        nmap[nid] = nr['name'] if isinstance(nr, sqlite3.Row) else nr[1]
                        uri = nr['face_image'] if isinstance(nr, sqlite3.Row) else nr[2]
                        if uri:
                            try:
                                img_rgb = _decode_data_uri_to_rgb(uri)
                                if img_rgb is not None:
                                    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                                    flipped_bgr = cv2.flip(img_bgr, 1)
                                    flipped_rgb = cv2.cvtColor(flipped_bgr, cv2.COLOR_BGR2RGB)
                                    from multiple_face_detection import app as mfd_app
                                    emb_f = mfd_app.get_embedder().embed(flipped_rgb)
                                    emb_f = _normalize_vec(emb_f)
                                    if emb_f.size > 0:
                                        flip_map[nid] = emb_f
                            except Exception:
                                pass
                    for it in items:
                        it['name'] = nmap.get(it['person_id'], '')
                        # Blend stored embedding with flipped embedding to get a
                        # pose-robust centroid without re-registering anyone.
                        fv = flip_map.get(it['person_id'])
                        if fv is not None and fv.size == it['vec'].size:
                            it['vec'] = _normalize_vec(it['vec'] + fv)
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
                        enhancer="None",   # no GFPGAN — Real-ESRGAN handles small faces during inference
                        enhance_level=0.5,
                        gfpgan_upscale=1,
                        codeformer_w=0.5,
                        compute_embeddings=False,
                        crop_mode="Face",
                        portrait_scale=3.0,
                        preclean_whole=False,
                        preclean_level=0.0,
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
                    # Gallery TTA: average original + horizontally flipped embedding.
                    # This creates a centroid that covers mild left/right head turns,
                    # matching the range of poses seen in classroom photos without
                    # requiring multiple registration captures per student.
                    if emb is not None and emb.size > 0:
                        try:
                            crop_bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR) if crop.shape[2] == 3 else crop
                            flipped_crop = cv2.flip(crop_bgr, 1)
                            flipped_rgb = cv2.cvtColor(flipped_crop, cv2.COLOR_BGR2RGB)
                            emb_flip = mfd_app.get_embedder().embed(flipped_rgb)
                            emb_flip = _normalize_vec(emb_flip)
                            if emb_flip.size == emb.size:
                                emb = _normalize_vec(emb + emb_flip)
                        except Exception:
                            pass
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

        # ── Always build raw-space per-person centroids ─────────────────────
        # Enables deterministic centroid-based matching even without the
        # triplet-trained projection W.  Each person is represented by 1
        # centroid (mean of their L2-normalized embeddings, re-normalized).
        if items:
            try:
                from embedding_cluster import build_person_centroids
                _raw_centroids = build_person_centroids(items)
                if _raw_centroids:
                    _VENDOR_EMB_CACHE[key]['raw_centroids'] = _raw_centroids
            except Exception:
                pass

        return _VENDOR_EMB_CACHE[key]
    except Exception as e:
        import traceback
        print(f"[_ensure_vendor_emb_cache] EXCEPTION: {e}", flush=True)
        traceback.print_exc()
        return None

def _suggest_via_projection(
    vec: np.ndarray,
    proj_W: np.ndarray,
    proj_centroids: dict,
    cache: dict,
    topk: int,
    struct_vec,
    class_year,
    division,
    branch,
) -> list:
    """
    Match a probe embedding against per-person projected centroids.

    Replaces the FAISS/linear-scan path when a trained projection W is
    available.  Each person is represented by a single centroid (mean of all
    their projected augmented embeddings) so matching is O(n_people).

    Similarity is cosine in projected space, rescaled to [0,1] via (s+1)/2.
    Scope filtering and contrastive refinement are identical to the raw path.
    Falls back gracefully (returns []) on any error so the caller can retry
    with the FAISS/linear path.
    """
    from metric_learning import project as _project
    proj_probe = _project(proj_W, vec)   # (PROJ_DIM,), unit-norm

    # One representative item per person (for scope / name / struct_vec lookup)
    person_meta: dict[int, dict] = {}
    for it in cache.get("items", []):
        pid = int(it["person_id"])
        if pid not in person_meta:
            person_meta[pid] = it

    target_year   = str(class_year or "").strip().lower()
    target_div    = str(division   or "").strip().lower()
    target_branch = str(branch     or "").strip().lower()
    scope_active  = bool(target_year or target_div or target_branch)

    raw = []
    for pid, centroid in proj_centroids.items():
        item = person_meta.get(pid)
        if item is None:
            continue

        # ── Scope filter (mirrors existing logic exactly) ────────────────
        if scope_active:
            item_year   = str(item.get("class_year") or "").strip().lower()
            item_div    = str(item.get("division")   or "").strip().lower()
            item_branch = str(item.get("branch")     or "").strip().lower()

            ok = True
            if target_year   and item_year   != target_year:   ok = False
            if target_div    and item_div    != target_div:    ok = False
            if target_branch and item_branch != target_branch: ok = False
            # Unassigned student matches any class scope
            if target_year and item_year == "":
                ok = True
            if not ok:
                continue

        # ── Cosine similarity in projected space → [0, 1] ────────────────
        proj_sim = float(np.dot(proj_probe, centroid))      # both unit-norm
        sim      = (proj_sim + 1.0) / 2.0                   # scale to [0, 1]

        # Structural similarity (diagnostic, not used for ranking)
        struct_sim = 0.0
        if struct_vec is not None and item.get("struct_vec") is not None:
            s_u = item["struct_vec"]
            if s_u.size == struct_vec.size > 0:
                struct_sim = float(np.dot(s_u, struct_vec))

        raw.append({
            "person_id":    pid,
            "name":         str(item.get("name", "Unknown")),
            "similarity":   sim,
            "arcface_pure": sim,
            "struct_pure":  struct_sim,
            "perfect_scope": True,
        })

    if not raw:
        return []

    raw.sort(key=lambda x: x["similarity"], reverse=True)

    # Dedup (centroid path already has one entry per person, but keep for safety)
    best: dict[int, dict] = {}
    for e in raw:
        pid = e["person_id"]
        if pid not in best or e["similarity"] > best[pid]["similarity"]:
            best[pid] = e
    deduped = sorted(best.values(), key=lambda x: x["similarity"], reverse=True)[: topk * 2]

    refined = _apply_contrastive_refinement(deduped)

    # Fetch face images and student metadata
    try:
        pids = [int(r["person_id"]) for r in refined]
        if pids:
            conn = get_db_connection()
            c    = conn.cursor()
            ph   = ",".join(["?"] * len(pids))
            c.execute(f"SELECT id, face_image, custom_data FROM faces WHERE id IN ({ph})", pids)
            imap = {int(row[0]): (row[1], row[2]) for row in (c.fetchall() or [])}
            conn.close()
            for r in refined:
                img, custom = imap.get(int(r["person_id"]), (None, None))
                r["face_image"] = img
                if custom:
                    try:
                        cd = json.loads(custom) if isinstance(custom, str) else custom
                        r["student_number"] = cd.get("student_id") or cd.get("student_number")
                    except Exception:
                        pass
    except Exception:
        pass

    return refined


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

        candidates = []
        if cache.get('faiss_index') is not None and USE_FAISS:
            try:
                q = v.reshape(1, -1).astype(np.float32)
                # Search more than topk to account for refinement and duplicates
                search_k = min(topk * 10, len(cache['items']))
                if _FAISS_LOCK:
                    with _FAISS_LOCK: D, I = cache['faiss_index'].search(q, search_k)
                else:
                    D, I = cache['faiss_index'].search(q, search_k)
                
                # FAISS map facilitates mapping indices to person_ids
                fmap = cache.get('faiss_map') or []
                for rank, idx in enumerate(I[0].tolist()):
                    if idx < 0 or idx >= len(fmap): continue
                    pid, nm = fmap[idx]
                    dot_val = float(D[0][rank]) if D is not None else 0.0
                    arcface_sim = (dot_val + 1.0) / 2.0
                    
                    # Match item for structural and scope data
                    item = next((x for x in cache['items'] if x['person_id'] == int(pid)), None)
                    if not item: continue

                    candidates.append((item, arcface_sim))
            except Exception: pass
        
        if not candidates:
            # ── Centroid-based fallback (replaces per-embedding linear scan) ──
            # Use raw-space centroids for deterministic matching: same probe
            # always matches the same centroid, eliminating score jitter.
            _raw_c = cache.get('raw_centroids')
            if _raw_c:
                from embedding_cluster import match_against_centroids as _match_c
                _c_results = _match_c(v, _raw_c, topk=topk * 3)
                for cr in _c_results:
                    # Find a representative item for scope/struct data
                    item = next((x for x in cache['items'] if x['person_id'] == cr['person_id']), None)
                    if item:
                        candidates.append((item, cr['similarity']))
            if not candidates:
                # Ultimate fallback: per-embedding linear scan (legacy path)
                candidates = [(it, (float(np.dot(it['vec'], v)) + 1.0) / 2.0) for it in cache['items']]

        raw = []
        for item, arcface_sim in candidates:
            # 1. SCOPE FILTERING (Case-insensitive & Robust)
            is_perfect = True
            
            # Use lowercase trimmed strings for comparison
            target_year = str(class_year or "").strip().lower()
            target_div = str(division or "").strip().lower()
            target_branch = str(branch or "").strip().lower()
            
            item_year = str(item.get('class_year') or "").strip().lower()
            item_div = str(item.get('division') or "").strip().lower()
            item_branch = str(item.get('branch') or "").strip().lower()

            if target_year and item_year != target_year: is_perfect = False
            if target_div and item_div != target_div: is_perfect = False
            if target_branch and item_branch != target_branch: is_perfect = False
            
            # Flexible filtering: If student has NO class assigned, they match ANY class filter 
            # (Matches 11b5fbd4 flexible behavior)
            if target_year and item_year == "": is_perfect = True
            
            # If a strict class scope was requested and this person is not in it, skip.
            if (target_year or target_div or target_branch) and not is_perfect:
                continue

            # 2. ADAPTIVE 3D MATCHING
            sim = arcface_sim
            struct_sim = 0.0
            if struct_vec is not None and item.get('struct_vec') is not None:
                s_u = item['struct_vec']
                if s_u.size == struct_vec.size and struct_vec.size > 0:
                    try:
                        # 3D Mesh Correlation (computed for diagnostics only)
                        struct_sim = float(np.dot(s_u, struct_vec))
                        # User requested disabling 3D logic for matching: relying 100% on ArcFace for distinct feature separation
                        sim = arcface_sim

                    except Exception: pass
            
            raw.append({
                'person_id': int(item['person_id']), 
                'name': str(item.get('name', 'Unknown')), 
                'similarity': sim,
                'arcface_pure': arcface_sim,
                'struct_pure': struct_sim,
                'perfect_scope': is_perfect
            })
            
        # Deduplicate and apply contrastive refinement (Separates top candidates)
        deduped = _dedup(raw, topk * 2) 
        refined = _apply_contrastive_refinement(deduped)
        
        # 3. IMAGE & METADATA FETCHING
        try:
            pids = [int(r['person_id']) for r in refined]
            if pids:
                conn = get_db_connection()
                c = conn.cursor()
                ph = ",".join(["?"]*len(pids))
                c.execute(f"SELECT id, face_image, custom_data FROM faces WHERE id IN ({ph})", pids)
                imap = {int(r[0]): (r[1], r[2]) for r in (c.fetchall() or [])}
                for r in refined:
                    img, custom = imap.get(int(r['person_id']), (None, None))
                    r['face_image'] = img
                    if custom:
                        try:
                            cd = json.loads(custom) if isinstance(custom, str) else custom
                            r['student_number'] = cd.get('student_id') or cd.get('student_number')
                        except Exception: pass
                conn.close()
        except Exception: pass
        
        return refined
    except Exception:
        return []

def _detect_faces_from_bytes(image_bytes: bytes, params: dict, vendor_id):
    try:
        _t0 = time.time()
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
        _t1 = time.time()
        print(f"[FACE_SVC] detect_faces took {_t1-_t0:.1f}s", flush=True)
        faces = []
        class_year = params.get('class_year'); division = params.get('division'); branch = params.get('branch')
        vcache = _ensure_vendor_emb_cache(vendor_id, class_year=class_year, division=division, branch=branch)
        if isinstance(annotated, tuple) and len(annotated) == 2:
            img_rgb, anns = annotated
            draw = cv2.cvtColor(img_rgb.copy(), cv2.COLOR_RGB2BGR)
            
            # ── Phase A: Batch-draw ALL 3D meshes on annotated image at once ──
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
            mesh_drawn = 0
            for i, ann in enumerate(anns or []):
                if df is not None and hasattr(df, 'iloc') and i < len(df):
                    row = df.iloc[i]
                    landmarks_3d = row.get('landmarks_3d', [])
                else:
                    landmarks_3d = []
                if landmarks_3d is not None and len(landmarks_3d) >= 68:
                    try:
                        pts_2d_global = [(int(pt[0]), int(pt[1])) for pt in landmarks_3d]
                        for indices, color, _ in _MESH_REGIONS:
                            for k in range(len(indices) - 1):
                                p1 = pts_2d_global[indices[k]]
                                p2 = pts_2d_global[indices[k + 1]]
                                cv2.line(draw, p1, p2, color, 3, cv2.LINE_AA)
                        # Z-depth coloring
                        pts_z = [float(pt[2]) if len(pt) > 2 else 0.0 for pt in landmarks_3d]
                        z_min, z_max = min(pts_z), max(pts_z)
                        z_range = max(z_max - z_min, 1.0)
                        for idx, (px, py) in enumerate(pts_2d_global):
                            t = (pts_z[idx] - z_min) / z_range
                            dot_color = (int(255 * t), int(220 * (1 - t)), int(60 + 60 * (1 - t)))
                            cv2.circle(draw, (px, py), 6, dot_color, -1, cv2.LINE_AA)
                        mesh_drawn += 1
                    except Exception:
                        pass
            if mesh_drawn > 0:
                print(f"[FACE_SVC] Drew 68-pt mesh for {mesh_drawn} faces (batch).", flush=True)

            # ── Phase B: Per-face thumbnail generation & embeddings ──
            face_data = []
            embeddings_map = {} # {local_index: emb_norm}
            for i, ann in enumerate(anns or []):
                # ann is now a dict: {"box": [x1,y1,x2,y2], "score": float, "landmarks_5": [...]}
                box = ann.get('box', [0,0,0,0])
                score_str = str(ann.get('score', 0.0))
                # Skip drawing the portrait box from ann['box'], calculate true face box first
                if i < len(crops):
                    ih, iw = img_rgb.shape[:2]
                    if df is not None and hasattr(df, 'iloc') and i < len(df):
                        row = df.iloc[i]
                        bx1, by1, bx2, by2 = int(row['x1']), int(row['y1']), int(row['x2']), int(row['y2'])
                        landmarks_3d = row.get('landmarks_3d', [])
                    else:
                        bx1, by1, bx2, by2 = [int(v) for v in box]
                        landmarks_3d = []
                    
                    
                    # ── False-Positive Gate ──
                    # No 3D landmarks → back-of-head, partial profile, or background blob.
                    if landmarks_3d is None or len(landmarks_3d) == 0:
                        continue
                    # Aspect ratio gate: a valid face box is roughly square (0.5–2.0).
                    # Ears, shoulders, and other body parts produce very narrow boxes
                    # (width/height < 0.4 or > 2.5) and should be discarded.
                    _fw = bx2 - bx1; _fh = by2 - by1
                    if _fh > 0 and not (0.4 <= (_fw / _fh) <= 2.5):
                        continue
                    
                    cv2.rectangle(draw, (bx1, by1), (bx2, by2), (0, 180, 255), 2)
                    
                    bx1 = max(0, bx1); by1 = max(0, by1); bx2 = min(iw, bx2); by2 = min(ih, by2)
                    cx1, cy1, cx2, cy2 = mfd_app._compute_centered_box(bx1, by1, bx2, by2, iw, ih, scale=1.2)
                    pure_face = img_rgb[cy1:cy2, cx1:cx2]
                    
                    if pure_face.size > 0:
                        lmks_local = None
                        try:
                            # For thumbnail mesh and embeddings, we need crop-local landmarks
                            lmks_local = np.array(landmarks_3d).copy()
                            lmks_local[:, 0] -= cx1
                            lmks_local[:, 1] -= cy1
                        except Exception as e:
                            print(f"[FACE_SVC] Error processing landmarks: {e}", flush=True)
                        
                        # Adaptive upscaling: determine scale factor from face pixel size
                        _face_min_side = min(pure_face.shape[:2])
                        if _face_min_side < 80:
                            _up_scale = 4
                        elif _face_min_side < 160:
                            _up_scale = 2
                        else:
                            _up_scale = 1

                        # Use pre-computed batch embedding only for normal-sized faces.
                        # Tiny/small faces need adaptive upscale + GFPGAN for accurate ArcFace input.
                        emb_norm = None
                        if df_emb is not None and i < len(df_emb) and _up_scale == 1:
                            emb_norm = df_emb[i]
                            _, face_display = mfd_app.prepare_embedding_crop(pure_face, lmks_local, skip_enhancement=True)

                        if emb_norm is None:
                            embed_face = pure_face
                            embed_lmks = lmks_local
                            # RealESRGAN upscale for small faces — preserves real pixel structure,
                            # no hallucination risk. Skip in fast mode for speed.
                            if _up_scale > 1 and not fast:
                                try:
                                    embed_face = mfd_app.get_realesrgan_manager().upscale(embed_face, scale=_up_scale)
                                    if embed_lmks is not None:
                                        embed_lmks = embed_lmks.copy()
                                        embed_lmks[:, 0] *= _up_scale
                                        embed_lmks[:, 1] *= _up_scale
                                except Exception:
                                    pass
                            # Never run GFPGAN for embedding — it regenerates face structure from a GAN
                            # prior and embeds invented features, not the real person's geometry.
                            # Real-ESRGAN above is sufficient: it upscales without synthesizing.
                            emb_crop_112, face_display = mfd_app.prepare_embedding_crop(embed_face, embed_lmks, skip_enhancement=True)
                            emb = mfd_app.get_embedder().embed(emb_crop_112)
                            emb_norm = _normalize_vec(emb)
                            # TTA: embed horizontally flipped crop and average with original.
                            # Robustifies matching against slightly turned faces — the gallery
                            # has one frontal photo per person; the averaged embedding bridges
                            # the gap to mild left/right turns without extra registration cost.
                            if emb_norm.size > 0:
                                try:
                                    flipped_112 = cv2.flip(emb_crop_112, 1)
                                    emb_flip = mfd_app.get_embedder().embed(flipped_112)
                                    emb_flip = _normalize_vec(emb_flip)
                                    if emb_flip.size == emb_norm.size:
                                        emb_norm = _normalize_vec(emb_norm + emb_flip)
                                except Exception:
                                    pass

                        # Extract Structural Vector
                        struct_vec_val = None
                        struct_vec_b64 = ''
                        if landmarks_3d is not None and len(landmarks_3d) > 0:
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

                        # Portrait thumbnail: smooth ALL faces for natural display
                        try:
                            px1, py1, px2, py2 = mfd_app._compute_portrait_box(bx1, by1, bx2, by2, iw, ih, scale=3.0, margin=0.5)
                            portrait = img_rgb[py1:py2, px1:px2]
                            
                            is_tiny = min(bx2-bx1, by2-by1) < 60
                            
                            if portrait.size > 0 and fast:
                                # ALWAYS smooth in fast mode — this is lightweight CV (~10ms/face)
                                ph, pw = portrait.shape[:2]
                                min_portrait_dim = min(ph, pw)
                                
                                # Step 1: Upscale small portraits for smooth display
                                if min_portrait_dim < 200:
                                    scale = max(2, int(np.ceil(200 / min_portrait_dim)))
                                    portrait_enh = cv2.resize(portrait, (pw * scale, ph * scale), interpolation=cv2.INTER_LANCZOS4)
                                else:
                                    portrait_enh = portrait.copy()
                                
                                # Step 2: Bilateral filter — smooths noise while keeping edges
                                portrait_enh = cv2.bilateralFilter(portrait_enh, 9, 75, 75)
                                
                                # Step 3: Light Gaussian blur to remove remaining blockiness
                                portrait_enh = cv2.GaussianBlur(portrait_enh, (3, 3), 0.5)
                            elif portrait.size > 0 and (is_blurry or is_tiny):
                                # Blurry/tiny portrait: Real-ESRGAN upscale + CLAHE + bilateral.
                                # Replaced GFPGAN here — it hallucinated facial structure on
                                # low-quality crops, making displayed faces look uncanny.
                                ph2, pw2 = portrait.shape[:2]
                                min_dim2 = min(ph2, pw2)
                                if min_dim2 < 160:
                                    up2 = max(2, int(np.ceil(160 / min_dim2)))
                                    try:
                                        portrait = mfd_app.get_realesrgan_manager().upscale(portrait, scale=up2)
                                    except Exception:
                                        portrait = cv2.resize(portrait, (pw2 * up2, ph2 * up2), interpolation=cv2.INTER_LANCZOS4)
                                portrait_lab = cv2.cvtColor(portrait, cv2.COLOR_RGB2LAB)
                                l_ch, a_ch, b_ch = cv2.split(portrait_lab)
                                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
                                l_ch = clahe.apply(l_ch)
                                portrait_lab = cv2.merge([l_ch, a_ch, b_ch])
                                portrait = cv2.cvtColor(portrait_lab, cv2.COLOR_LAB2RGB)
                                portrait_enh = cv2.bilateralFilter(portrait, 9, 60, 60)
                            else:
                                portrait_enh = portrait.copy() if portrait.size > 0 else None

                            # Draw 3D Landmarks on the portrait thumbnail for immediate visual feedback in the UI gallery
                            if portrait_enh is not None and landmarks_3d is not None and len(landmarks_3d) > 0:
                                try:
                                    for pt in landmarks_3d:
                                        # Map global coordinates to portrait-local coordinates
                                        lpx, lpy = int(pt[0] - px1), int(pt[1] - py1)
                                        if 0 <= lpx < portrait_enh.shape[1] and 0 <= lpy < portrait_enh.shape[0]:
                                            # Radius 3 for thumbnails (half of the global radius 6)
                                            cv2.circle(portrait_enh, (lpx, lpy), 3, (0, 255, 0), -1)
                                except Exception as e:
                                    print(f"[FACE_SVC] Thumbnail landmark error: {e}", flush=True)
                        except Exception:
                            portrait_enh = None

                        # ── Smooth the FACE thumbnail (this is what the UI actually shows!) ──
                        # face_display from prepare_embedding_crop is a raw crop — needs smoothing
                        if fast and face_display is not None and face_display.size > 0:
                            fd_h, fd_w = face_display.shape[:2]
                            fd_min = min(fd_h, fd_w)
                            if fd_min < 200:
                                fd_scale = max(2, int(np.ceil(200 / fd_min)))
                                face_display = cv2.resize(face_display, (fd_w * fd_scale, fd_h * fd_scale), interpolation=cv2.INTER_LANCZOS4)
                            face_display = cv2.bilateralFilter(face_display, 9, 75, 75)
                            face_display = cv2.GaussianBlur(face_display, (3, 3), 0.5)

                        # Encode thumbnails
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
                            "landmarks_3d": landmarks_3d.tolist() if hasattr(landmarks_3d, 'tolist') else landmarks_3d,
                            "emb_norm": emb_norm, # Internal use
                            "struct_vec_val": struct_vec_val # Internal use
                        }
                        face_data.append(f_entry)
                        if emb_norm.size > 0:
                            embeddings_map[len(face_data)-1] = emb_norm

            # Step 2: Intra-batch Clustering
            # 0.83: looser than the old 0.90 so multiple crops of the same student
            # in different poses/lighting get grouped before matching. At 0.90 the
            # same person shot from slightly different angles was treated as two
            # separate unknowns and each fell below the confidence threshold alone.
            clusters = _cluster_batch_embeddings(embeddings_map, threshold=0.83)

            # Step 3: Identify Clusters and Assign suggestions
            for cluster in clusters:
                centroid = cluster['centroid']
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

            # Step 4: Fallback for any non-clustered faces
            for f in face_data:
                if 'suggestions' not in f:
                    f['suggestions'] = _suggest_from_cache(f['emb_norm'], vcache, topk=3, struct_vec=f['struct_vec_val'], class_year=class_year, division=division, branch=branch)
                if 'emb_norm' in f: del f['emb_norm']
                if 'struct_vec_val' in f: del f['struct_vec_val']

            # Step 5: Quality-aware suggestion gate — raise the bar for blurry / extreme-pose faces
            for f in face_data:
                f_sharpness  = f.get('sharpness', 999.0)
                f_lmks       = f.get('landmarks_3d')
                f_det_score  = float(f.get('score') or 1.0)
                pose_yaw     = _estimate_pose_yaw(f_lmks) if f_lmks else 0.0
                f['pose_yaw'] = round(pose_yaw, 3)
                # Hard pose rejection: yaw > 0.55 means ~50°+ turn (near-profile).
                # ArcFace embeddings for near-profile faces are too far from the
                # frontal gallery embedding to produce reliable matches — returning
                # ambiguous suggestions is worse than returning none at all.
                if pose_yaw > 0.55:
                    f['suggestions'] = []
                    f['min_sim'] = 1.0
                    continue
                min_sim      = _quality_min_sim(f_sharpness, pose_yaw, f_det_score)
                f['min_sim']   = round(min_sim, 3)
                if f.get('suggestions'):
                    f['suggestions'] = [s for s in f['suggestions'] if s['similarity'] >= min_sim]

            # Second-stage filter: only keep faces the 3D engine confirmed as real.
            # A face with no landmarks_3d is almost certainly a detector false positive
            # (background blob, partial body part, etc.).
            # Guard: if the 3D engine isn't running at all (no face has landmarks),
            # skip filtering so the UI still shows something.
            has_any_landmarks = any(f.get('landmarks_3d') is not None and len(f.get('landmarks_3d')) > 0 for f in face_data)
            faces = [f for f in face_data if f.get('landmarks_3d') is not None and len(f.get('landmarks_3d')) > 0] if has_any_landmarks else face_data

            ok2, ann = cv2.imencode('.jpg', draw, [cv2.IMWRITE_JPEG_QUALITY, 85])
            annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(ann.tobytes()).decode('ascii')}" if ok2 else ''
            _t2 = time.time()
            print(f"[FACE_SVC] Per-face processing took {_t2-_t1:.1f}s for {len(faces)} faces", flush=True)
        else:
            annotated_b64 = ''
        return faces, annotated_b64
    except Exception as e:
        import traceback
        pass # print(f"[FACE_DETECT] ERROR: {e}", flush=True)
        traceback.print_exc()
        return [], ''
