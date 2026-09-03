"""Authoritative vendor report-filter configuration and faceting helpers."""

import json
import re


STANDARD_FILTERS = ("department", "designation", "shift", "phone")
NON_FILTER_FIELDS = {
    "name", "face_image", "templates", "templates_list", "landmarks_3d",
    "landmarks_3d_list", "struct_vec", "struct_vec_list",
}
KEY_ALIASES = {
    "student_id": ("student_id", "student_number", "id_number"),
    "student_number": ("student_number", "student_id", "id_number"),
    "id_number": ("id_number", "student_id", "student_number"),
    "class_section": ("class_section", "class_id"),
    "class_id": ("class_id", "class_section"),
}


def parse_json_list(raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def normalized_key(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def custom_value(custom, key):
    """Case/spacing-tolerant custom value lookup with explicit safe aliases."""
    if not isinstance(custom, dict):
        return None
    wanted = normalized_key(key)
    normalized = {normalized_key(raw_key): value for raw_key, value in custom.items()}
    for candidate in KEY_ALIASES.get(wanted, (wanted,)):
        if candidate in normalized:
            return normalized[candidate]
    return None


def merge_filter_configuration(registration_config, bulk_fields):
    """Merge only fields explicitly configured by Superadmin or bulk upload."""
    visible = {key: False for key in STANDARD_FILTERS}
    standard_labels = {key: key.replace("_", " ").title() for key in STANDARD_FILTERS}
    dynamic = {}
    registration_items = parse_json_list(registration_config)
    blocked_by_registration = {
        normalized_key(raw.get("field") or raw.get("key") or raw.get("name"))
        for raw in registration_items
        if isinstance(raw, dict) and raw.get("enabled", True) is False
    }

    def add(raw, source):
        if not isinstance(raw, dict) or raw.get("enabled", True) is False:
            return
        original_key = str(raw.get("field") or raw.get("key") or raw.get("name") or "").strip()
        if not original_key:
            return
        canonical = normalized_key(original_key)
        if source == "bulk_upload" and canonical in blocked_by_registration:
            return
        if canonical in NON_FILTER_FIELDS or raw.get("is_name") is True:
            return
        label = str(raw.get("label") or original_key).strip() or original_key
        if canonical in STANDARD_FILTERS:
            visible[canonical] = True
            standard_labels[canonical] = label
            return
        dedupe_key = canonical
        if dedupe_key not in dynamic:
            dynamic[dedupe_key] = {
                "key": original_key,
                "label": label,
                "options": raw.get("options") if isinstance(raw.get("options"), list) else [],
                "source": source,
            }
        elif source == "registration":
            dynamic[dedupe_key].update({"key": original_key, "label": label, "source": source})
            if isinstance(raw.get("options"), list) and raw["options"]:
                dynamic[dedupe_key]["options"] = raw["options"]

    for field in registration_items:
        add(field, "registration")
    for field in parse_json_list(bulk_fields):
        add(field, "bulk_upload")

    return visible, standard_labels, list(dynamic.values())


def face_matches(face, standard_values, dynamic_values, exclude_standard=None, exclude_dynamic=None):
    for key in STANDARD_FILTERS:
        expected = str((standard_values or {}).get(key) or "").strip()
        if key != exclude_standard and expected and str(face.get(key) or "").strip() != expected:
            return False
    for key, expected_raw in (dynamic_values or {}).items():
        expected = str(expected_raw or "").strip()
        if key != exclude_dynamic and expected:
            actual = custom_value(face.get("custom"), key)
            if actual is None or str(actual).strip() != expected:
                return False
    return True
