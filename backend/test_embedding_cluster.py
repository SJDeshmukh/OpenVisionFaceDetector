"""
Unit tests for embedding_cluster.py

Tests centroid computation, deterministic matching, and embedding validation.
Run: python test_embedding_cluster.py
"""

import sys
import os
import numpy as np

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from embedding_cluster import (
    compute_centroid,
    build_person_centroids,
    match_against_centroids,
    validate_embedding,
    _l2_normalize,
)


def _make_person_embeddings(base_vec, n=5, noise=0.05):
    """Create n embeddings near base_vec with small random perturbations."""
    vecs = []
    rng = np.random.default_rng(42)
    for _ in range(n):
        v = base_vec + rng.normal(0, noise, size=base_vec.shape)
        v = (v / np.linalg.norm(v)).astype(np.float32)
        vecs.append(v)
    return vecs


def test_compute_centroid():
    """Centroid should be unit-norm and close to the mean direction."""
    rng = np.random.default_rng(1)
    base = rng.normal(0, 1, size=512).astype(np.float32)
    base /= np.linalg.norm(base)
    vecs = _make_person_embeddings(base, n=10, noise=0.03)

    c = compute_centroid(vecs)
    assert c.shape == (512,), f"Expected shape (512,), got {c.shape}"
    assert abs(np.linalg.norm(c) - 1.0) < 1e-5, f"Centroid not unit-norm: {np.linalg.norm(c)}"
    # Centroid should be very close to the base vector
    sim = float(np.dot(c, base))
    assert sim > 0.95, f"Centroid too far from base: sim={sim:.4f}"
    print(f"  PASS: centroid shape={c.shape}, norm={np.linalg.norm(c):.4f}, sim_to_base={sim:.4f}")


def test_build_person_centroids():
    """Build centroids for 3 people, verify all present."""
    rng = np.random.default_rng(10)
    items = []
    for pid in [1, 2, 3]:
        base = rng.normal(0, 1, size=512).astype(np.float32)
        base /= np.linalg.norm(base)
        for v in _make_person_embeddings(base, n=4):
            items.append({"person_id": pid, "name": f"Person_{pid}", "vec": v})

    centroids = build_person_centroids(items)
    assert len(centroids) == 3, f"Expected 3 centroids, got {len(centroids)}"
    for pid in [1, 2, 3]:
        assert pid in centroids, f"Missing centroid for person {pid}"
        assert centroids[pid]["count"] == 4, f"Expected 4 embeddings for person {pid}"
        c = centroids[pid]["centroid"]
        assert abs(np.linalg.norm(c) - 1.0) < 1e-5
    print(f"  PASS: built {len(centroids)} centroids, counts={[centroids[p]['count'] for p in [1,2,3]]}")


def test_match_against_centroids():
    """Probe close to person 2 should rank person 2 first."""
    rng = np.random.default_rng(20)
    bases = {}
    items = []
    for pid in [1, 2, 3]:
        base = rng.normal(0, 1, size=512).astype(np.float32)
        base /= np.linalg.norm(base)
        bases[pid] = base
        for v in _make_person_embeddings(base, n=5):
            items.append({"person_id": pid, "name": f"Person_{pid}", "vec": v})

    centroids = build_person_centroids(items)

    # Probe is close to person 2's base
    probe = bases[2] + rng.normal(0, 0.02, size=512).astype(np.float32)
    probe = (probe / np.linalg.norm(probe)).astype(np.float32)

    results = match_against_centroids(probe, centroids, topk=3)
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"
    assert results[0]["person_id"] == 2, f"Expected person 2 first, got {results[0]['person_id']}"
    assert results[0]["similarity"] > 0.9, f"Expected high similarity, got {results[0]['similarity']:.4f}"
    print(f"  PASS: top match=person_{results[0]['person_id']} sim={results[0]['similarity']:.4f}")


def test_deterministic_matching():
    """Same probe should always return identical results."""
    rng = np.random.default_rng(30)
    items = []
    for pid in [1, 2, 3]:
        base = rng.normal(0, 1, size=512).astype(np.float32)
        base /= np.linalg.norm(base)
        for v in _make_person_embeddings(base, n=5):
            items.append({"person_id": pid, "name": f"P{pid}", "vec": v})

    centroids = build_person_centroids(items)
    probe = rng.normal(0, 1, size=512).astype(np.float32)
    probe /= np.linalg.norm(probe)

    first_result = match_against_centroids(probe, centroids, topk=3)
    for run in range(20):
        result = match_against_centroids(probe, centroids, topk=3)
        for i in range(len(result)):
            assert result[i]["person_id"] == first_result[i]["person_id"], \
                f"Run {run}: person_id mismatch at rank {i}"
            assert abs(result[i]["similarity"] - first_result[i]["similarity"]) < 1e-7, \
                f"Run {run}: similarity jitter at rank {i}"
    print(f"  PASS: 20 runs identical — person_ids={[r['person_id'] for r in first_result]}")


def test_validate_embedding_valid():
    """A new embedding near the cluster should be accepted."""
    rng = np.random.default_rng(40)
    base = rng.normal(0, 1, size=512).astype(np.float32)
    base /= np.linalg.norm(base)
    existing = _make_person_embeddings(base, n=5, noise=0.03)

    new_vec = base + rng.normal(0, 0.04, size=512).astype(np.float32)
    new_vec = (new_vec / np.linalg.norm(new_vec)).astype(np.float32)

    valid, sim = validate_embedding(new_vec, existing)
    assert valid, f"Expected valid, got invalid with sim={sim:.4f}"
    assert sim > 0.8, f"Expected high similarity, got {sim:.4f}"
    print(f"  PASS: valid embedding accepted, sim={sim:.4f}")


def test_validate_embedding_outlier():
    """A random embedding far from the cluster should be flagged."""
    rng = np.random.default_rng(50)
    base = rng.normal(0, 1, size=512).astype(np.float32)
    base /= np.linalg.norm(base)
    existing = _make_person_embeddings(base, n=5, noise=0.03)

    # Create a completely different vector
    outlier = rng.normal(0, 1, size=512).astype(np.float32)
    outlier /= np.linalg.norm(outlier)
    # Make sure it's actually different
    outlier = -base  # opposite direction
    outlier = (outlier / np.linalg.norm(outlier)).astype(np.float32)

    valid, sim = validate_embedding(outlier, existing)
    assert not valid, f"Expected invalid (outlier), got valid with sim={sim:.4f}"
    print(f"  PASS: outlier rejected, sim={sim:.4f}")


def test_validate_no_existing():
    """With no existing embeddings, any new one should be accepted."""
    rng = np.random.default_rng(60)
    new_vec = rng.normal(0, 1, size=512).astype(np.float32)
    new_vec /= np.linalg.norm(new_vec)

    valid, sim = validate_embedding(new_vec, [])
    assert valid, "Expected valid when no existing embeddings"
    assert sim == 1.0
    print(f"  PASS: no existing → auto-accepted, sim={sim:.1f}")


if __name__ == "__main__":
    tests = [
        ("compute_centroid", test_compute_centroid),
        ("build_person_centroids", test_build_person_centroids),
        ("match_against_centroids", test_match_against_centroids),
        ("deterministic_matching", test_deterministic_matching),
        ("validate_embedding_valid", test_validate_embedding_valid),
        ("validate_embedding_outlier", test_validate_embedding_outlier),
        ("validate_no_existing", test_validate_no_existing),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"\n[TEST] {name}")
            fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed == 0:
        print("ALL TESTS PASSED ✓")
    else:
        print("SOME TESTS FAILED ✗")
    sys.exit(1 if failed > 0 else 0)
