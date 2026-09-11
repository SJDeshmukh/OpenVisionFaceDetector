"""Validation and decoding for Android face-template serialization formats."""

import base64
import struct

import numpy as np


EMBEDDING_DIMENSION = 512
FID1_FAMILY = "mobilefacenet-arcface-v1"
LEGACY_RAW_FAMILY = "legacy-raw"


def decode_face_template(encoded):
    """Return a normalized float vector and its model/serialization family."""
    if not isinstance(encoded, str) or not encoded.strip():
        raise ValueError("Face template is empty")
    raw = base64.b64decode(encoded, validate=True)
    if raw.startswith(b"FID1"):
        if len(raw) < 8:
            raise ValueError("Truncated FID1 template")
        dimension = struct.unpack(">I", raw[4:8])[0]
        if dimension != EMBEDDING_DIMENSION or len(raw) != 8 + dimension * 4:
            raise ValueError("Invalid FID1 template dimensions")
        vector = np.frombuffer(raw[8:], dtype=">f4").astype(np.float32)
        family = FID1_FAMILY
    else:
        if len(raw) != EMBEDDING_DIMENSION * 4:
            raise ValueError("Unsupported legacy template dimensions")
        vector = np.frombuffer(raw, dtype=np.float32).copy()
        family = LEGACY_RAW_FAMILY
    if not np.all(np.isfinite(vector)):
        raise ValueError("Template contains non-finite values")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm < 1e-8:
        raise ValueError("Template has zero magnitude")
    return vector / norm, family
