"""hash refresh tokens at rest

Revision ID: z1a2b3c4d5e6
Revises: y3u1v7w8x0t6
Create Date: 2026-09-07

Refresh tokens were stored in plaintext in refresh_tokens.token — a DB
compromise (backup leak, SQL injection, insider access) would hand over
every live refresh token as-is, letting an attacker mint new access tokens
for the token's full lifetime with no password needed.

Adds token_hash (SHA-256 of the token, computed in app/api/v1/auth.py) as
the new lookup column, and loosens token's NOT NULL constraint since new
code stops writing to it. Deliberately additive/loosening only — no column
drop here (matches this repo's established migration convention; a future
migration can drop `token` once nothing depends on it).

Existing rows are deleted rather than left as orphaned plaintext, since
this deploy invalidates every session anyway (the lookup column changes,
so no existing row can match a hash-based query regardless) — every user
must log in again after this deploys.
"""
from alembic import op


revision = 'z1a2b3c4d5e6'
down_revision = 'y3u1v7w8x0t6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS token_hash VARCHAR")
    op.execute("ALTER TABLE refresh_tokens ALTER COLUMN token DROP NOT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_refresh_tokens_token_hash ON refresh_tokens (token_hash)")
    # Every existing row is plaintext-only (no token_hash) and will never
    # match a hash-based lookup again — delete rather than leave as inert,
    # still-sensitive plaintext.
    op.execute("DELETE FROM refresh_tokens")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_refresh_tokens_token_hash")
    # Deliberately NOT restoring `token`'s NOT NULL constraint: any row
    # created after upgrade() has token=NULL (new code never writes to it),
    # so SET NOT NULL would fail with "column contains null values" on any
    # database that's had even one login/refresh since upgrading — leaving
    # it nullable is harmless and avoids that failure mode.
    op.execute("ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS token_hash")
