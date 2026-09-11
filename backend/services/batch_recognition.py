"""Deterministic, batch-wide helpers for open-set face recognition."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

EMBEDDING_MODEL_VERSION = "faceplugin-onnx-v1"


def normalize_embedding(value) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.all(np.isfinite(vector)):
        return np.zeros(0, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-10:
        return np.zeros(0, dtype=np.float32)
    return (vector / norm).astype(np.float32)


def annotate_candidate_margin(candidates: list[dict]) -> list[dict]:
    """Attach raw top-two confidence metadata without modifying scores."""
    if not candidates:
        return candidates
    candidates.sort(key=lambda candidate: float(candidate.get("similarity", 0.0)), reverse=True)
    top = candidates[0]
    top_score = float(top.get("similarity", 0.0))
    top["raw_top1_score"] = top_score
    top["raw_top2_score"] = None
    top["score_margin"] = None
    top["is_ambiguous"] = False
    if len(candidates) < 2:
        return candidates

    runner_up = candidates[1]
    second_score = float(runner_up.get("similarity", 0.0))
    margin = top_score - second_score
    ambiguous = (top_score > 0.65 and margin < 0.05) or (top_score < 0.78 and margin < 0.04)
    top["raw_top2_score"] = second_score
    top["score_margin"] = margin
    top["is_ambiguous"] = bool(ambiguous)
    if ambiguous:
        runner_up["is_ambiguous"] = True
    return candidates


def _similarity(first: np.ndarray, second: np.ndarray) -> float:
    """Cosine similarity rescaled to the application's existing 0..1 range."""
    return (float(np.dot(first, second)) + 1.0) / 2.0


def _quality_weight(record: dict) -> float:
    sharpness = max(0.0, float(record.get("sharpness") or 0.0))
    detector = min(1.0, max(0.0, float(record.get("score") or 0.0)))
    pose = min(1.0, max(0.0, float(record.get("pose_yaw") or 0.0)))
    sharpness_weight = min(1.25, max(0.20, sharpness / 150.0))
    pose_weight = max(0.20, 1.0 - pose)
    return max(0.01, sharpness_weight * max(0.20, detector) * pose_weight)


def complete_linkage_clusters(records: list[dict], threshold: float = 0.86) -> list[dict]:
    """
    Cluster repeated appearances across a complete upload batch.

    Complete linkage avoids transitive "chains" that can merge two different
    people through a marginal intermediate face.  Clusters may not contain two
    faces from the same source image, which also protects the physical rule
    that one person cannot occupy two locations in a single photograph.
    """
    prepared = []
    for record in records:
        embedding = normalize_embedding(record.get("embedding"))
        if embedding.size:
            prepared.append({**record, "embedding": embedding})
    prepared.sort(key=lambda row: (str(row.get("item_id", "")), int(row.get("face_index", 0))))

    clusters = [[index] for index in range(len(prepared))]

    def can_merge(left: list[int], right: list[int]) -> tuple[bool, float]:
        left_items = {str(prepared[index].get("item_id", "")) for index in left}
        right_items = {str(prepared[index].get("item_id", "")) for index in right}
        if left_items.intersection(right_items):
            return False, -1.0
        minimum = min(
            _similarity(prepared[a]["embedding"], prepared[b]["embedding"])
            for a in left for b in right
        )
        return minimum >= threshold, minimum

    while True:
        best_pair = None
        best_score = -1.0
        for left_index in range(len(clusters)):
            for right_index in range(left_index + 1, len(clusters)):
                accepted, score = can_merge(clusters[left_index], clusters[right_index])
                if accepted and score > best_score:
                    best_pair = (left_index, right_index)
                    best_score = score
        if best_pair is None:
            break
        left_index, right_index = best_pair
        clusters[left_index] = sorted(clusters[left_index] + clusters[right_index])
        del clusters[right_index]

    result = []
    for cluster_number, indices in enumerate(clusters, start=1):
        members = [prepared[index] for index in indices]
        weights = np.asarray([_quality_weight(member) for member in members], dtype=np.float32)
        matrix = np.vstack([member["embedding"] for member in members])
        centroid = normalize_embedding(np.average(matrix, axis=0, weights=weights))
        result.append({
            "cluster_id": f"cluster-{cluster_number}",
            "members": members,
            "centroid": centroid,
            "observations": len(members),
        })
    return result


def classify_face_decision(face: dict, suggestions: list[dict] | None = None) -> str:
    suggestions = suggestions if suggestions is not None else (face.get("suggestions") or [])
    sharpness = float(face.get("sharpness") or 0.0)
    pose_yaw = float(face.get("pose_yaw") or 0.0)
    if sharpness < 80.0 or pose_yaw > 0.45:
        return "rejected_quality"
    if not suggestions:
        return "unknown"
    top = suggestions[0]
    margin = top.get("score_margin")
    if top.get("is_ambiguous") or (isinstance(margin, (int, float)) and margin < 0.05):
        return "review_required"
    return "matched"


def enforce_unique_predictions(faces: list[dict]) -> None:
    """Downgrade duplicate top identities within one photograph to review."""
    grouped = defaultdict(list)
    for face in faces:
        suggestions = face.get("suggestions") or []
        if face.get("recognition_decision") != "matched" or not suggestions:
            continue
        person_id = suggestions[0].get("person_id")
        if person_id is not None:
            grouped[(str(face.get("item_id", "")), str(person_id))].append(face)

    for duplicate_faces in grouped.values():
        if len(duplicate_faces) < 2:
            continue
        duplicate_faces.sort(
            key=lambda face: float((face.get("suggestions") or [{}])[0].get("similarity", 0.0)),
            reverse=True,
        )
        for conflict in duplicate_faces[1:]:
            conflict["recognition_decision"] = "review_required"
            conflict["duplicate_identity_conflict"] = True
