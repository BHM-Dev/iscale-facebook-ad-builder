"""add app_feedback (in-app feedback, one row per submission)"""
from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # init_db's create_all runs first and may already have built this table.
    if sa.inspect(bind).has_table("app_feedback"):
        return
    op.create_table(
        "app_feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_email", sa.String(), nullable=True),
        sa.Column("page_path", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("screenshot_url", sa.String(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("soft_tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_app_feedback_status", "app_feedback", ["status"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("app_feedback"):
        op.drop_table("app_feedback")
