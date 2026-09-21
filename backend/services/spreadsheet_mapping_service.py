"""Safe, one-call semantic mapping for spreadsheet headers.

Only header names and aggregate value-shape statistics are sent to the model;
employee/student cell values are never included in the prompt.
"""

import json
import logging
import os
import re
import uuid


logger = logging.getLogger(__name__)

CANONICAL_FIELDS = (
    "name", "phone", "person_id", "email", "department", "designation",
    "shift", "class_id", "class_year", "division", "branch",
    "parent_name", "parent_phone",
)

_SYNONYMS = {
    "name": ("name", "full name", "student name", "employee name", "person name", "staff name", "faculty name"),
    "phone": ("phone", "phone number", "mobile", "mobile number", "contact number", "contact mobile", "whatsapp number"),
    "person_id": (
        "student id", "student number", "student no", "roll number", "roll no", "enrollment number",
        "enrollment no", "admission number", "admission no", "employee id", "employee code", "staff id",
        "person id", "id number",
    ),
    "email": ("email", "email address", "e mail", "official email", "work email"),
    "department": ("department", "dept", "unit", "team"),
    "designation": ("designation", "job title", "role", "position", "post"),
    "shift": ("shift", "work shift", "timing", "shift timing"),
    "class_id": ("class id", "class code", "section id"),
    "class_year": ("class year", "academic year", "year", "standard", "grade", "class"),
    "division": ("division", "section", "class section"),
    "branch": ("branch", "course", "stream"),
    "parent_name": ("parent name", "guardian name", "father name", "mother name", "parent guardian name"),
    "parent_phone": (
        "parent phone", "parent mobile", "parent whatsapp", "guardian phone", "guardian mobile",
        "guardian whatsapp", "father mobile", "mother mobile", "parent contact number",
    ),
}


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _safe_headers(headers):
    result = []
    seen = set()
    for header in headers or []:
        text = str(header).strip()[:160]
        if not text or text in seen:
            continue
        seen.add(text)
        result.append((text, header))
    return result[:200]


def _profiles(headers, rows):
    profiles = {}
    for header_text, original in headers:
        values = [str(row.get(original)).strip() for row in (rows or [])[:100] if row.get(original) not in (None, "")]
        count = len(values)
        if not count:
            profiles[header_text] = {"non_empty": 0}
            continue
        digit_lengths = [len(re.sub(r"\D", "", value)) for value in values]
        profiles[header_text] = {
            "non_empty": count,
            "unique_ratio": round(len(set(values)) / count, 2),
            "email_ratio": round(sum(bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)) for value in values) / count, 2),
            "phone_shape_ratio": round(sum(7 <= length <= 15 for length in digit_lengths) / count, 2),
            "numeric_ratio": round(sum(bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value)) for value in values) / count, 2),
            "average_length": round(sum(len(value) for value in values) / count, 1),
        }
    return profiles


def deterministic_mapping(headers, rows=None):
    safe_headers = _safe_headers(headers)
    normalized = {_normalize(text): original for text, original in safe_headers}
    mapping = {}
    used = set()
    for canonical in CANONICAL_FIELDS:
        for alias in _SYNONYMS[canonical]:
            original = normalized.get(_normalize(alias))
            if original is not None and original not in used:
                mapping[canonical] = original
                used.add(original)
                break

    profiles = _profiles(safe_headers, rows)
    for canonical, score_key, threshold in (("email", "email_ratio", 0.7), ("phone", "phone_shape_ratio", 0.8)):
        if canonical in mapping:
            continue
        candidates = [
            original for text, original in safe_headers
            if profiles.get(text, {}).get(score_key, 0) >= threshold and original not in used
        ]
        if len(candidates) == 1:
            mapping[canonical] = candidates[0]
            used.add(candidates[0])
    return mapping


