"""initial schema

Revision ID: 0001
"""
from alembic import op

from app.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # The first revision builds the tables straight from the models; later
    # changes get their own hand-written revisions.
    Base.metadata.create_all(op.get_bind())


def downgrade():
    Base.metadata.drop_all(op.get_bind())
