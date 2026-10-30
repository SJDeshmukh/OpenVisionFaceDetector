"""Effective-dated employee compensation and privileged payroll reauthentication."""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from services.attendance_shift_service import calculate_shift_wage


logger = logging.getLogger(__name__)
MONEY_FIELDS = (
    "daily_wage",
    "basic_salary",
    "hra",
    "conveyance",
    "special_allowance",
    "professional_tax",
    "late_deduction_amount",
)
FLAG_FIELDS = ("pf_enabled", "esi_enabled", "gratuity_enabled")
SALARY_FIELDS = MONEY_FIELDS + FLAG_FIELDS + ("late_allowance_days",)
MANAGER_ROLES = {"super_admin", "vendor_admin", "admin", "owner"}
ALLOWED_REAUTH_PURPOSES = {"salary_change", "payroll_finalize"}
_MONEY_LIMIT = Decimal("9999999999.99")


class SalaryValidationError(ValueError):
    pass


class SalaryConflictError(RuntimeError):
    pass


class ReauthenticationError(PermissionError):
    pass


def _row_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError("Database row does not expose named columns")


def _date_value(value, field="effective_from"):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise SalaryValidationError(f"{field} must use YYYY-MM-DD format")


def _money(value, field):
    if value is None and field == "late_deduction_amount":
        return None
    try:
        parsed = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise SalaryValidationError(f"{field} must be a valid amount")
    if parsed < 0 or parsed > _MONEY_LIMIT:
        raise SalaryValidationError(f"{field} must be between 0 and {_MONEY_LIMIT}")
    return float(parsed)


def normalize_salary_values(source, fallback=None):
    fallback = fallback or {}
    result = {}
    for field in MONEY_FIELDS:
        raw = source[field] if field in source else fallback.get(field)
        result[field] = _money(raw, field)
    for field in FLAG_FIELDS:
        raw = source[field] if field in source else fallback.get(field, 0)
        if raw not in (0, 1, False, True, "0", "1"):
            raise SalaryValidationError(f"{field} must be true or false")
        result[field] = 1 if str(raw).lower() in {"1", "true"} else 0
    raw_allowance = source.get("late_allowance_days", fallback.get("late_allowance_days"))
    if raw_allowance in (None, ""):
        result["late_allowance_days"] = None
    else:
        try:
            allowance = int(raw_allowance)
        except (TypeError, ValueError):
            raise SalaryValidationError("late_allowance_days must be a whole number")
        if allowance < 0 or allowance > 366:
            raise SalaryValidationError("late_allowance_days must be between 0 and 366")
        result["late_allowance_days"] = allowance
    return result


def salary_values_equal(left, right):
    for field in MONEY_FIELDS:
        if _money(left.get(field), field) != _money(right.get(field), field):
            return False
    for field in FLAG_FIELDS:
        if int(bool(left.get(field))) != int(bool(right.get(field))):
            return False
    return left.get("late_allowance_days") == right.get("late_allowance_days")


def load_salary_versions(cursor, vendor_id, person_ids):
    ids = sorted({int(person_id) for person_id in person_ids if person_id is not None})
    if not ids:
        return {}
    output = defaultdict(list)
    for offset in range(0, len(ids), 300):
        batch = ids[offset:offset + 300]
        placeholders = ",".join("?" for _ in batch)
        try:
            cursor.execute(
                f"""SELECT id, vendor_id, person_id, version_number, effective_from,
                           effective_to, daily_wage, basic_salary, hra, conveyance,
                           special_allowance, pf_enabled, esi_enabled, gratuity_enabled,
                           professional_tax, late_allowance_days, late_deduction_amount,
                           changed_by, change_reason, created_at
                      FROM employee_salary_versions
                     WHERE vendor_id = ? AND person_id IN ({placeholders})
                     ORDER BY person_id, effective_from, version_number""",
                [vendor_id, *batch],
            )
        except Exception as exc:
            message = str(exc).lower()
            # SQLite fixtures and rolling local upgrades can lack the table.
            # PostgreSQL errors are deliberately re-raised because a failed
            # statement aborts that transaction and must not be hidden.
            missing_table = (
                "employee_salary_versions" in message and "no such table" in message
            )
            if not missing_table:
                raise
            logger.warning(
                "Salary ledger table is not available yet; using current employee salary values"
            )
            return {}
        for row in cursor.fetchall() or []:
            item = _row_dict(row)
            item["effective_from"] = _date_value(item["effective_from"])
            if item.get("effective_to") is not None:
                item["effective_to"] = _date_value(item["effective_to"], "effective_to")
            for field in MONEY_FIELDS:
                if item.get(field) is not None:
                    item[field] = float(item[field])
            for field in FLAG_FIELDS:
                item[field] = int(item.get(field) or 0)
            output[int(item["person_id"])].append(item)
    return dict(output)


