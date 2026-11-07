"""add content_hash index to pages

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX IF NOT EXISTS ix_pages_content_hash ON pages (content_hash)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_pages_content_hash")
