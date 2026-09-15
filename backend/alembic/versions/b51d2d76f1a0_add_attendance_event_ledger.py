"""Add immutable attendance event ledger.

Revision ID: b51d2d76f1a0
Revises: 7994cef3f0e2
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b51d2d76f1a0"
down_revision: Union[str, Sequence[str], None] = "7994cef3f0e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("faces.id"), nullable=False),
        sa.Column("legacy_attendance_id", sa.Integer(), sa.ForeignKey("attendance.id")),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("event_time_utc", sa.DateTime(), nullable=False),
        sa.Column("event_timezone", sa.String(length=64), nullable=False),
        sa.Column("received_at_utc", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("device_id", sa.String(length=255)),
        sa.Column("location_id", sa.Integer()),
        sa.Column("activity_code", sa.String(length=255)),
        sa.Column("verification_method", sa.String(length=40)),
        sa.Column("verification_score", sa.Float()),
        sa.Column("captured_image_reference", sa.Text()),
        sa.Column("payload_metadata", sa.Text(), server_default="{}"),
        sa.Column("ingestion_status", sa.String(length=30), nullable=False, server_default="ACCEPTED"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vendor_id", "source", "source_event_id", name="uq_attendance_event_source"),
    )
    op.create_index(
        "idx_attendance_events_person_time",
        "attendance_events",
        ["vendor_id", "person_id", "event_time_utc"],
    )
    op.create_index(
        "idx_attendance_events_device_received",
        "attendance_events",
        ["vendor_id", "device_id", "received_at_utc"],
    )


def downgrade() -> None:
    op.drop_index("idx_attendance_events_device_received", table_name="attendance_events")
    op.drop_index("idx_attendance_events_person_time", table_name="attendance_events")
    op.drop_table("attendance_events")