def resolve_salary_version(versions, attendance_day):
    attendance_day = _date_value(attendance_day, "attendance_day")
    candidates = [
        version for version in (versions or [])
        if version["effective_from"] <= attendance_day
        and (version.get("effective_to") is None or attendance_day < version["effective_to"])
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["effective_from"], int(item["version_number"])))


def calculate_versioned_shift_wage(
    versions,
    fallback_config,
    worked_seconds_by_day,
    scheduled_hours,
    *,
    overtime_multiplier=1.0,
):
    """Calculate each operational attendance day with its effective salary."""
    grouped_days = defaultdict(dict)
    configs = {}
    for attendance_day, seconds in worked_seconds_by_day.items():
        version = resolve_salary_version(versions, attendance_day)
        config = version or fallback_config
        key = int(version["id"]) if version else 0
        grouped_days[key][attendance_day] = seconds
        configs[key] = config

    totals = {
        "regular_hours": 0.0,
        "overtime_hours": 0.0,
        "regular_wage": 0.0,
        "overtime_wage": 0.0,
        "gross_wage": 0.0,
    }
    groups = []
    for key, days in grouped_days.items():
        config = configs[key]
        result = calculate_shift_wage(
            config.get("daily_wage") or 0,
            days,
            scheduled_hours,
            overtime_multiplier=overtime_multiplier,
        )
        for field in totals:
            totals[field] += float(result[field])
        groups.append({
            "salary_version_id": key or None,
            "salary_version_number": config.get("version_number"),
            "config": config,
            "dates": sorted(day.isoformat() for day in days),
            "wage": result,
        })
    for field in totals:
        totals[field] = round(totals[field], 2)
    totals["hourly_rate"] = None
    totals["groups"] = groups
    totals["salary_version_ids"] = sorted(
        group["salary_version_id"] for group in groups if group["salary_version_id"] is not None
    )
    return totals


def issue_reauth_token(cursor, vendor_id, username, role, password, purpose="salary_change"):
    from services.auth_service import verify_password

    if purpose not in ALLOWED_REAUTH_PURPOSES:
        raise SalaryValidationError("Unsupported confirmation purpose")
    if role not in MANAGER_ROLES:
        raise ReauthenticationError("Payroll changes require manager access")
    if not password:
        raise SalaryValidationError("Your current login password is required")

    cursor.execute(
        "SELECT password, vendor_id FROM system_users WHERE LOWER(username) = LOWER(?) LIMIT 1",
        (username,),
    )
    user = _row_dict(cursor.fetchone())
    if not user or not verify_password(password, user.get("password")):
        raise ReauthenticationError("Incorrect password")
    if role != "super_admin" and int(user.get("vendor_id") or 0) != int(vendor_id):
        raise ReauthenticationError("The login does not belong to this business")

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    # These rows are short-lived credentials, not an audit log. Keep the table
    # bounded while retaining active tokens long enough for the confirmation flow.
    cursor.execute(
        "DELETE FROM salary_reauth_tokens WHERE used_at IS NOT NULL OR expires_at < ?",
        (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),),
    )
    cursor.execute(
        """INSERT INTO salary_reauth_tokens
               (token_hash, vendor_id, username, purpose, expires_at)
             VALUES (?, ?, ?, ?, ?)""",
        (token_hash, vendor_id, username, purpose, expires_at.isoformat(timespec="seconds")),
    )
    return raw_token, expires_at


def consume_reauth_token(cursor, vendor_id, username, raw_token, purpose):
    if not raw_token:
        raise ReauthenticationError("Password confirmation is required")
    token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
    cursor.execute(
        """SELECT token_hash, expires_at, used_at
             FROM salary_reauth_tokens
            WHERE token_hash = ? AND vendor_id = ? AND username = ? AND purpose = ?""",
        (token_hash, vendor_id, username, purpose),
    )
    row = _row_dict(cursor.fetchone())
    if not row or row.get("used_at") is not None:
        raise ReauthenticationError("Password confirmation is invalid or has already been used")
    expires = row.get("expires_at")
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires.replace("Z", "+00:00")).replace(tzinfo=None)
    if not isinstance(expires, datetime) or expires <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise ReauthenticationError("Password confirmation expired; please confirm again")
    cursor.execute(
        """UPDATE salary_reauth_tokens SET used_at = CURRENT_TIMESTAMP
            WHERE token_hash = ? AND used_at IS NULL""",
        (token_hash,),
    )
    if int(cursor.rowcount or 0) != 1:
        raise ReauthenticationError("Password confirmation has already been used")


