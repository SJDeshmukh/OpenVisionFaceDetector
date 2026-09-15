"""Canonical entry point for attendance event persistence.

Phase 0 continues to write the existing ``attendance`` table. Phase 1 will add
the immutable event ledger behind this interface, allowing callers to remain
unchanged while dual-write and reconciliation are introduced.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Any, Optional
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from domain.attendance import AttendanceEventSource, AttendanceEventType


logger = logging.getLogger(__name__)
MAX_CLIENT_CLOCK_DRIFT = timedelta(hours=24)


def resolve_client_event_time(
    timestamp: Optional[str],
    *,
    server_now: Optional[datetime] = None,
    max_clock_drift: timedelta = MAX_CLIENT_CLOCK_DRIFT,
) -> datetime:
    """Resolve a bounded, timezone-naive legacy event timestamp.

    The current schema stores naive datetimes, so Phase 0 deliberately retains
    that contract. New ledger events will store UTC plus the source timezone.
    Live clients omit the timestamp; a recent timestamp is accepted for offline
    replay. Invalid or implausible device clocks fall back to server time.
    """

    now = server_now or datetime.now()
    if not timestamp:
        return now

    parsed = None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(timestamp, fmt)
            break
        except (ValueError, TypeError):
            continue

    if parsed is None or abs(now - parsed) > max_clock_drift:
        logger.warning("Ignoring implausible attendance timestamp; using server time")
        return now
    return parsed


@dataclass(frozen=True)
class LegacyAttendanceEvent:
    """Validated write contract for the existing attendance table."""

    name: str
    timestamp: Any
    status: str
    vendor_id: Optional[int]
    person_id: Optional[int]
    captured_image: Optional[str] = None
    activity: str = "Work"
    is_late: int = 0
    device_id: Optional[str] = None
    attendance_date: Any = None
    class_year: Optional[str] = None
    division: Optional[str] = None
    branch: Optional[str] = None
    subject: Optional[str] = None
    lecture_id: Optional[int] = None
    source: str = AttendanceEventSource.API.value
    source_event_id: Optional[str] = None
    source_timezone: Optional[str] = None
    verification_method: Optional[str] = None
    verification_score: Optional[float] = None
    payload_metadata: Optional[dict] = None

    def __post_init__(self):
        valid_statuses = {item.value for item in AttendanceEventType}
        if self.status not in valid_statuses:
            raise ValueError(f"Unsupported attendance event type: {self.status}")
        if not str(self.name or "").strip():
            raise ValueError("Attendance event name is required")
        if self.timestamp is None:
            raise ValueError("Attendance event timestamp is required")
        if self.vendor_id is None:
            raise ValueError("Attendance event vendor_id is required")
        if self.person_id is None:
            raise ValueError("Attendance event person_id is required")
        valid_sources = {item.value for item in AttendanceEventSource}
        if self.source not in valid_sources:
            raise ValueError(f"Unsupported attendance event source: {self.source}")


@dataclass(frozen=True)
class IngestionResult:
    event_id: str
    legacy_attendance_id: Optional[int]
    duplicate: bool = False
    event_type: Optional[str] = None


class AttendanceEventIngestionService:
    """Persist attendance through a caller-owned database transaction."""

    _OPTIONAL_COLUMNS = (
        "captured_image",
        "activity",
        "is_late",
        "device_id",
        "attendance_date",
        "class_year",
        "division",
        "branch",
        "subject",
        "lecture_id",
    )

    @classmethod
    def insert_legacy_event(cls, cursor, event: LegacyAttendanceEvent):
        """Insert one event without committing the caller's transaction.

        Question-mark placeholders are intentional: the repository's database
        wrapper translates them for PostgreSQL and SQLite accepts them natively.
        """

        columns = ["name", "timestamp", "status", "vendor_id", "person_id"]
        values = [event.name, event.timestamp, event.status, event.vendor_id, event.person_id]

        for column in cls._OPTIONAL_COLUMNS:
            value = getattr(event, column)
            if value is not None:
                columns.append(column)
                values.append(value)

        values = [
            value.isoformat(sep=" ") if isinstance(value, datetime) else value
            for value in values
        ]
        placeholders = ", ".join("?" for _ in columns)
        cursor.execute(
            f"INSERT INTO attendance ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values),
        )
        return getattr(cursor, "lastrowid", None)

    @staticmethod
    def _utc_event_time(event: LegacyAttendanceEvent) -> tuple[datetime, str]:
        value = event.timestamp
        if isinstance(value, str):
            parsed = None
            for candidate in (value, value.replace("Z", "+00:00")):
                try:
                    parsed = datetime.fromisoformat(candidate)
                    break
                except (TypeError, ValueError):
                    continue
            if parsed is None:
                raise ValueError("Attendance event timestamp is not ISO-8601 compatible")
            value = parsed
        if not isinstance(value, datetime):
            raise ValueError("Attendance event timestamp must be a datetime or ISO-8601 string")

        timezone_name = event.source_timezone or os.environ.get("DEFAULT_TIMEZONE", "Asia/Kolkata")
        try:
            source_zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown attendance event timezone: {timezone_name}") from exc

        if value.tzinfo is None:
            value = value.replace(tzinfo=source_zone)
        utc_value = value.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        return utc_value, timezone_name

    @classmethod
    def find_idempotent_event(cls, cursor, vendor_id, source, source_event_id):
        if not source_event_id:
            return None
        cursor.execute(
            """SELECT id, legacy_attendance_id, event_type
               FROM attendance_events
               WHERE vendor_id = ? AND source = ? AND source_event_id = ?
               LIMIT 1""",
            (vendor_id, source, source_event_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return IngestionResult(
            event_id=str(row[0]),
            legacy_attendance_id=row[1],
            duplicate=True,
            event_type=row[2],
        )

    @classmethod
    def ingest(cls, cursor, event: LegacyAttendanceEvent) -> IngestionResult:
        """Atomically write the legacy record and immutable ledger projection.

        The caller owns commit/rollback. A repeated client idempotency key returns
        the original result and creates neither a second ledger event nor a
        second legacy attendance row.
        """

        source_event_id = str(event.source_event_id or uuid.uuid4())
        existing = cls.find_idempotent_event(
            cursor, event.vendor_id, event.source, source_event_id
        )
        if existing:
            return existing

        legacy_id = cls.insert_legacy_event(cursor, event)
        return cls.insert_ledger_projection(cursor, event, legacy_id, source_event_id)

    @classmethod
    def insert_ledger_projection(
        cls,
        cursor,
        event: LegacyAttendanceEvent,
        legacy_attendance_id: int,
        source_event_id: Optional[str] = None,
    ) -> IngestionResult:
        """Create only the ledger projection for an existing legacy row.

        This is used by historical backfill and by ``ingest`` after its legacy
        insert. It is idempotent for a stable source event ID.
        """

        resolved_source_event_id = str(source_event_id or event.source_event_id or uuid.uuid4())
        existing = cls.find_idempotent_event(
            cursor, event.vendor_id, event.source, resolved_source_event_id
        )
        if existing:
            return existing

        event_id = str(uuid.uuid4())
        event_time_utc, timezone_name = cls._utc_event_time(event)
        received_at_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        metadata = json.dumps(event.payload_metadata or {}, separators=(",", ":"), sort_keys=True)
        cursor.execute(
            """INSERT INTO attendance_events
               (id, vendor_id, person_id, legacy_attendance_id, event_type,
                event_time_utc, event_timezone, received_at_utc, source,
                source_event_id, device_id, activity_code, verification_method,
                verification_score, captured_image_reference, payload_metadata,
                ingestion_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, event.vendor_id, event.person_id, legacy_attendance_id, event.status,
                event_time_utc.isoformat(sep=" "), timezone_name,
                received_at_utc.isoformat(sep=" "), event.source,
                resolved_source_event_id, event.device_id, event.activity,
                event.verification_method, event.verification_score,
                event.captured_image, metadata, "ACCEPTED",
                received_at_utc.isoformat(sep=" "),
            ),
        )
        return IngestionResult(
            event_id=event_id,
            legacy_attendance_id=legacy_attendance_id,
            duplicate=False,
            event_type=event.status,
        )
