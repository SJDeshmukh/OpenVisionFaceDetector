"""Stable attendance vocabulary.

Keep transport strings and database values centralized so capture paths do not
invent subtly different values. These values intentionally match the existing
API/database contract during the Phase 0 migration.
"""

from enum import Enum


class AttendanceEventType(str, Enum):
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"


class AttendanceEventSource(str, Enum):
    FACE = "FACE"
    RFID = "RFID"
    MOBILE = "MOBILE"
    WEB = "WEB"
    KIOSK = "KIOSK"
    IMPORT = "IMPORT"
    API = "API"
    FACULTY_APP = "FACULTY_APP"
    BULK_IMAGE_API = "BULK_IMAGE_API"
    LEGACY = "LEGACY"


class DailyAttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"
    ON_LEAVE = "ON_LEAVE"
    HOLIDAY = "HOLIDAY"
    WEEKLY_OFF = "WEEKLY_OFF"
    WORK_FROM_HOME = "WORK_FROM_HOME"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
