"""Cross-entity duplicate face detection service.

Enforces vector cosine similarity checks across:
1. Student enrollment vs Active Parents (parent_users)
2. Student enrollment vs Existing Students/Residents (faces)
3. Parent enrollment vs Active Students/Residents (faces)
4. Parent enrollment vs Other Parents (parent_users)
"""

import base64
import json
import logging
import struct
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSION = 512
FAMILY_FID1 = "mobilefacenet-arcface-v1"
FAMILY_SERVER = "server-arcface"

# Cosine similarity thresholds
# 0.60 corresponds to ArcFace scaled similarity ~0.80, with FMR < 0.001%
SIMILARITY_THRESHOLD_PARENT_STUDENT = 0.60
SIMILARITY_THRESHOLD_STUDENT_STUDENT = 0.62
SIMILARITY_THRESHOLD_PARENT_PARENT = 0.60


def decode_single_vector(encoded):
    """
    Decodes a single vector from bytes, base64 string, or float array.
    Returns: (normalized_vector: np.ndarray, family: str) or None.
    """
    if encoded is None:
        return None
    try:
        # If already a numpy array
        if isinstance(encoded, np.ndarray):
            vec = encoded.astype(np.float32).flatten()
            if len(vec) != EMBEDDING_DIMENSION:
                return None
            norm = float(np.linalg.norm(vec))
            if norm < 1e-8 or not np.all(np.isfinite(vec)):
                return None
            return vec / norm, FAMILY_SERVER

        # If list / tuple of floats
        if isinstance(encoded, (list, tuple)):
            if len(encoded) == 0:
                return None
            # If it's a list containing a base64 string, recurse
            if isinstance(encoded[0], str):
                return decode_single_vector(encoded[0])
            vec = np.array(encoded, dtype=np.float32).flatten()
            if len(vec) != EMBEDDING_DIMENSION:
                return None
            norm = float(np.linalg.norm(vec))
            if norm < 1e-8 or not np.all(np.isfinite(vec)):
                return None
            return vec / norm, FAMILY_SERVER

        # If bytes or base64 string
        if isinstance(encoded, bytes):
            raw = encoded
        elif isinstance(encoded, str):
            encoded = encoded.strip()
            if not encoded:
                return None
            raw = base64.b64decode(encoded)
        else:
            return None

        # Check for FID1 header (4 bytes 'FID1' + 4 bytes dimension + 512*4 bytes)
        if raw.startswith(b"FID1"):
            if len(raw) < 8:
                return None
            dimension = struct.unpack(">I", raw[4:8])[0]
            if dimension != EMBEDDING_DIMENSION or len(raw) != 8 + dimension * 4:
                return None
            vec = np.frombuffer(raw[8:], dtype=">f4").astype(np.float32)
            family = FAMILY_FID1
        elif len(raw) == EMBEDDING_DIMENSION * 4:
            # 2048 bytes of float32 (server embedder format)
            vec = np.frombuffer(raw, dtype=np.float32).copy()
            family = FAMILY_SERVER
        else:
            return None

        if not np.all(np.isfinite(vec)):
            return None
        norm = float(np.linalg.norm(vec))
        if norm < 1e-8 or not np.isfinite(norm):
            return None
        return vec / norm, family
    except Exception as e:
        return None


def extract_vectors_from_payload(payload):
    """
    Extracts all valid (vector, family) tuples from a payload which could be:
    - Base64 string (single vector or FID1)
    - JSON string of list of base64 strings
    - List of base64 strings or float arrays
    - bytes blob
    """
    if not payload:
        return []
    results = []

    if isinstance(payload, str):
        payload_str = payload.strip()
        if payload_str.startswith("["):
            try:
                items = json.loads(payload_str)
                if isinstance(items, list):
                    for item in items:
                        v = decode_single_vector(item)
                        if v:
                            results.append(v)
                    return results
            except Exception:
                pass
        v = decode_single_vector(payload_str)
        if v:
            results.append(v)
        return results

    if isinstance(payload, (list, tuple)):
        for item in payload:
            v = decode_single_vector(item)
            if v:
                results.append(v)
        return results

    if isinstance(payload, bytes):
        v = decode_single_vector(payload)
        if v:
            results.append(v)
        return results

    return results


def compute_max_vector_similarity(vectors_a, vectors_b):
    """
    Computes maximum cosine similarity between two vector sets where model family matches.
    Returns max_similarity (float).
    """
    if not vectors_a or not vectors_b:
        return 0.0
    best_sim = -1.0
    for vec_a, fam_a in vectors_a:
        for vec_b, fam_b in vectors_b:
            if fam_a == fam_b:
                sim = float(np.dot(vec_a, vec_b))
                if sim > best_sim:
                    best_sim = sim
    return max(best_sim, 0.0)


