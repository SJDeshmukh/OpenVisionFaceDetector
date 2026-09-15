"""Add normalized workforce structure and effective-dated shifts.

Revision ID: c62e3e87a2b1
Revises: b51d2d76f1a0
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = "c62e3e87a2b1"
down_revision = "b51d2d76f1a0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location_type", sa.String(40), nullable=False, server_default="OFFICE"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("address", sa.Text()),
        sa.Column("geofence_lat", sa.Float()),
        sa.Column("geofence_lng", sa.Float()),
        sa.Column("geofence_radius_m", sa.Float()),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vendor_id", "code", name="uq_location_vendor_code"),
    )
    op.create_table(
        "organization_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("organization_units.id")),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id")),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit_type", sa.String(40), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vendor_id", "code", name="uq_org_unit_vendor_code"),
    )
    op.create_table(
        "shifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vendor_id", "code", name="uq_shift_vendor_code"),
    )
    op.create_table(
        "person_organization_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("faces.id"), nullable=False),
        sa.Column("organization_unit_id", sa.Integer(), sa.ForeignKey("organization_units.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_primary", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "shift_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("end_time", sa.String(5), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("operational_day_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("grace_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_cross_midnight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("shift_id", "version_number", name="uq_shift_version_number"),
    )
    op.create_table(
        "shift_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("shift_version_id", sa.Integer(), sa.ForeignKey("shift_versions.id"), nullable=False),
        sa.Column("segment_type", sa.String(30), nullable=False),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("end_time", sa.String(5), nullable=False),
        sa.Column("is_paid", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "shift_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id"), nullable=False),
        sa.Column("scope_type", sa.String(30), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("faces.id")),
        sa.Column("organization_unit_id", sa.Integer(), sa.ForeignKey("organization_units.id")),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id")),
        sa.Column("group_key", sa.String(255)),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assignment_source", sa.String(40), nullable=False, server_default="MANUAL"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "holiday_calendars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "holidays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("calendar_id", sa.Integer(), sa.ForeignKey("holiday_calendars.id"), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_paid", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("calendar_id", "holiday_date", name="uq_calendar_holiday_date"),
    )
    op.create_table(
        "weekly_off_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("weekdays", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id")),
        sa.Column("organization_unit_id", sa.Integer(), sa.ForeignKey("organization_units.id")),
    )
    op.create_index("idx_shift_assignment_resolution", "shift_assignments", ["vendor_id", "person_id", "effective_from", "effective_to"])
    op.create_index("idx_shift_version_resolution", "shift_versions", ["vendor_id", "shift_id", "effective_from", "effective_to"])
    op.create_index("idx_person_org_resolution", "person_organization_assignments", ["vendor_id", "person_id", "effective_from", "effective_to"])


def downgrade():
    op.drop_index("idx_person_org_resolution", table_name="person_organization_assignments")
    op.drop_index("idx_shift_version_resolution", table_name="shift_versions")
    op.drop_index("idx_shift_assignment_resolution", table_name="shift_assignments")
    for table in ("weekly_off_patterns", "holidays", "holiday_calendars", "shift_assignments", "shift_segments", "shift_versions", "person_organization_assignments", "shifts", "organization_units", "locations"):
        op.drop_table(table)
