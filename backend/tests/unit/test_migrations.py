from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.models import Base


def test_migrations_chain_and_models_agreement():
    """M2: test that alembic revisions form a valid chain and models match expected tables."""
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    assert alembic_ini.exists(), "alembic.ini not found"
    cfg = Config(str(alembic_ini))
    script = ScriptDirectory.from_config(cfg)

    # Verify migration chain has a single current head
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected single head, got {heads}"
    head_rev = heads[0]
    assert head_rev == "0002"

    # Check that base rev 0001 leads to 0002
    rev_0001 = script.get_revision("0001")
    rev_0002 = script.get_revision("0002")
    assert rev_0001 is not None
    assert rev_0002 is not None
    assert rev_0002.down_revision == "0001"

    # Verify all expected tables exist in models metadata
    tables = Base.metadata.tables.keys()
    for expected in (
        "documents", "pages", "invoices", "line_items", "extracted_fields",
        "validation_results", "corrections", "reconciliation_runs",
        "reconciliation_items", "llm_calls", "jobs", "processing_events"
    ):
        assert expected in tables, f"Expected table '{expected}' missing from models"
