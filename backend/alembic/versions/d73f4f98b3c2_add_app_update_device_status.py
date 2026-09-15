"""Add per-device OTA update telemetry.

Revision ID: d73f4f98b3c2
Revises: c62e3e87a2b1
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = "d73f4f98b3c2"
down_revision = "c62e3e87a2b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_update_device_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("device_id", sa.String(255), nullable=False),
        sa.Column("release_id", sa.Integer()),
        sa.Column("target_version_code", sa.Integer(), nullable=False),
        sa.Column("installed_version_code", sa.Integer()),
        sa.Column("installed_version_name", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress", sa.Integer()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vendor_id", "device_id", "target_version_code", name="uq_device_update_target"),
    )
    op.create_index(
        "idx_app_update_status_target",
        "app_update_device_status",
        ["target_version_code", "status"],
    )


def downgrade():
    op.drop_index("idx_app_update_status_target", table_name="app_update_device_status")
    op.drop_table("app_update_device_status")
