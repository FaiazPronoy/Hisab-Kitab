from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
from faker import Faker
import pytest

from app.db.models import Document, Page, ProcessingEvent
from app.db.session import SessionLocal
from app.pipeline import process
from eval import generator

pytestmark = pytest.mark.usefixtures("db_ready")


def make_pdf(tmp_path: Path, seed: int) -> Path:
    rng = random.Random(seed)
    inv = generator.make(Faker("en_GB"), rng, seed, "classic")
    p = tmp_path / f"reproc_{seed}.pdf"
    generator.render(inv, p)
    return p


def test_reprocess_failed_document_with_done_pages(client, H, tmp_path):
    p = make_pdf(tmp_path, 42)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    # Wait/check document completed
    d = client.get(f"/api/v1/documents/{doc_id}", headers=H).json()
    assert d["status"] in ("done", "needs_review")

    # Simulate an extraction failure by updating document status to failed
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        doc.status = "failed"
        doc.error_code = "SIMULATED_LLM_FAILURE"
        db.commit()

    # Reprocess with scope="failed_only": pages are done, so finalize should be triggered cleanly
    rep = client.post(f"/api/v1/documents/{doc_id}/reprocess", json={"scope": "failed_only"}, headers=H)
    assert rep.status_code == 202
    assert rep.json()["status"] == "processing"

    # Verify document finishes
    d_after = client.get(f"/api/v1/documents/{doc_id}", headers=H).json()
    assert d_after["status"] in ("done", "needs_review")
    assert d_after["error_code"] is None


def test_reprocess_active_document_returns_409(client, H, tmp_path):
    """H6: active document (queued, processing, finalizing) must return 409."""
    p = make_pdf(tmp_path, 43)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    for st in ("queued", "processing", "finalizing"):
        with SessionLocal() as db:
            doc = db.get(Document, doc_id)
            doc.status = st
            db.commit()
        rep = client.post(f"/api/v1/documents/{doc_id}/reprocess", json={"scope": "failed_only"}, headers=H)
        assert rep.status_code == 409


def test_reprocess_ingest_failed_or_zero_pages(client, H, tmp_path):
    """H6: document that failed at ingest (page_count=0) routes to ingest rather than 409."""
    p = make_pdf(tmp_path, 44)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        doc.page_count = 0
        doc.pages_done = 0
        doc.pages_failed = 0
        doc.status = "failed"
        doc.error_code = "ENQUEUE_FAILED"
        for inv in list(doc.invoices):
            db.delete(inv)
        db.commit()

    rep = client.post(f"/api/v1/documents/{doc_id}/reprocess", json={"scope": "failed_only"}, headers=H)
    assert rep.status_code == 202
    assert rep.json()["status"] == "queued"

    d = client.get(f"/api/v1/documents/{doc_id}", headers=H).json()
    assert d["status"] in ("done", "needs_review")
    assert d["page_count"] == 1


def test_reprocess_preserves_approved_invoice(client, H, tmp_path):
    """H6: failed_only extraction reprocess must keep approved invoices."""
    p = make_pdf(tmp_path, 45)
    with open(p, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (p.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert len(doc.invoices) > 0
        inv = doc.invoices[0]
        inv.status = "approved"
        approved_id = inv.id
        doc.status = "needs_review"
        db.commit()

    rep = client.post(f"/api/v1/documents/{doc_id}/reprocess", json={"scope": "failed_only"}, headers=H)
    assert rep.status_code == 202

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert any(i.id == approved_id and i.status == "approved" for i in doc.invoices)


def test_maintenance_sweep_clamping_and_validation(client, H):
    """H7: timeout_seconds clamped; 0 rejected with 422."""
    r_bad = client.post("/api/v1/maintenance/sweep?timeout_seconds=0", headers=H)
    assert r_bad.status_code == 422

    r_good = client.post("/api/v1/maintenance/sweep?timeout_seconds=300", headers=H)
    assert r_good.status_code == 200
    assert "swept" in r_good.json()


def test_sweeper_redispatches_pending_pages(tmp_path):
    """H7: sweeper re-dispatches missing pages instead of failing when pages remain pending."""
    from app.storage.service import storage
    p = make_pdf(tmp_path, 46)
    key = storage().new_key(".pdf")
    storage().save_bytes(key, p.read_bytes())
    with SessionLocal() as db:
        doc = Document(filename="stuck.pdf", sha256="deadbeef" * 8, mime="application/pdf",
                       size_bytes=1000, storage_key=key, kind="pdf", status="processing",
                       page_count=2, pages_done=1, pages_failed=0,
                       updated_at=datetime.now(timezone.utc) - timedelta(seconds=1200))
        db.add(doc)
        db.flush()
        db.add(Page(document_id=doc.id, page_no=1, status="done"))
        db.add(Page(document_id=doc.id, page_no=2, status="pending"))
        db.commit()
        doc_id = doc.id

    with SessionLocal() as db:
        swept = process.sweep_stuck_documents(db, timeout_seconds=600)

    assert any(f"redispatched:{doc_id}" in s for s in swept)


def test_sweeper_recent_event_keeps_document_alive(tmp_path):
    """H7: a recent processing event keeps a document from being swept."""
    from app.storage.service import storage
    p = make_pdf(tmp_path, 47)
    key = storage().new_key(".pdf")
    storage().save_bytes(key, p.read_bytes())
    with SessionLocal() as db:
        doc = Document(filename="alive.pdf", sha256="feedface" * 8, mime="application/pdf",
                       size_bytes=1000, storage_key=key, kind="pdf", status="processing",
                       page_count=2, pages_done=0, pages_failed=0,
                       updated_at=datetime.now(timezone.utc) - timedelta(seconds=1200))
        db.add(doc)
        db.flush()
        # Add a recent event (50s ago, within 600s timeout)
        db.add(ProcessingEvent(document_id=doc.id, stage="ocr", status="done",
                               created_at=datetime.now(timezone.utc) - timedelta(seconds=50)))
        db.commit()
        doc_id = doc.id

    with SessionLocal() as db:
        swept = process.sweep_stuck_documents(db, timeout_seconds=600)

    assert not any(str(doc_id) in s for s in swept)