def _parse_model_mapping(content, headers):
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    payload = json.loads(text[start:end + 1])
    raw_mapping = payload.get("mapping", payload) if isinstance(payload, dict) else {}
    header_lookup = {text: original for text, original in headers}
    validated = {}
    used = set()
    for canonical in CANONICAL_FIELDS:
        selected = raw_mapping.get(canonical) if isinstance(raw_mapping, dict) else None
        original = header_lookup.get(str(selected).strip()) if selected is not None else None
        if original is not None and original not in used:
            validated[canonical] = original
            used.add(original)
    return validated


def _manual_mapping(manual_mapping, headers):
    if not isinstance(manual_mapping, dict):
        return {}
    return _parse_model_mapping(json.dumps({"mapping": manual_mapping}), headers)


def _merge_unique(primary, secondary):
    merged = dict(primary)
    used = set(primary.values())
    for canonical, header in secondary.items():
        if canonical not in merged and header not in used:
            merged[canonical] = header
            used.add(header)
    return merged


def _contextualize(mapping, context):
    result = dict(mapping)
    if str(context or "").lower() in {"employee", "faculty", "people"}:
        if "branch" in result and "department" not in result:
            result["department"] = result["branch"]
        result.pop("branch", None)
        result.pop("class_id", None)
        result.pop("class_year", None)
        result.pop("division", None)
    return result


def map_spreadsheet_headers(
    headers, rows, context="people", manual_mapping=None, vendor_id=None,
    username=None, provider=None, connection_factory=None,
):
    safe_headers = _safe_headers(headers)
    deterministic = _contextualize(deterministic_mapping(headers, rows), context)
    exact_mapping = _contextualize(deterministic_mapping(headers, None), context)
    manual = _manual_mapping(manual_mapping, safe_headers)
    if manual:
        return {"mapping": _merge_unique(manual, deterministic), "method": "manual", "warning": None}

    if str(os.environ.get("SPREADSHEET_LLM_MAPPING_ENABLED", "true")).lower() not in {"1", "true", "yes", "on"}:
        return {"mapping": deterministic, "method": "deterministic", "warning": None}

    try:
        if provider is None:
            from services.xchat_service import configured_provider
            provider = configured_provider()

        prompt_payload = {
            "context": str(context or "people")[:40],
            "headers": [text for text, _ in safe_headers],
            "value_profiles": _profiles(safe_headers, rows),
            "allowed_fields": list(CANONICAL_FIELDS),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Map spreadsheet columns to canonical fields. Return JSON only as "
                    "{\"mapping\":{\"canonical_field\":\"exact input header\"}}. Use only allowed fields "
                    "and exact supplied headers, use each header at most once, and omit uncertain mappings. "
                    "For people imports, do not map a parent/guardian name as the person's name. "
                    "class_id means an internal class identifier; grade/class labels belong to class_year."
                ),
            },
            {"role": "user", "content": json.dumps(prompt_payload, separators=(",", ":"))},
        ]
        response = provider.complete(messages, [])
        llm_mapping = _contextualize(_parse_model_mapping(response.get("content"), safe_headers), context)
        # Exact, known aliases take precedence; the model fills ambiguous/custom labels.
        mapping = _merge_unique(exact_mapping, llm_mapping)
        mapping = _merge_unique(mapping, deterministic)

        usage = dict(getattr(provider, "usage_totals", {}) or {})
        if vendor_id is not None and int(usage.get("total_tokens", 0) or 0) > 0:
            from services.xchat_billing_service import record_usage
            record_usage(
                vendor_id, username, f"spreadsheet:{uuid.uuid4()}",
                getattr(provider, "model", "unknown"), usage,
                connection_factory=connection_factory, usage_type="spreadsheet_mapping", billable=False,
            )
        return {"mapping": mapping, "method": "llm_assisted", "warning": None}
    except Exception as exc:
        logger.warning("Spreadsheet semantic mapping fell back to deterministic rules: %s", type(exc).__name__)
        return {
            "mapping": deterministic,
            "method": "deterministic",
            "warning": "AI header mapping was unavailable; safe built-in mapping was used.",
        }
