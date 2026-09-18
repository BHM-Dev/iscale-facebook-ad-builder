"""add durable direct Meta launch idempotency records

Revision ID: i9j7k5l3m1n9
Revises: h8i6j4k2l0m8
"""

from alembic import op
import sqlalchemy as sa


revision = "i9j7k5l3m1n9"
down_revision = "h8i6j4k2l0m8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("meta_launch_requests"):
        return
    op.create_table(
        "meta_launch_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fb_ad_id", sa.String(), nullable=True),
        sa.Column("fb_creative_id", sa.String(), nullable=True),
        sa.Column("generated_ad_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("meta_launch_requests")