def extract_server_vector_from_image(face_image, vendor_id=None):
    """Fallback helper to extract server embedding from a base64 image or data URI."""
    if not face_image:
        return None
    try:
        from services.face_service import _decode_data_uri_to_rgb, _normalize_vec
        from multiple_face_detection import app as mfd_app

        img_rgb = _decode_data_uri_to_rgb(face_image)
        if img_rgb is not None:
            emb = mfd_app.get_embedder().embed(img_rgb)
            if emb is not None and emb.size > 0:
                vec = _normalize_vec(emb)
                return (vec, FAMILY_SERVER)
    except Exception as e:
        logger.warning(f"Failed to extract server vector from image: {e}")
    return None


def check_student_face_duplicate(conn, vendor_id, candidate_vectors, candidate_image=None, exclude_person_id=None):
    """
    Checks if a candidate student face duplicates:
    1. Any active parent in parent_users (similarity >= 0.60)
    2. Any existing active person in faces (similarity >= 0.62)
    Returns: (is_duplicate: bool, error_message: str or None)
    """
    if not vendor_id:
        return False, None

    candidate_vecs = list(candidate_vectors or [])
    if not candidate_vecs and candidate_image:
        sv = extract_server_vector_from_image(candidate_image, vendor_id)
        if sv:
            candidate_vecs.append(sv)

    if not candidate_vecs:
        return False, None

    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    # 1. Check against PARENT_USERS
    # A student can NEVER share a face with any registered parent for this vendor
    try:
        if is_pg:
            c.execute("""
                SELECT id, username, student_number, contact_phone, face_template, face_server_template, face_image
                FROM parent_users
                WHERE vendor_id = %s AND (face_template IS NOT NULL OR face_server_template IS NOT NULL OR face_image IS NOT NULL)
            """, (vendor_id,))
        else:
            c.execute("""
                SELECT id, username, student_number, contact_phone, face_template, face_server_template, face_image
                FROM parent_users
                WHERE vendor_id = ? AND (face_template IS NOT NULL OR face_server_template IS NOT NULL OR face_image IS NOT NULL)
            """, (vendor_id,))

        parent_rows = c.fetchall() or []
        for prow in parent_rows:
            p_user = prow[1] if not isinstance(prow, dict) else prow.get("username")
            p_sn = prow[2] if not isinstance(prow, dict) else prow.get("student_number")
            p_template = prow[4] if not isinstance(prow, dict) else prow.get("face_template")
            p_server_template = prow[5] if not isinstance(prow, dict) else prow.get("face_server_template")
            p_image = prow[6] if not isinstance(prow, dict) else prow.get("face_image")

            parent_vecs = []
            if p_server_template:
                parent_vecs.extend(extract_vectors_from_payload(p_server_template))
            if p_template:
                parent_vecs.extend(extract_vectors_from_payload(p_template))
            if not parent_vecs and p_image:
                pv = extract_server_vector_from_image(p_image, vendor_id)
                if pv:
                    parent_vecs.append(pv)

            sim = compute_max_vector_similarity(candidate_vecs, parent_vecs)
            if sim >= SIMILARITY_THRESHOLD_PARENT_STUDENT:
                sn_info = f" (Student ID: {p_sn})" if p_sn else ""
                logger.warning(f"[DUPLICATE_FACE] Student enrollment blocked: matches parent '{p_user}' (sim={sim:.3f})")
                return True, (
                    f"Duplicate face detected: This face is already registered to a parent account "
                    f"'{p_user}'{sn_info}. A student cannot be registered with the same face as a parent."
                )
    except Exception as e:
        logger.error(f"[DUPLICATE_CHECK] Error checking parent_users: {e}", exc_info=True)

    # 2. Check against FACES (existing active students/residents/employees)
    try:
        if is_pg:
            c.execute("""
                SELECT id, name, templates, custom_data
                FROM faces
                WHERE vendor_id = %s AND (student_status IS NULL OR student_status <> 'deleted')
            """, (vendor_id,))
        else:
            c.execute("""
                SELECT id, name, templates, custom_data
                FROM faces
                WHERE vendor_id = ? AND (student_status IS NULL OR student_status <> 'deleted')
            """, (vendor_id,))

        face_rows = c.fetchall() or []
        for frow in face_rows:
            f_id = frow[0] if not isinstance(frow, dict) else frow.get("id")
            if exclude_person_id and str(f_id) == str(exclude_person_id):
                continue
            f_name = frow[1] if not isinstance(frow, dict) else frow.get("name")
            f_templates = frow[2] if not isinstance(frow, dict) else frow.get("templates")

            existing_vecs = extract_vectors_from_payload(f_templates)
            sim = compute_max_vector_similarity(candidate_vecs, existing_vecs)
            if sim >= SIMILARITY_THRESHOLD_STUDENT_STUDENT:
                logger.warning(f"[DUPLICATE_FACE] Student enrollment blocked: matches existing person '{f_name}' (sim={sim:.3f})")
                return True, f"Duplicate face detected: This face is already registered to '{f_name}'."
    except Exception as e:
        logger.error(f"[DUPLICATE_CHECK] Error checking faces: {e}", exc_info=True)

    return False, None


