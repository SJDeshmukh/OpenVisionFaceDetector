#!/usr/bin/env python3
"""Audit or backfill the attendance event ledger.

Run from the backend directory:
  python scripts/reconcile_attendance_events.py
  python scripts/reconcile_attendance_events.py --vendor-id 12 --backfill
"""

import argparse
import json

from db_factory import get_db_connection
from services.attendance_reconciliation_service import backfill, summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor-id", type=int)
    parser.add_argument("--source-timezone", default=None)
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args()

    connection = get_db_connection()
    cursor = connection.cursor()
    backfilled = 0
    try:
        before = summarize(cursor, args.vendor_id)
        if args.backfill:
            backfilled = backfill(
                cursor,
                args.vendor_id,
                source_timezone=args.source_timezone,
            )
            connection.commit()
        after = summarize(cursor, args.vendor_id)
        print(json.dumps({
            "vendor_id": args.vendor_id,
            "before": before.__dict__,
            "backfilled": backfilled,
            "after": after.__dict__,
        }, indent=2, sort_keys=True))
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
