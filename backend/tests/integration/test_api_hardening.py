from datetime import date
from decimal import Decimal
import random
from unittest.mock import patch
from faker import Faker
import pytest
from redis import Redis

from app.core.config import get_settings
from app.db.models import Document, Invoice, LineItem
from app.db.session import SessionLocal
from app.pipeline.extract.providers import LlmError, _take_token
from eval import generator

pytestmark = pytest.mark.usefixtures("db_ready")


def _make_sample_doc_and_invoice(db, seed=101):
    doc = Document(
        sha256=f"sha256_mock_sample_{seed}",
        filename=f"doc_{seed}.pdf",
        mime="application/pdf",
        size_bytes=1024,
        storage_key=f"sample_{seed}.pdf",
        kind="pdf",
        status="done",
        page_count=1,
    )
    db.add(doc)
    db.flush()

    inv = Invoice(
        document_id=doc.id,
        status="needs_review",
        version=1,
        invoice_number=f"INV-{seed}",
        invoice_date=date(2025, 1, 1),
        supplier_name="Initial Supplier Co",
        customer_name="Customer Ltd",
        currency="USD",
        subtotal=Decimal("100.00"),
        tax=Decimal("10.00"),
        total=Decimal("110.00"),
    )
    db.add(inv)
    db.flush()

    li = LineItem(
        invoice_id=inv.id,
        idx=0,
        description="Widget",
        quantity=Decimal("2"),
        unit_price=Decimal("50.00"),
        amount=Decimal("100.00"),
        confidence=0.95,
    )
    db.add(li)
    db.commit()
    db.refresh(inv)
    return doc, inv


def test_h8_auth_header_and_query_rules(client, H):
    """H8: strict ASCII X-API-Key header required, ?api_key= rejected except on browser routes."""
    from fastapi import HTTPException
    from app.api.deps import require_key

    # 1. No auth -> 401
    r = client.get("/api/v1/invoices")
    assert r.status_code == 401

    # 2. Non-ASCII header -> 401 (not 500)
    with pytest.raises(HTTPException) as exc:
        require_key(x_api_key="bad\u2603key")
    assert exc.value.status_code == 401

    r = client.get("/api/v1/invoices", headers={"X-API-Key": b"bad\x80key"})
    assert r.status_code == 401

    # 3. Query param on standard API endpoint -> 401
    r = client.get(f"/api/v1/invoices?api_key={get_settings().api_key}")
    assert r.status_code == 401

    # 4. Correct header -> 200
    r = client.get("/api/v1/invoices", headers=H)
    assert r.status_code == 200

    # 5. Query param allowed on browser routes (events and page image)
    with SessionLocal() as db:
        doc, _ = _make_sample_doc_and_invoice(db, seed=201)
        doc_id = str(doc.id)

    # Browser image preview with query param succeeds auth (not 401)
    r_img = client.get(f"/api/v1/documents/{doc_id}/pages/1/image?api_key={get_settings().api_key}")
    assert r_img.status_code != 401


def test_h9_patch_invoice_validation(client, H):
    """H9: validate PATCH values: reject NaN, Inf, exponent, EU format, length cap, stale version."""
    with SessionLocal() as db:
        _, inv = _make_sample_doc_and_invoice(db, seed=301)
        inv_id = str(inv.id)

    # 1. NaN -> 422
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "total", "value": "NaN"}], "version": 1}, headers=H)
    assert r.status_code == 422

    # 2. Infinity -> 422
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "total", "value": "Infinity"}], "version": 1}, headers=H)
    assert r.status_code == 422

    # 3. Exponent -> 422
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "total", "value": "1e5"}], "version": 1}, headers=H)
    assert r.status_code == 422

    # 4. EU number format (comma decimal) -> 422
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "total", "value": "1.234,56"}], "version": 1}, headers=H)
    assert r.status_code == 422
    assert "European number format" in r.json()["detail"]

    # 5. Large number >= 1e14 -> 422
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "total", "value": "100000000000000"}], "version": 1}, headers=H)
    assert r.status_code == 422

    # 6. Currency length cap -> 422
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "currency", "value": "US"}], "version": 1}, headers=H)
    assert r.status_code == 422

    # 7. Field length cap -> 422
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "invoice_number", "value": "X" * 150}], "version": 1}, headers=H)
    assert r.status_code == 422

    # 8. Valid PATCH -> succeeds and quantizes
    r = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "total", "value": "150.55"}], "version": 1}, headers=H)
    assert r.status_code == 200
    assert r.json()["version"] > 1

    # 9. Stale version -> 409
    r_stale = client.patch(f"/api/v1/invoices/{inv_id}", json={"corrections": [{"field": "total", "value": "160.00"}], "version": 1}, headers=H)
    assert r_stale.status_code == 409


