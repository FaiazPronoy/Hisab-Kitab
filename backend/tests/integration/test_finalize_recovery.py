import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from faker import Faker

from app.db.models import Document, Page
from app.db.session import SessionLocal
from app.pipeline import process
from app.workers.tasks import finalize, pages
from eval import generator

pytestmark = pytest.mark.usefixtures("db_ready")


def _make_pdf(tmp_path: Path, seed: int = 101) -> Path:
    rng = random.Random(seed)
    inv = generator.make(Faker("en_GB"), rng, seed, "classic")
    p = tmp_path / f"test_fin_{seed}.pdf"
    generator.render(inv, p)
    return p


def test_h4_finalize_exception_never_leaves_finalizing(client, H, tmp_path, monkeypatch):
    """H4: finalize claim must be recoverable and not leave document in finalizing when extract fails."""
    p = _make_pdf(tmp_path, 102)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    # Reset to processing state with pages done
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        doc.status = "processing"
        for inv in list(doc.invoices):
            db.delete(inv)
        db.commit()

    def buggy_extract(*args, **kwargs):
        raise ValueError("Simulated unexpected extraction crash")

    monkeypatch.setattr("app.pipeline.process.extract_segment", buggy_extract)

    # Calling finalize task
    finalize(doc_id)

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "failed"
        assert doc.error_code == "FINALIZE_ERROR"
        assert "ValueError" in (doc.error_message or "")


def test_h4_finalize_lease_claim_recovery(client, H, tmp_path):
    """H4: a document stuck in finalizing whose lease expired can be claimed and finalized."""
    p = _make_pdf(tmp_path, 103)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    # Mark document as finalizing with updated_at in the past (> 300s ago)
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        doc.status = "finalizing"
        doc.updated_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        # Clear invoices to simulate aborted run before save
        for inv in list(doc.invoices):
            db.delete(inv)
        db.commit()

    with SessionLocal() as db:
        ids = process.run_finalize(db, doc_id, lease_seconds=300)
        db.commit()

    assert len(ids) > 0
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert doc.status in ("done", "needs_review")


def test_h4_finalize_resumes_without_recreating_existing_invoice(client, H, tmp_path):
    """H4: finalize skips existing segment and preserves existing invoices."""
    p = _make_pdf(tmp_path, 104)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert len(doc.invoices) > 0
        original_inv_id = doc.invoices[0].id
        doc.status = "processing"
        db.commit()

    # Run finalize again; the segment should be skipped, keeping original_inv_id
    with SessionLocal() as db:
        ids = process.run_finalize(db, doc_id)
        db.commit()

    assert original_inv_id in ids
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert any(i.id == original_inv_id for i in doc.invoices)


def test_h5_soft_time_limit_in_pages(client, H, tmp_path, monkeypatch):
    """H5: SoftTimeLimitExceeded inside process_page marks pages failed and finishes completed_with_errors."""
    from celery.exceptions import SoftTimeLimitExceeded

    p = _make_pdf(tmp_path, 105)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    # Reset pages to pending and doc to processing
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        for inv in list(doc.invoices):
            db.delete(inv)
        for pg in doc.pages:
            pg.status = "pending"
        doc.pages_done = 0
        doc.pages_failed = 0
        doc.status = "processing"
        db.commit()

    def fake_process_page(*args, **kwargs):
        raise SoftTimeLimitExceeded("Simulated timeout in page processing")

    monkeypatch.setattr("app.pipeline.process.process_page", fake_process_page)

    with pytest.raises(SoftTimeLimitExceeded):
        pages(doc_id, 1, 1)

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        p1 = db.get(Page, (doc_id, 1))
        assert p1.status == "failed"
        assert "time limit" in (p1.reason or "")
