import random
from pathlib import Path
import pytest
from faker import Faker

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
    from app.db.session import SessionLocal
    from app.db.models import Document
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


def test_maintenance_sweep_endpoint(client, H):
    r = client.post("/api/v1/maintenance/sweep", headers=H)
    assert r.status_code == 200
    data = r.json()
    assert "swept" in data and "count" in data