def _current_face(cursor, vendor_id, person_id, for_update=False):
    suffix = " FOR UPDATE" if for_update else ""
    cursor.execute(
        """SELECT id, vendor_id, daily_wage, basic_salary, hra, conveyance,
                  special_allowance, pf_enabled, esi_enabled, gratuity_enabled,
                  professional_tax, late_allowance_days, late_deduction_amount,
                  joining_date, registered_at
             FROM faces WHERE id = ? AND vendor_id = ?""" + suffix,
        (person_id, vendor_id),
    )
    return _row_dict(cursor.fetchone())


def _insert_baseline(cursor, vendor_id, person_id, face, changed_by):
    values = normalize_salary_values(face)
    registered_at = face.get("registered_at")
    if isinstance(registered_at, datetime):
        registration_day = registered_at.date()
    elif isinstance(registered_at, date):
        registration_day = registered_at
    else:
        try:
            registration_day = date.fromisoformat(str(registered_at)[:10])
        except (TypeError, ValueError):
            registration_day = date.today()
    cursor.execute(
        """INSERT INTO employee_salary_versions (
               vendor_id, person_id, version_number, effective_from, effective_to,
               daily_wage, basic_salary, hra, conveyance, special_allowance,
               pf_enabled, esi_enabled, gratuity_enabled, professional_tax,
               late_allowance_days, late_deduction_amount, changed_by, change_reason
           ) VALUES (?, ?, 1, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            vendor_id, person_id, registration_day.isoformat(),
            *[values[field] for field in (
                "daily_wage", "basic_salary", "hra", "conveyance",
                "special_allowance", "pf_enabled", "esi_enabled",
                "gratuity_enabled", "professional_tax", "late_allowance_days",
                "late_deduction_amount",
            )],
            changed_by, "Initial price",
        ),
    )


def apply_salary_updates(
    conn,
    cursor,
    *,
    vendor_id,
    username,
    updates,
    effective_from,
    reason,
    reauth_token,
):
    effective_day = _date_value(effective_from)
    if effective_day > date.today():
        raise SalaryValidationError("Future salary dates are not supported yet")
    reason = str(reason or "").strip()
    if len(reason) < 3 or len(reason) > 500:
        raise SalaryValidationError("Please enter a reason between 3 and 500 characters")
    if not isinstance(updates, list) or not updates:
        raise SalaryValidationError("At least one employee salary change is required")
    if len(updates) > 500:
        raise SalaryValidationError("No more than 500 employees can be changed at once")

    consume_reauth_token(cursor, vendor_id, username, reauth_token, "salary_change")
    is_pg = bool(getattr(conn, "_is_pg", False))
    changed = []

    for update in updates:
        if not isinstance(update, dict) or update.get("person_id") is None:
            raise SalaryValidationError("Every salary change must contain person_id")
        try:
            person_id = int(update["person_id"])
        except (TypeError, ValueError):
            raise SalaryValidationError("person_id must be a number")

        face = _current_face(cursor, vendor_id, person_id, for_update=is_pg)
        if not face:
            raise SalaryValidationError(f"Employee {person_id} was not found")

        cursor.execute(
            """SELECT id, vendor_id, person_id, version_number, effective_from,
                      effective_to, daily_wage, basic_salary, hra, conveyance,
                      special_allowance, pf_enabled, esi_enabled, gratuity_enabled,
                      professional_tax, late_allowance_days, late_deduction_amount,
                      changed_by, change_reason, created_at
                 FROM employee_salary_versions
                WHERE vendor_id = ? AND person_id = ?
                ORDER BY effective_from, version_number""" + (" FOR UPDATE" if is_pg else ""),
            (vendor_id, person_id),
        )
        versions = [_row_dict(row) for row in (cursor.fetchall() or [])]
        for version in versions:
            version["effective_from"] = _date_value(version["effective_from"])
            if version.get("effective_to") is not None:
                version["effective_to"] = _date_value(version["effective_to"], "effective_to")
            for field in MONEY_FIELDS:
                if version.get(field) is not None:
                    version[field] = float(version[field])
        if not versions:
            _insert_baseline(cursor, vendor_id, person_id, face, username)
            cursor.execute(
                "SELECT * FROM employee_salary_versions WHERE vendor_id = ? AND person_id = ?",
                (vendor_id, person_id),
            )
            versions = [_row_dict(row) for row in cursor.fetchall()]
            for version in versions:
                version["effective_from"] = _date_value(version["effective_from"])
                if version.get("effective_to") is not None:
                    version["effective_to"] = _date_value(version["effective_to"], "effective_to")
                for field in MONEY_FIELDS:
                    if version.get(field) is not None:
                        version[field] = float(version[field])

        base = resolve_salary_version(versions, effective_day)
        if not base:
            raise SalaryConflictError(f"No salary baseline exists for employee {person_id}")
        expected = update.get("expected_salary_version")
        latest_visible = resolve_salary_version(versions, date.today()) or base
        if expected is not None and int(expected) != int(latest_visible["version_number"]):
            raise SalaryConflictError(
                f"Employee {person_id}'s salary changed in another session; refresh and try again"
            )
        new_values = normalize_salary_values(update, base)
        joining_date = update.get("joining_date", face.get("joining_date"))
        if joining_date not in (None, ""):
            joining_date = _date_value(joining_date, "joining_date")

        salary_changed = not salary_values_equal(new_values, base)
        joining_changed = str(joining_date or "") != str(face.get("joining_date") or "")
        if not salary_changed and not joining_changed:
            continue

        new_version_number = max(int(item["version_number"]) for item in versions) + 1
        new_version_id = None
        if salary_changed:
            old_effective_to = base.get("effective_to")
            cursor.execute(
                "UPDATE employee_salary_versions SET effective_to = ? WHERE id = ?",
                (effective_day.isoformat(), base["id"]),
            )
            cursor.execute(
                """INSERT INTO employee_salary_versions (
                       vendor_id, person_id, version_number, effective_from, effective_to,
                       daily_wage, basic_salary, hra, conveyance, special_allowance,
                       pf_enabled, esi_enabled, gratuity_enabled, professional_tax,
                       late_allowance_days, late_deduction_amount, changed_by, change_reason
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    vendor_id, person_id, new_version_number, effective_day.isoformat(),
                    old_effective_to.isoformat() if hasattr(old_effective_to, "isoformat") else old_effective_to,
                    *[new_values[field] for field in (
                        "daily_wage", "basic_salary", "hra", "conveyance",
                        "special_allowance", "pf_enabled", "esi_enabled",
                        "gratuity_enabled", "professional_tax", "late_allowance_days",
                        "late_deduction_amount",
                    )],
                    username, reason,
                ),
            )
            new_version_id = cursor.lastrowid

        # faces remains a compatibility snapshot of the salary effective today.
        all_versions = load_salary_versions(cursor, vendor_id, [person_id]).get(person_id, [])
        active_today = resolve_salary_version(all_versions, date.today()) or new_values
        cursor.execute(
            """UPDATE faces SET daily_wage = ?, basic_salary = ?, hra = ?,
                      conveyance = ?, special_allowance = ?, pf_enabled = ?,
                      esi_enabled = ?, gratuity_enabled = ?, professional_tax = ?,
                      late_allowance_days = ?, late_deduction_amount = ?, joining_date = ?
                WHERE id = ? AND vendor_id = ?""",
            (
                *[active_today.get(field) for field in (
                    "daily_wage", "basic_salary", "hra", "conveyance",
                    "special_allowance", "pf_enabled", "esi_enabled",
                    "gratuity_enabled", "professional_tax", "late_allowance_days",
                    "late_deduction_amount",
                )],
                joining_date.isoformat() if hasattr(joining_date, "isoformat") else joining_date,
                person_id, vendor_id,
            ),
        )
        changed.append({
            "person_id": person_id,
            "salary_version": new_version_number if salary_changed else base["version_number"],
            "salary_version_id": new_version_id,
        })
    return changed


def serialize_salary_version(version):
    output = dict(version)
    for field in ("effective_from", "effective_to", "created_at"):
        value = output.get(field)
        if hasattr(value, "isoformat"):
            output[field] = value.isoformat()
    for field in MONEY_FIELDS:
        if output.get(field) is not None:
            output[field] = float(output[field])
    return output
