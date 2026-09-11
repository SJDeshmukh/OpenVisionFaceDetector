import base64
import struct

import numpy as np
import pytest

from services.mobile_face_template import (
    FID1_FAMILY,
    LEGACY_RAW_FAMILY,
    decode_face_template,
)


def _unit_vector():
    vector = np.arange(1, 513, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_decodes_versioned_android_template():
    expected = _unit_vector()
    payload = b"FID1" + struct.pack(">I", 512) + expected.astype(">f4").tobytes()

    actual, family = decode_face_template(base64.b64encode(payload).decode("ascii"))

    assert family == FID1_FAMILY
    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-7)


def test_decodes_legacy_native_float_template_separately():
    expected = _unit_vector()
    payload = expected.astype(np.float32).tobytes()

    actual, family = decode_face_template(base64.b64encode(payload).decode("ascii"))

    assert family == LEGACY_RAW_FAMILY
    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-7)


@pytest.mark.parametrize("payload", [b"", b"FID1", bytes(2048), b"not-a-template"])
def test_rejects_malformed_or_zero_templates(payload):
    with pytest.raises(ValueError):
        decode_face_template(base64.b64encode(payload).decode("ascii"))


def test_rejects_non_finite_values():
    vector = _unit_vector()
    vector[10] = np.nan
    payload = b"FID1" + struct.pack(">I", 512) + vector.astype(">f4").tobytes()

    with pytest.raises(ValueError):
        decode_face_template(base64.b64encode(payload).decode("ascii"))
