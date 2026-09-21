"""Versioned, vendor-specific leave approval workflows.

The legacy leave columns remain populated for backwards compatibility, but all
new routing decisions are made from the per-request stage snapshot.  A snapshot
prevents a later workflow edit from changing an approval already in progress.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone


DEFAULT_STAGES = [
    {
        "stage_key": "rector",
        "display_name": "Rector",
        "actor_type": "staff",
        "role_key": "rector",
        "department_scoped": False,
        "auth_method": "staff_pin",
    },
    {
        "stage_key": "hod",
        "display_name": "HOD",
        "actor_type": "staff",
        "role_key": "hod",
        "department_scoped": True,
        "auth_method": "staff_pin",
    },
    {
        "stage_key": "parent",
        "display_name": "Parent",
        "actor_type": "parent",
        "role_key": "parent",
        "department_scoped": False,
        "auth_method": "face",
    },
]

ALLOWED_ACTOR_TYPES = {"staff", "parent"}
ALLOWED_AUTH_METHODS = {"staff_pin", "staff_session", "face"}


def _row_dict(row):
    if row is None:
        return None
    try:
        return dict(row)
    except (TypeError, ValueError):
        return row


def _fetch_id(cursor, is_pg):
    if is_pg:
        row = cursor.fetchone()
        mapped = _row_dict(row)
        return int(mapped.get("id") if isinstance(mapped, dict) else row[0])
    return int(cursor.lastrowid)


def _slug(value, fallback):
    value = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return value or fallback


def normalize_stages(stages):
    if not isinstance(stages, list) or not stages:
        raise ValueError("At least one approval stage is required")
    if len(stages) > 12:
        raise ValueError("A workflow can contain at most 12 stages")

    normalized = []
    keys = set()
    parent_count = 0
    for index, raw in enumerate(stages, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Stage {index} is invalid")
        display_name = str(raw.get("display_name") or raw.get("name") or "").strip()
        if not display_name or len(display_name) > 80:
            raise ValueError(f"Stage {index} needs a name of at most 80 characters")
        actor_type = str(raw.get("actor_type") or "staff").strip().lower()
        if actor_type not in ALLOWED_ACTOR_TYPES:
            raise ValueError(f"Stage {display_name} has an invalid actor type")

        role_key = "parent" if actor_type == "parent" else _slug(
            raw.get("role_key") or display_name, f"stage_{index}"
        )
        stage_key = _slug(raw.get("stage_key") or role_key, f"stage_{index}")
        if stage_key in keys:
            raise ValueError(f"Stage key '{stage_key}' is duplicated")
        keys.add(stage_key)

        auth_method = str(raw.get("auth_method") or ("face" if actor_type == "parent" else "staff_pin"))
        if auth_method not in ALLOWED_AUTH_METHODS:
            raise ValueError(f"Stage {display_name} has an invalid authentication method")
        if actor_type == "parent":
            parent_count += 1
            auth_method = "face"
        elif auth_method == "face":
            raise ValueError("Face authentication is currently supported only for parent stages")

        normalized.append(
            {
                "stage_key": stage_key,
                "display_name": display_name,
                "actor_type": actor_type,
                "role_key": role_key,
                "sequence": index,
                "department_scoped": bool(raw.get("department_scoped", False)),
                "auth_method": auth_method,
            }
        )
    if parent_count > 1:
        raise ValueError("A workflow can contain only one Parent stage")
    return normalized


def _workflow_stages(cursor, workflow_id):
    cursor.execute(
        """SELECT stage_key, display_name, actor_type, role_key, sequence,
                  department_scoped, auth_method
           FROM leave_workflow_stages WHERE workflow_id = ? ORDER BY sequence""",
        (workflow_id,),
    )
    columns = (
        "stage_key", "display_name", "actor_type", "role_key", "sequence",
        "department_scoped", "auth_method",
    )
    result = []
    for row in cursor.fetchall():
        mapped = _row_dict(row)
        result.append(mapped if isinstance(mapped, dict) else dict(zip(columns, row)))
    return result


def get_active_workflow(conn, vendor_id, create_default=True):
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, vendor_id, name, version, is_active, created_by, created_at
           FROM leave_workflows WHERE vendor_id = ? AND is_active = 1
           ORDER BY version DESC LIMIT 1""",
        (vendor_id,),
    )
    row = cursor.fetchone()
    if row is None and create_default:
        try:
            return replace_workflow(conn, vendor_id, "Default Leave Approval", DEFAULT_STAGES, "system")
        except Exception as exc:
            # Multiple web workers can initialise the same vendor concurrently.
            # The unique (vendor_id, version) constraint chooses one winner.
            conn.rollback()
            existing = get_active_workflow(conn, vendor_id, create_default=False)
            if existing is None:
                raise exc
            return existing
    if row is None:
        return None
    workflow = _row_dict(row)
    if not isinstance(workflow, dict):
        workflow = dict(zip(
            ("id", "vendor_id", "name", "version", "is_active", "created_by", "created_at"),
            row,
        ))
    workflow["stages"] = _workflow_stages(cursor, workflow["id"])
    return workflow


