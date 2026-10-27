"""add face registration idempotency key

Revision ID: f4a8c2d19e71
Revises: d73f4f98b3c2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a8c2d19e71"
down_revision: Union[str, Sequence[str], None] = "d73f4f98b3c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("faces", sa.Column("local_uid", sa.Text(), nullable=True))
    op.create_index(
        "idx_faces_vendor_local_uid",
        "faces",
        ["vendor_id", "local_uid"],
        unique=True,
        postgresql_where=sa.text("local_uid IS NOT NULL"),
        sqlite_where=sa.text("local_uid IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_faces_vendor_local_uid", table_name="faces")
    op.drop_column("faces", "local_uid")
