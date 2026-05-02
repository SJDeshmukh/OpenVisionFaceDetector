"""
Per-person embedding cluster manager.

Provides centroid-based matching that is deterministic and stable:
  - build_person_centroids():  aggregate per-person embeddings into a single
                               unit-norm centroid (mean of L2-norm vectors).
  - match_against_centroids(): O(n_persons) cosine matching against centroids.
  - validate_embedding():      checks if a new embedding is consistent with
                               a person's existing cluster before storage.

This module is used by face_service.py to replace the noisy per-embedding
linear scan with stable centroid-based matching.  It requires NO minimum
number of people — even a single person with a single embedding gets a
(trivial) centroid.

No new dependencies — pure numpy.
"""

from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)

# Minimum cosine similarity for a new embedding to be considered consistent
# with an existing person cluster.  Below this the embedding is flagged as
# an outlier (still saved because the user explicitly chose the label, but
# logged for diagnostics).
MIN_CLUSTER_SIMILARITY = 0.50


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize a vector or each row of a matrix. Safe against zero."""
    if v.ndim == 1:
        n = float(np.linalg.norm(v))
        return (v / n).astype(np.float32) if n > 1e-10 else v.astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return (v / np.maximum(norms, 1e-10)).astype(np.float32)


def compute_centroid(vecs: list[np.ndarray] | np.ndarray) -> np.ndarray:
    """
    Compute a single unit-norm centroid from a list of embedding vectors.

    Steps: stack → mean → L2-normalize.  The result is the "representative
    direction" of the cluster in embedding space.

    Returns
    -------
    np.ndarray of shape (dim,), unit-norm float32.
    """
    if isinstance(vecs, np.ndarray) and vecs.ndim == 2:
        stacked = vecs.astype(np.float32)
    else:
        arr = [v for v in vecs if v is not None and v.size > 0]
        if not arr:
            return np.zeros(0, dtype=np.float32)
        stacked = np.array(arr, dtype=np.float32)

    mean = stacked.mean(axis=0)
    return _l2_normalize(mean)


def build_person_centroids(items: list[dict]) -> dict[int, dict]:
    """
    Group cache items by person_id and compute a centroid for each person.

    Parameters
    ----------
    items : list of dicts with keys 'person_id', 'vec', and optionally 'name'.

    Returns
    -------
    {person_id: {'centroid': np.ndarray(dim,), 'name': str, 'count': int}}
    """
    buckets: dict[int, list[np.ndarray]] = defaultdict(list)
    names: dict[int, str] = {}

    for it in items:
        pid = int(it["person_id"])
        v = it.get("vec")
        if v is not None and v.size > 0:
            buckets[pid].append(v)
        if pid not in names:
            names[pid] = str(it.get("name", ""))

    centroids: dict[int, dict] = {}
    for pid, vecs in buckets.items():
        c = compute_centroid(vecs)
        if c.size > 0:
            centroids[pid] = {
                "centroid": c,
                "name": names.get(pid, ""),
                "count": len(vecs),
            }

    return centroids


def match_against_centroids(
    probe: np.ndarray,
    centroids: dict[int, dict],
    topk: int = 5,
) -> list[dict]:
    """
    Compare a probe embedding against all person centroids.

    Returns a sorted list (highest similarity first) of:
        {'person_id': int, 'name': str, 'similarity': float}

    Similarity is cosine in raw space, rescaled to [0, 1] via (s+1)/2.
    This is O(n_persons) — fast even for thousands of people.
    """
    probe_norm = _l2_normalize(probe)
    if probe_norm.size == 0:
        return []

    results = []
    for pid, info in centroids.items():
        c = info["centroid"]
        if c.size != probe_norm.size:
            continue
        cos_sim = float(np.dot(probe_norm, c))       # both unit-norm → [-1, 1]
        sim = (cos_sim + 1.0) / 2.0                   # scale to [0, 1]
        results.append({
            "person_id": pid,
            "name": info.get("name", ""),
            "similarity": sim,
        })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:topk]


def validate_embedding(
    new_vec: np.ndarray,
    existing_vecs: list[np.ndarray],
    min_sim: float = MIN_CLUSTER_SIMILARITY,
) -> tuple[bool, float]:
    """
    Check whether a new embedding is consistent with a person's cluster.

    Computes cosine similarity between new_vec and the centroid of
    existing_vecs.  If below min_sim, the embedding is flagged as an
    outlier.

    Parameters
    ----------
    new_vec        : the embedding to validate (512-D)
    existing_vecs  : list of existing embeddings for this person
    min_sim        : minimum cosine similarity (0→1 scale) to pass

    Returns
    -------
    (is_valid: bool, similarity: float)
    """
    if not existing_vecs or new_vec is None or new_vec.size == 0:
        return True, 1.0   # no prior data → always valid

    centroid = compute_centroid(existing_vecs)
    if centroid.size == 0 or centroid.size != new_vec.size:
        return True, 1.0

    v = _l2_normalize(new_vec)
    cos_sim = float(np.dot(v, centroid))
    sim_01 = (cos_sim + 1.0) / 2.0

    is_valid = sim_01 >= min_sim
    if not is_valid:
        logger.warning(
            f"[Cluster] Outlier embedding detected: similarity={sim_01:.3f} "
            f"< threshold={min_sim:.2f}.  Embedding will still be saved "
            f"(user explicitly assigned this label)."
        )

    return is_valid, sim_01