def replace_workflow(conn, vendor_id, name, stages, created_by):
    normalized = normalize_stages(stages)
    cursor = conn.cursor()
    is_pg = bool(getattr(conn, "_is_pg", False))
    if is_pg:
        # Serialize workflow version allocation per vendor across Gunicorn workers.
        cursor.execute("SELECT pg_advisory_xact_lock(734918, ?)", (int(vendor_id),))
    cursor.execute("SELECT COALESCE(MAX(version), 0) FROM leave_workflows WHERE vendor_id = ?", (vendor_id,))
    row = cursor.fetchone()
    version = int(row[0] or 0) + 1
    cursor.execute("UPDATE leave_workflows SET is_active = 0 WHERE vendor_id = ?", (vendor_id,))
    if is_pg:
        cursor.execute(
            """INSERT INTO leave_workflows
               (vendor_id, name, version, is_active, created_by)
               VALUES (?, ?, ?, 1, ?) RETURNING id""",
            (vendor_id, str(name or "Leave Approval").strip()[:120], version, created_by),
        )
    else:
        cursor.execute(
            """INSERT INTO leave_workflows
               (vendor_id, name, version, is_active, created_by)
               VALUES (?, ?, ?, 1, ?)""",
            (vendor_id, str(name or "Leave Approval").strip()[:120], version, created_by),
        )
    workflow_id = _fetch_id(cursor, is_pg)
    for stage in normalized:
        cursor.execute(
            """INSERT INTO leave_workflow_stages
               (workflow_id, stage_key, display_name, actor_type, role_key,
                sequence, department_scoped, auth_method)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                workflow_id,
                stage["stage_key"],
                stage["display_name"],
                stage["actor_type"],
                stage["role_key"],
                stage["sequence"],
                int(stage["department_scoped"]),
                stage["auth_method"],
            ),
        )
    conn.commit()
    return get_active_workflow(conn, vendor_id, create_default=False)


def snapshot_request(conn, vendor_id, request_id, legacy_request=None):
    """Create or return the immutable ordered stages for a leave request."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, request_id, vendor_id, workflow_id, workflow_version,
                  stage_key, display_name, actor_type, role_key, sequence,
                  department_scoped, auth_method, status, actor_id, actor_name,
                  decided_at, decision_metadata
           FROM leave_request_stages WHERE request_id = ? ORDER BY sequence""",
        (request_id,),
    )
    columns = (
        "id", "request_id", "vendor_id", "workflow_id", "workflow_version",
        "stage_key", "display_name", "actor_type", "role_key", "sequence",
        "department_scoped", "auth_method", "status", "actor_id", "actor_name",
        "decided_at", "decision_metadata",
    )
    existing = []
    for row in cursor.fetchall():
        mapped = _row_dict(row)
        existing.append(mapped if isinstance(mapped, dict) else dict(zip(columns, row)))
    if existing:
        return existing

    workflow = get_active_workflow(conn, vendor_id)
    legacy_request = legacy_request or {}
    final_status = str(legacy_request.get("final_status") or "pending")
    rejected_seen = False
    for stage in workflow["stages"]:
        legacy_status = legacy_request.get(f"{stage['stage_key']}_status")
        status = str(legacy_status or "pending")
        if rejected_seen:
            status = "skipped"
        elif status == "rejected":
            rejected_seen = True
        elif final_status == "approved" and legacy_status is None:
            status = "approved"
        cursor.execute(
            """INSERT INTO leave_request_stages
               (request_id, vendor_id, workflow_id, workflow_version, stage_key,
                display_name, actor_type, role_key, sequence, department_scoped,
                auth_method, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id,
                vendor_id,
                workflow["id"],
                workflow["version"],
                stage["stage_key"],
                stage["display_name"],
                stage["actor_type"],
                stage["role_key"],
                stage["sequence"],
                int(stage["department_scoped"]),
                stage["auth_method"],
                status,
            ),
        )
    conn.commit()
    return snapshot_request(conn, vendor_id, request_id)


