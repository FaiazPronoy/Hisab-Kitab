"""sheet roles, reviewers, supplier memory and payment batches

Revision ID: 0003
Revises: 0002
"""
from alembic import op

from app.db.models import Base, PaymentBatch, SupplierAlias, SupplierLabel, User

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

COLUMNS = [
    ("documents", "role", "VARCHAR(20)"),
    ("invoices", "bank_account", "VARCHAR(64)"),
    ("invoices", "bank_evidence", "JSONB"),
    ("invoices", "approved_by", "VARCHAR(100)"),
    ("invoices", "approved_at", "TIMESTAMPTZ"),
    ("invoices", "payment_batch_id", "UUID"),
    ("corrections", "corrected_by_id", "INTEGER"),
]


def upgrade():
    # 0001 builds tables from the current models, so on a fresh database
    # these already exist; IF NOT EXISTS keeps both paths working
    for table, col, typ in COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_payment_batch_id ON invoices (payment_batch_id)")
    tables = [m.__table__ for m in (User, SupplierLabel, SupplierAlias, PaymentBatch)]
    Base.metadata.create_all(op.get_bind(), tables=tables)


def downgrade():
    for m in (PaymentBatch, SupplierAlias, SupplierLabel, User):
        m.__table__.drop(op.get_bind(), checkfirst=True)
    for table, col, _ in reversed(COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
