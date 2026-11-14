import base64
import struct
import numpy as np
import pytest

from services.face_duplicate_service import (
    EMBEDDING_DIMENSION,
    FAMILY_FID1,
    FAMILY_SERVER,
    decode_single_vector,
    extract_vectors_from_payload,
    compute_max_vector_similarity,
    check_student_face_duplicate,
    check_parent_face_duplicate,
)


def _make_unit_vector(seed=42):
    rng = np.random.RandomState(seed)
    vec = rng.randn(EMBEDDING_DIMENSION).astype(np.float32)
    return vec / np.linalg.norm(vec)


def _to_fid1_base64(unit_vec):
    payload = b"FID1" + struct.pack(">I", 512) + unit_vec.astype(">f4").tobytes()
    return base64.b64encode(payload).decode("ascii")


def _to_server_base64(unit_vec):
    payload = unit_vec.astype(np.float32).tobytes()
    return base64.b64encode(payload).decode("ascii")


def test_decode_fid1_template():
    vec = _make_unit_vector(1)
    b64 = _to_fid1_base64(vec)
    res = decode_single_vector(b64)
    assert res is not None
    decoded_vec, family = res
    assert family == FAMILY_FID1
    np.testing.assert_allclose(decoded_vec, vec, atol=1e-6)


def test_decode_server_template():
    vec = _make_unit_vector(2)
    b64 = _to_server_base64(vec)
    res = decode_single_vector(b64)
    assert res is not None
    decoded_vec, family = res
    assert family == FAMILY_SERVER
    np.testing.assert_allclose(decoded_vec, vec, atol=1e-6)


def test_extract_vectors_from_json_list():
    vec1 = _make_unit_vector(10)
    vec2 = _make_unit_vector(20)
    import json
    json_str = json.dumps([_to_server_base64(vec1), _to_fid1_base64(vec2)])
    vecs = extract_vectors_from_payload(json_str)
    assert len(vecs) == 2
    assert vecs[0][1] == FAMILY_SERVER
    assert vecs[1][1] == FAMILY_FID1


def test_similarity_same_vector():
    vec = _make_unit_vector(100)
    v1 = [(vec, FAMILY_SERVER)]
    v2 = [(vec, FAMILY_SERVER)]
    sim = compute_max_vector_similarity(v1, v2)
    assert abs(sim - 1.0) < 1e-5


def test_similarity_different_families_does_not_match():
    vec = _make_unit_vector(100)
    v1 = [(vec, FAMILY_SERVER)]
    v2 = [(vec, FAMILY_FID1)]
    sim = compute_max_vector_similarity(v1, v2)
    assert sim == 0.0


def test_similarity_orthogonal_vectors():
    vec1 = np.zeros(512, dtype=np.float32)
    vec1[0] = 1.0
    vec2 = np.zeros(512, dtype=np.float32)
    vec2[1] = 1.0
    sim = compute_max_vector_similarity([(vec1, FAMILY_SERVER)], [(vec2, FAMILY_SERVER)])
    assert abs(sim) < 1e-6


class MockCursor:
    def __init__(self, parent_rows=None, face_rows=None):
        self.parent_rows = parent_rows or []
        self.face_rows = face_rows or []
        self.last_query = ""

    def execute(self, query, params=None):
        self.last_query = query.lower()

    def fetchall(self):
        if "from parent_users" in self.last_query:
            return self.parent_rows
        if "from faces" in self.last_query:
            return self.face_rows
        return []


class MockConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self._is_pg = False

    def cursor(self):
        return self._cursor


def test_check_student_face_duplicate_blocks_parent_face():
    # Parent has face A
    face_a = _make_unit_vector(111)
    parent_rows = [
        (1, "parent_ganesh", "RES20260002", "9999999999", None, _to_server_base64(face_a), None)
    ]
    cursor = MockCursor(parent_rows=parent_rows, face_rows=[])
    conn = MockConn(cursor)

    candidate = [(face_a, FAMILY_SERVER)]
    is_dup, msg = check_student_face_duplicate(conn, vendor_id=1, candidate_vectors=candidate)
    assert is_dup is True
    assert "parent account 'parent_ganesh'" in msg


def test_check_student_face_duplicate_blocks_existing_student():
    face_b = _make_unit_vector(222)
    face_rows = [
        (10, "Aditi Iyer", _to_server_base64(face_b), {})
    ]
    cursor = MockCursor(parent_rows=[], face_rows=face_rows)
    conn = MockConn(cursor)

    candidate = [(face_b, FAMILY_SERVER)]
    is_dup, msg = check_student_face_duplicate(conn, vendor_id=1, candidate_vectors=candidate)
    assert is_dup is True
    assert "already registered to 'Aditi Iyer'" in msg


def test_check_parent_face_duplicate_blocks_student_face():
    face_c = _make_unit_vector(333)
    face_rows = [
        (10, "Aarav Sharma", _to_server_base64(face_c), {})
    ]
    cursor = MockCursor(parent_rows=[], face_rows=face_rows)
    conn = MockConn(cursor)

    candidate = [(face_c, FAMILY_SERVER)]
    is_dup, msg = check_parent_face_duplicate(conn, vendor_id=1, parent_id=99, candidate_vectors=candidate)
    assert is_dup is True
    assert "already registered to student 'Aarav Sharma'" in msg
