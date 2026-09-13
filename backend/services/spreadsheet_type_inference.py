import re
from typing import List, Dict, Any, Tuple


NUMERIC_REGEX = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
INTEGER_REGEX = re.compile(r"^[-+]?\d+$")

DROPDOWN_KEYWORDS = {
    "gender", "sex", "department", "dept", "shift", "blood", "blood_group",
    "status", "type", "category", "role", "designation", "level", "division",
    "section", "grade", "state", "city", "country", "location"
}


def clean_cell_value(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null", "undefined"):
        return ""
    # If float ending in .0 from Excel (e.g. 25.0 -> 25), clean it up for display
    if re.fullmatch(r"[-+]?\d+\.0", s):
        s = s[:-2]
    return s


def infer_column_spec(
    header: str,
    raw_values: List[Any],
    canonical_role: str = "custom"
) -> Dict[str, Any]:
    """
    Infers whether a column is 'text', 'number', or 'select' (dropdown).
    Also extracts sample preview values and initial dropdown options.
    """
    cleaned_values = [clean_cell_value(v) for v in raw_values]
    non_empty = [v for v in cleaned_values if v != ""]
    
    # 3-5 distinct sample values for UI preview
    sample_values = []
    seen_samples = set()
    for v in non_empty:
        if v not in seen_samples:
            seen_samples.add(v)
            sample_values.append(v)
            if len(sample_values) >= 5:
                break

    header_clean = str(header or "").strip().lower()
    header_normalized = re.sub(r"[^a-z0-9]+", "_", header_clean).strip("_")

    # If canonical role is name, it is always text and required
    if canonical_role == "name":
        return {
            "header": str(header).strip(),
            "role": "name",
            "type": "text",
            "required": True,
            "sample_values": sample_values,
            "options": []
        }

    # If canonical role is phone, it is text
    if canonical_role == "phone":
        return {
            "header": str(header).strip(),
            "role": "phone",
            "type": "text",
            "required": False,
            "sample_values": sample_values,
            "options": []
        }

    # If canonical role is person_id, it is text
    if canonical_role == "person_id":
        return {
            "header": str(header).strip(),
            "role": "person_id",
            "type": "text",
            "required": False,
            "sample_values": sample_values,
            "options": []
        }

    total_count = len(non_empty)
    unique_values = sorted(list(set(non_empty)))
    unique_count = len(unique_values)

    # 1. Numerical Check (Age, Marks, Experience, Salary, etc.)
    # Ignore if column looks like a phone number or ID
    is_phone_like = any(kw in header_normalized for kw in ("phone", "mobile", "contact", "whatsapp"))
    is_id_like = any(kw in header_normalized for kw in ("id", "code", "enrollment", "admission", "roll"))
    
    if total_count > 0 and not is_phone_like and not is_id_like:
        numeric_count = sum(1 for v in non_empty if NUMERIC_REGEX.fullmatch(v))
        if numeric_count / total_count >= 0.85:
            return {
                "header": str(header).strip(),
                "role": canonical_role,
                "type": "number",
                "required": False,
                "sample_values": sample_values,
                "options": []
            }

    # 2. Dropdown / Categorical Check
    # Check if header matches common categorical keywords
    has_dropdown_keyword = any(kw == header_normalized or header_normalized.startswith(f"{kw}_") or header_normalized.endswith(f"_{kw}") or kw in header_normalized.split("_") for kw in DROPDOWN_KEYWORDS)
    
    # If values are categorical: unique count between 1 and 15
    # or keyword matched and unique count <= 25
    if (
        (1 <= unique_count <= 15 and (total_count >= 2 or has_dropdown_keyword)) or
        (has_dropdown_keyword and 1 <= unique_count <= 25)
    ) and not is_id_like:
        # Format options cleanly
        options = [str(opt).strip() for opt in unique_values if str(opt).strip()]
        return {
            "header": str(header).strip(),
            "role": canonical_role,
            "type": "select",
            "required": False,
            "sample_values": sample_values,
            "options": options
        }

    # 3. Default: Text
    return {
        "header": str(header).strip(),
        "role": canonical_role,
        "type": "text",
        "required": False,
        "sample_values": sample_values,
        "options": []
    }


def inspect_spreadsheet_fields(
    headers: List[str],
    rows: List[Dict[str, Any]],
    canonical_mapping: Dict[str, str] = None
) -> List[Dict[str, Any]]:
    """
    Inspects all headers across rows and produces field specifications.
    """
    mapping = canonical_mapping or {}
    # Inverted mapping: header -> canonical_role
    header_to_role = {h: role for role, h in mapping.items()}

    field_specs = []
    for h in headers:
        header_str = str(h).strip()
        if not header_str:
            continue
        role = header_to_role.get(header_str, "custom")
        raw_vals = [row.get(h) for row in rows if row.get(h) is not None]
        spec = infer_column_spec(header_str, raw_vals, canonical_role=role)
        field_specs.append(spec)

    return field_specs
