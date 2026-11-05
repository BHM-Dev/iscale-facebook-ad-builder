"""add daily close snapshots"""
from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "ad5e6f708192"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("daily_close_versions"):
        op.create_table(
            "daily_close_versions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("account_id", sa.String(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("revenue_as_of", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("target_roas", sa.Numeric(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("posted_by", sa.String(), nullable=True),
            sa.UniqueConstraint("account_id", "day", "version", name="uq_daily_close_account_day_version"),
        )
        op.create_index("ix_daily_close_versions_account_id", "daily_close_versions", ["account_id"])
        op.create_index("ix_daily_close_account_day", "daily_close_versions", ["account_id", "day"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("daily_close_versions"):
        op.drop_table("daily_close_versions")
