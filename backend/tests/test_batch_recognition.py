import numpy as np
import pytest

from schemas import ClassBatchAssignment
from embedding_cluster import compute_weighted_centroid
from services.batch_recognition import (
    annotate_candidate_margin,
    classify_face_decision,
    complete_linkage_clusters,
    enforce_unique_predictions,
)


def _unit(*values):
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_batch_clustering_is_order_independent():
    records = [
        {"item_id": "a", "face_index": 0, "embedding": _unit(1.0, 0.0), "sharpness": 180, "score": .9},
        {"item_id": "b", "face_index": 0, "embedding": _unit(.98, .05), "sharpness": 160, "score": .9},
        {"item_id": "c", "face_index": 0, "embedding": _unit(0.0, 1.0), "sharpness": 170, "score": .9},
    ]
    forward = complete_linkage_clusters(records, threshold=.90)
    reverse = complete_linkage_clusters(list(reversed(records)), threshold=.90)

    assert sorted(cluster["observations"] for cluster in forward) == [1, 2]
    assert sorted(cluster["observations"] for cluster in reverse) == [1, 2]


def test_two_faces_from_same_image_never_join_one_cluster():
    embedding = _unit(1.0, 0.0)
    clusters = complete_linkage_clusters([
        {"item_id": "same", "face_index": 0, "embedding": embedding},
        {"item_id": "same", "face_index": 1, "embedding": embedding},
    ], threshold=.50)

    assert len(clusters) == 2


def test_complete_linkage_prevents_transitive_identity_chain():
    def direction(degrees):
        radians = np.deg2rad(degrees)
        return _unit(np.cos(radians), np.sin(radians))

    clusters = complete_linkage_clusters([
        {"item_id": "a", "face_index": 0, "embedding": direction(0)},
        {"item_id": "b", "face_index": 0, "embedding": direction(20)},
        {"item_id": "c", "face_index": 0, "embedding": direction(40)},
    ], threshold=.90)

    assert sorted(cluster["observations"] for cluster in clusters) == [1, 2]


def test_ambiguous_face_requires_review_even_when_clear():
    face = {"sharpness": 200, "pose_yaw": .05}
    suggestions = [{"person_id": 1, "similarity": .91, "score_margin": .02}]

    assert classify_face_decision(face, suggestions) == "review_required"


def test_candidate_margin_never_changes_raw_scores():
    candidates = [
        {"person_id": 1, "similarity": .81},
        {"person_id": 2, "similarity": .79},
    ]

    result = annotate_candidate_margin(candidates)

    assert result[0]["similarity"] == .81
    assert result[1]["similarity"] == .79
    assert result[0]["score_margin"] == .81 - .79
    assert result[0]["is_ambiguous"] is True


def test_duplicate_identity_in_one_image_keeps_only_strongest_auto_match():
    faces = [
        {"item_id": "photo", "recognition_decision": "matched", "suggestions": [{"person_id": 7, "similarity": .88}]},
        {"item_id": "photo", "recognition_decision": "matched", "suggestions": [{"person_id": 7, "similarity": .81}]},
    ]

    enforce_unique_predictions(faces)

    assert faces[0]["recognition_decision"] == "matched"
    assert faces[1]["recognition_decision"] == "review_required"
    assert faces[1]["duplicate_identity_conflict"] is True


def test_legacy_assignment_defaults_to_non_learning_auto_source():
    assignment = ClassBatchAssignment(item_id="photo", face_index=0, person_id=7)

    assert assignment.assignment_source == "auto_match"


def test_unknown_assignment_source_is_rejected():
    with pytest.raises(ValueError):
        ClassBatchAssignment(
            item_id="photo", face_index=0, person_id=7,
            assignment_source="browser_supplied_trusted",
        )


def test_gallery_centroid_prefers_high_quality_confirmations():
    centroid = compute_weighted_centroid(
        [_unit(1.0, 0.0), _unit(.98, .02), _unit(0.0, 1.0)],
        [200.0, 180.0, 20.0],
    )

    assert float(np.dot(centroid, _unit(1.0, 0.0))) > .98
