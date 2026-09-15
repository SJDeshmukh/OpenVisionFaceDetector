"""Deterministic, effective-dated shift assignment resolution."""

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


SCOPE_PRECEDENCE = {
    "VENDOR": 100,
    "LOCATION": 200,
    "ORG_UNIT": 300,
    "GROUP": 400,
    "EMPLOYEE": 500,
}


@dataclass(frozen=True)
class ResolvedShift:
    assignment_id: int
    shift_id: int
    shift_version_id: int
    shift_name: str
    scope_type: str
    effective_from: date
    start_time: str
    end_time: str
    timezone: str
    is_cross_midnight: bool
    explanation: str


def _as_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def choose_assignment(assignments: Iterable[dict], operational_date: date) -> Optional[dict]:
    """Choose by scope, explicit priority, latest start, then stable ID."""

    on_date = _as_date(operational_date)
    eligible = []
    for item in assignments:
        starts = _as_date(item["effective_from"])
        ends = _as_date(item["effective_to"]) if item.get("effective_to") else None
        scope = str(item.get("scope_type") or "").upper()
        if scope not in SCOPE_PRECEDENCE or starts > on_date or (ends and ends < on_date):
            continue
        eligible.append(item)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            SCOPE_PRECEDENCE[str(item["scope_type"]).upper()],
            int(item.get("priority") or 0),
            _as_date(item["effective_from"]),
            -int(item.get("id") or 0),
        ),
    )


def resolve_shift(
    cursor,
    vendor_id: int,
    person_id: int,
    operational_date: date,
    *,
    organization_unit_ids=(),
    location_id=None,
    group_keys=(),
) -> Optional[ResolvedShift]:
    """Resolve an assignment and its version without crossing tenant scope."""

    cursor.execute(
        """SELECT id, shift_id, scope_type, person_id, organization_unit_id,
                  location_id, group_key, effective_from, effective_to, priority
           FROM shift_assignments
           WHERE vendor_id = ? AND effective_from <= ?
             AND (effective_to IS NULL OR effective_to >= ?)""",
        (vendor_id, operational_date, operational_date),
    )
    org_ids = {int(value) for value in organization_unit_ids}
    groups = {str(value) for value in group_keys}
    candidates = []
    for row in cursor.fetchall() or []:
        item = dict(row) if hasattr(row, "keys") else {
            "id": row[0], "shift_id": row[1], "scope_type": row[2],
            "person_id": row[3], "organization_unit_id": row[4],
            "location_id": row[5], "group_key": row[6],
            "effective_from": row[7], "effective_to": row[8], "priority": row[9],
        }
        scope = str(item["scope_type"]).upper()
        matches = (
            (scope == "EMPLOYEE" and int(item["person_id"] or 0) == int(person_id))
            or (scope == "ORG_UNIT" and int(item["organization_unit_id"] or 0) in org_ids)
            or (scope == "LOCATION" and location_id is not None and int(item["location_id"] or 0) == int(location_id))
            or (scope == "GROUP" and str(item["group_key"] or "") in groups)
            or scope == "VENDOR"
        )
        if matches:
            candidates.append(item)

    selected = choose_assignment(candidates, operational_date)
    if not selected:
        return None
    cursor.execute(
        """SELECT sv.id, s.name, sv.effective_from, sv.start_time, sv.end_time,
                  sv.timezone, sv.is_cross_midnight
           FROM shift_versions sv
           JOIN shifts s ON s.id = sv.shift_id AND s.vendor_id = sv.vendor_id
           WHERE sv.vendor_id = ? AND sv.shift_id = ? AND sv.effective_from <= ?
             AND (sv.effective_to IS NULL OR sv.effective_to >= ?)
           ORDER BY sv.version_number DESC LIMIT 1""",
        (vendor_id, selected["shift_id"], operational_date, operational_date),
    )
    version = cursor.fetchone()
    if not version:
        return None
    scope = str(selected["scope_type"]).upper()
    return ResolvedShift(
        assignment_id=int(selected["id"]),
        shift_id=int(selected["shift_id"]),
        shift_version_id=int(version[0]),
        shift_name=str(version[1]),
        scope_type=scope,
        effective_from=_as_date(version[2]),
        start_time=str(version[3]),
        end_time=str(version[4]),
        timezone=str(version[5]),
        is_cross_midnight=bool(version[6]),
        explanation=f"Resolved {scope} assignment {selected['id']} using precedence {SCOPE_PRECEDENCE[scope]}",
    )