def test_h10_supplier_correction_indexing(client, H):
    """H10: Correcting supplier re-indexes invoice so keyword search finds it."""
    with SessionLocal() as db:
        _, inv = _make_sample_doc_and_invoice(db, seed=401)
        inv_id = str(inv.id)

    unique_supplier = "AcmeRocketScienceLLC"
    r = client.patch(
        f"/api/v1/invoices/{inv_id}",
        json={"corrections": [{"field": "supplier_name", "value": unique_supplier}], "version": 1},
        headers=H,
    )
    assert r.status_code == 200

    # Keyword search for the newly indexed supplier
    sr = client.get(f"/api/v1/search?q={unique_supplier}&mode=keyword", headers=H)
    assert sr.status_code == 200
    results = sr.json()["results"]
    assert any(it["id"] == inv_id for it in results)


def test_m1_idempotency_pending_returns_409(client, H):
    """M1: concurrent request holding 'pending' idempotency key returns 409."""
    rc = Redis.from_url(get_settings().redis_url)
    api_key = get_settings().api_key
    idemp_key = "test-concurrent-idemp-key"
    redis_key = f"docintel:idemp:{api_key}:{idemp_key}"

    rc.set(redis_key, "pending", ex=60)
    try:
        r = client.post(
            "/api/v1/documents",
            headers={"X-API-Key": api_key, "Idempotency-Key": idemp_key},
            files=[("files", ("dummy.pdf", b"%PDF-1.4 dummy", "application/pdf"))],
        )
        assert r.status_code == 409
        assert "already in progress" in r.json()["detail"]
    finally:
        rc.delete(redis_key)
        rc.close()


def test_m1_reupload_enqueue_failed_reenqueues(client, H, tmp_path):
    """M1: A re-upload whose existing document is failed with ENQUEUE_FAILED re-enqueues."""
    rng = random.Random(501)
    inv_data = generator.make(Faker("en_GB"), rng, 501, "classic")
    pdf_path = tmp_path / "failed_enqueue.pdf"
    generator.render(inv_data, pdf_path)

    with open(pdf_path, "rb") as f:
        r = client.post("/api/v1/documents", files=[("files", (pdf_path.name, f))], headers=H)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]

    # Manually mark the document as ENQUEUE_FAILED
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        doc.status = "failed"
        doc.error_code = "ENQUEUE_FAILED"
        doc.error_message = "RabbitMQ connection refused"
        db.commit()

    # Re-upload the exact same file
    with open(pdf_path, "rb") as f:
        r2 = client.post("/api/v1/documents", files=[("files", (pdf_path.name, f))], headers=H)
    assert r2.status_code == 202
    res2 = r2.json()[0]
    assert res2["document_id"] == doc_id
    assert res2["status"] in ("queued", "done", "needs_review")

    with SessionLocal() as db:
        doc_after = db.get(Document, doc_id)
        assert doc_after.error_code != "ENQUEUE_FAILED"


def test_m4_csv_export_negative_total_and_formula_guard(client, H):
    """M4: CSV formula guard applies only to text columns; negative total remains numeric."""
    with SessionLocal() as db:
        doc, inv = _make_sample_doc_and_invoice(db, seed=601)
        inv.total = Decimal("-50.00")
        inv.supplier_name = "=SUM(1,2)"
        db.commit()
        inv_id = str(inv.id)

    r = client.get("/api/v1/invoices/export?format=csv", headers=H)
    assert r.status_code == 200
    csv_text = r.text
    rows = csv_text.strip().splitlines()

    target_row = next((row for row in rows if inv_id in row), None)
    assert target_row is not None
    # Supplier name with formula starts with single quote
    assert "'=SUM(1,2)" in target_row
    # Negative total stays as plain -50.00, not '-50.00
    assert "-50.00" in target_row
    assert "'-50.00" not in target_row


def test_m5_line_items_precision_preserved(client, H):
    """M5: unit_price and quantity preserve precision up to 4 decimals without rounding to 2 places."""
    with SessionLocal() as db:
        doc, inv = _make_sample_doc_and_invoice(db, seed=701)
        li = inv.line_items[0]
        li.quantity = Decimal("1.2500")
        li.unit_price = Decimal("0.0375")
        db.commit()
        inv_id = str(inv.id)

    r = client.get(f"/api/v1/invoices/{inv_id}", headers=H)
    assert r.status_code == 200
    data = r.json()
    item = data["line_items"][0]
    assert item["unit_price"] == "0.0375"
    assert item["quantity"] == "1.25"


def test_h15_sliding_window_limiter_timeout():
    """H15: sliding-window limiter raises transient LlmError when rate limit is full and times out."""
    with patch("app.pipeline.extract.providers._get_redis") as mock_get_redis:
        mock_rc = mock_get_redis.return_value
        # Eval returns 0 (not allowed) every time
        mock_rc.eval.return_value = 0
        with patch("time.sleep", return_value=None):
            with pytest.raises(LlmError) as exc_info:
                _take_token()
            assert exc_info.value.transient is True
            assert "sliding window full" in str(exc_info.value)
