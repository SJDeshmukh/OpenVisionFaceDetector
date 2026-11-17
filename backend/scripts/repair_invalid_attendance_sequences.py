#!/usr/bin/env python3
"""Audit or repair invalid historical work-attendance transitions.

Dry-run is the default and does not modify data:
  python scripts/repair_invalid_attendance_sequences.py \
    --vendor-id 8 --start-date 2026-10-01 --end-date 2026-10-31

After reviewing the JSON output, apply the exact same scope explicitly:
  python scripts/repair_invalid_attendance_sequences.py \
    --vendor-id 8 --start-date 2026-10-01 --end-date 2026-10-31 \
    --apply --actor admin@example.com
"""

import argparse
from datetime import date
import json
from pathlib import Path
import sys


# Executing ``python scripts/<name>.py`` makes ``scripts`` the first import
# directory. Add the backend root explicitly so local modules resolve exactly
# as they do under Gunicorn and pytest.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.attendance_sequence_repair_service import (
    apply_findings,
    find_invalid_transitions,
    load_projection_rows,
)


def _iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor-id", type=int, required=True)
    parser.add_argument("--start-date", type=_iso_date, required=True)
    parser.add_argument("--end-date", type=_iso_date, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", help="Required with --apply for the repair audit trail")
    args = parser.parse_args()

    if args.vendor_id <= 0:
        parser.error("--vendor-id must be positive")
    if args.start_date > args.end_date:
        parser.error("--start-date cannot be after --end-date")
    if args.apply and not str(args.actor or "").strip():
        parser.error("--actor is required with --apply")

    # Keep the database dependency lazy so help/argument validation can run in
    # lightweight maintenance environments.
    from db_factory import get_db_connection

    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        rows = load_projection_rows(
            cursor, args.vendor_id, args.start_date, args.end_date
        )
        findings = find_invalid_transitions(rows)
        output = {
            "mode": "apply" if args.apply else "dry-run",
            "vendor_id": args.vendor_id,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "rows_scanned": len(rows),
            "invalid_count": len(findings),
            "repairable_count": sum(item.repair_eligible for item in findings),
            "manual_review_count": sum(not item.repair_eligible for item in findings),
            "reason_counts": {},
            "findings": [finding.as_dict() for finding in findings],
        }
        for finding in findings:
            output["reason_counts"][finding.reason] = (
                output["reason_counts"].get(finding.reason, 0) + 1
            )

        if args.apply:
            output["repair"] = apply_findings(
                cursor, findings, repaired_by=args.actor
            )
            connection.commit()
        else:
            connection.rollback()

        print(json.dumps(output, indent=2, sort_keys=True, default=str))
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