def check_parent_face_duplicate(conn, vendor_id, parent_id, candidate_vectors, candidate_image=None):
    """
    Checks if a candidate parent face duplicates:
    1. Any active student/resident in faces (similarity >= 0.60)
    2. Any other parent in parent_users (similarity >= 0.60)
    Returns: (is_duplicate: bool, error_message: str or None)
    """
    if not vendor_id:
        return False, None

    candidate_vecs = list(candidate_vectors or [])
    if not candidate_vecs and candidate_image:
        sv = extract_server_vector_from_image(candidate_image, vendor_id)
        if sv:
            candidate_vecs.append(sv)

    if not candidate_vecs:
        return False, None

    is_pg = getattr(conn, "_is_pg", False)
    c = conn.cursor()

    # 1. Check against FACES (students cannot register as parents)
    try:
        if is_pg:
            c.execute("""
                SELECT id, name, templates
                FROM faces
                WHERE vendor_id = %s AND (student_status IS NULL OR student_status <> 'deleted')
            """, (vendor_id,))
        else:
            c.execute("""
                SELECT id, name, templates
                FROM faces
                WHERE vendor_id = ? AND (student_status IS NULL OR student_status <> 'deleted')
            """, (vendor_id,))

        rows = c.fetchall() or []
        for r in rows:
            s_name = r[1] if not isinstance(r, dict) else r.get("name")
            s_templates = r[2] if not isinstance(r, dict) else r.get("templates")
            s_vecs = extract_vectors_from_payload(s_templates)
            sim = compute_max_vector_similarity(candidate_vecs, s_vecs)
            if sim >= SIMILARITY_THRESHOLD_PARENT_STUDENT:
                logger.warning(f"[DUPLICATE_FACE] Parent registration blocked: matches student '{s_name}' (sim={sim:.3f})")
                return True, (
                    f"Violation: This face is already registered to student '{s_name}'. "
                    f"A parent cannot have the same face as a student."
                )
    except Exception as e:
        logger.error(f"[DUPLICATE_CHECK] Error checking parent against faces: {e}", exc_info=True)

    # 2. Check against OTHER PARENTS in parent_users
    try:
        if is_pg:
            c.execute("""
                SELECT id, username, student_number, face_template, face_server_template, face_image
                FROM parent_users
                WHERE vendor_id = %s AND id <> %s
                  AND (face_template IS NOT NULL OR face_server_template IS NOT NULL OR face_image IS NOT NULL)
            """, (vendor_id, parent_id))
        else:
            c.execute("""
                SELECT id, username, student_number, face_template, face_server_template, face_image
                FROM parent_users
                WHERE vendor_id = ? AND id <> ?
                  AND (face_template IS NOT NULL OR face_server_template IS NOT NULL OR face_image IS NOT NULL)
            """, (vendor_id, parent_id))

        other_parents = c.fetchall() or []
        for op in other_parents:
            op_user = op[1] if not isinstance(op, dict) else op.get("username")
            op_sn = op[2] if not isinstance(op, dict) else op.get("student_number")
            op_tpl = op[3] if not isinstance(op, dict) else op.get("face_template")
            op_srv_tpl = op[4] if not isinstance(op, dict) else op.get("face_server_template")
            op_img = op[5] if not isinstance(op, dict) else op.get("face_image")

            op_vecs = []
            if op_srv_tpl:
                op_vecs.extend(extract_vectors_from_payload(op_srv_tpl))
            if op_tpl:
                op_vecs.extend(extract_vectors_from_payload(op_tpl))
            if not op_vecs and op_img:
                pv = extract_server_vector_from_image(op_img, vendor_id)
                if pv:
                    op_vecs.append(pv)

            sim = compute_max_vector_similarity(candidate_vecs, op_vecs)
            if sim >= SIMILARITY_THRESHOLD_PARENT_PARENT:
                sn_info = f" (Student ID: {op_sn})" if op_sn else ""
                logger.warning(f"[DUPLICATE_FACE] Parent registration blocked: matches other parent '{op_user}' (sim={sim:.3f})")
                return True, (
                    f"Violation: This face is already registered to another parent account "
                    f"'{op_user}'{sn_info}."
                )
    except Exception as e:
        logger.error(f"[DUPLICATE_CHECK] Error checking other parents: {e}", exc_info=True)

    return False, None