def current_stage(stages):
    for stage in sorted(stages, key=lambda item: int(item["sequence"])):
        if stage["status"] == "pending":
            return stage
        if stage["status"] != "approved":
            return None
    return None


def attach_approval_steps(conn, requests):
    for request_row in requests:
        steps = snapshot_request(
            conn,
            request_row["vendor_id"],
            request_row["id"],
            request_row,
        )
        request_row["approval_steps"] = steps
        request_row["current_stage"] = current_stage(steps)
    return requests


def backfill_legacy_requests(conn):
    """Snapshot pre-workflow requests during startup before admins can edit a flow."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT lr.* FROM leave_requests lr
           LEFT JOIN leave_request_stages lrs ON lrs.request_id = lr.id
           WHERE lrs.id IS NULL ORDER BY lr.vendor_id, lr.id"""
    )
    rows = cursor.fetchall() or []
    columns = [item[0] for item in (cursor.description or [])]
    count = 0
    for row in rows:
        mapped = _row_dict(row)
        if not isinstance(mapped, dict):
            mapped = dict(zip(columns, row))
        snapshot_request(conn, mapped["vendor_id"], mapped["id"], mapped)
        count += 1
    return count


def decide_current_stage(
    conn,
    vendor_id,
    request_row,
    action,
    *,
    actor_type,
    role_key,
    actor_id,
    actor_name,
    metadata=None,
):
    stages = snapshot_request(conn, vendor_id, request_row["id"], request_row)
    stage = current_stage(stages)
    if not stage:
        raise ValueError("Leave request is not awaiting an approval")
    if stage["actor_type"] != actor_type:
        raise PermissionError(f"Leave request is awaiting {stage['display_name']} approval")
    if actor_type == "staff" and stage["role_key"] != role_key:
        raise PermissionError(f"Leave request is awaiting {stage['display_name']} approval")

    cursor = conn.cursor()
    cursor.execute(
        """UPDATE leave_request_stages
           SET status = ?, actor_id = ?, actor_name = ?, decided_at = ?, decision_metadata = ?
           WHERE id = ? AND vendor_id = ? AND status = 'pending'""",
        (
            action,
            str(actor_id) if actor_id is not None else None,
            actor_name,
            datetime.now(timezone.utc).isoformat(),
            json.dumps(metadata or {}, separators=(",", ":")),
            stage["id"],
            vendor_id,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("Leave request was already processed")

    # Continue populating legacy fields while older clients/reports still use them.
    if stage["stage_key"] in {"rector", "hod", "parent"}:
        column = f"{stage['stage_key']}_status"
        cursor.execute(
            f"UPDATE leave_requests SET {column} = ? WHERE id = ? AND vendor_id = ?",
            (action, request_row["id"], vendor_id),
        )

    if action == "rejected":
        cursor.execute(
            """UPDATE leave_request_stages SET status = 'skipped'
               WHERE request_id = ? AND vendor_id = ? AND sequence > ? AND status = 'pending'""",
            (request_row["id"], vendor_id, stage["sequence"]),
        )
        cursor.execute(
            "UPDATE leave_requests SET final_status = 'rejected' WHERE id = ? AND vendor_id = ?",
            (request_row["id"], vendor_id),
        )
    else:
        refreshed = snapshot_request(conn, vendor_id, request_row["id"])
        # snapshot_request reads before this transaction is committed, including
        # the current update on both SQLite and PostgreSQL connections.
        if current_stage(refreshed) is None and all(item["status"] == "approved" for item in refreshed):
            cursor.execute(
                "UPDATE leave_requests SET final_status = 'approved' WHERE id = ? AND vendor_id = ?",
                (request_row["id"], vendor_id),
            )
    conn.commit()
    return stage
