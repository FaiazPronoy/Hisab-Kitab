import random
from pathlib import Path

import openpyxl
import pytest
from faker import Faker

from eval import generator

pytestmark = pytest.mark.usefixtures("db_ready")


def make_pdf(tmp_path: Path, seed: int, **over) -> tuple[Path, dict]:
    rng = random.Random(seed)
    inv = generator.make(Faker("en_GB"), rng, seed, over.pop("layout", "classic"))
    inv.update(over)
    p = tmp_path / f"inv{seed}.pdf"
    generator.render(inv, p)
    return p, inv


def up(client, H, path: Path, name=None):
    with open(path, "rb") as f:
        return client.post("/api/v1/documents", files=[("files", (name or path.name, f))], headers=H)


def first_invoice(client, H, doc_id):
    d = client.get(f"/api/v1/documents/{doc_id}", headers=H).json()
    return d, client.get(f"/api/v1/invoices/{d['invoices'][0]['id']}", headers=H).json()


def test_auth_required(client):
    assert client.get("/api/v1/documents").status_code == 401
    assert client.get("/api/v1/documents", headers={"X-API-Key": "wrong"}).status_code == 401


def test_upload_extracts_grounded_fields_and_is_idempotent(client, H, tmp_path):
    p, truth = make_pdf(tmp_path, 1, currency="GBP")
    r = up(client, H, p)
    assert r.status_code == 202
    doc_id = r.json()[0]["document_id"]
    doc, inv = first_invoice(client, H, doc_id)
    assert doc["status"] in ("done", "needs_review") and doc["pages"][0]["source"] == "text_layer"
    f = inv["fields"]
    assert f["invoice_number"]["value"] == truth["invoice_number"]
    assert f["total"]["value"] == truth["total"] and f["total"]["verified"] and f["total"]["bbox"]
    assert f["currency"]["value"] == "GBP"
    again = up(client, H, p, "copy.pdf").json()[0]
    assert again["duplicate_of"] == doc_id
    hist = client.get(f"/api/v1/documents/{doc_id}/history", headers=H).json()
    assert {"ingest", "finalize"} <= {e["stage"] for e in hist}


def test_wrong_total_goes_to_review_and_correction_revalidates(client, H, tmp_path):
    p, truth = make_pdf(tmp_path, 2, printed_total="9999.99")
    doc_id = up(client, H, p).json()[0]["document_id"]
    _, inv = first_invoice(client, H, doc_id)
    assert inv["status"] == "needs_review"
    assert "TOTAL_MATH" in {x["rule_code"] for x in inv["findings_list"]}
    r = client.patch(f"/api/v1/invoices/{inv['id']}", headers=H, json={
        "version": inv["version"], "corrections": [{"field": "total", "value": truth["total"], "reason": "misprint"}]})
    assert r.status_code == 200
    assert "TOTAL_MATH" not in {x["rule_code"] for x in r.json()["findings"]}
    after = client.get(f"/api/v1/invoices/{inv['id']}", headers=H).json()
    assert after["corrections"][0]["old_value"] == "9999.9900" and after["fields"]["total"]["source"] == "user"
    stale = client.patch(f"/api/v1/invoices/{inv['id']}", headers=H, json={"version": inv["version"], "corrections": []})
    assert stale.status_code == 409


def test_corrupt_and_spoofed_files_fail_cleanly(client, H, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\n" + b"x" * 100)
    doc = up(client, H, bad).json()[0]
    d = client.get(f"/api/v1/documents/{doc['document_id']}", headers=H).json()
    assert d["status"] == "failed" and d["error_code"] == "CORRUPT_FILE"
    fake = tmp_path / "photo.png"
    fake.write_bytes(b"%PDF-1.4 not a png")
    r = up(client, H, fake)
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "TYPE_MISMATCH"


def test_oversize_upload_rejected(client, H, tmp_path):
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.7\n" + b"0" * (3 * 1024 * 1024))
    assert up(client, H, big).status_code == 413


def test_failed_page_reprocess_only_that_page(client, H, tmp_path, monkeypatch):
    from app.pipeline import process
    rng = random.Random(3)
    inv = generator.make(Faker("en_GB"), rng, 3, "multipage")
    inv["line_items"] = inv["line_items"] * 3
    p = tmp_path / "long.pdf"
    generator.render(inv, p)
    real = process.process_page
    calls = []

    def flaky(db, doc, page, pdf=None, frames=None):
        calls.append(page.page_no)
        if page.page_no == 2:
            raise RuntimeError("ocr crashed")
        return real(db, doc, page, pdf, frames)

    monkeypatch.setattr(process, "process_page", flaky)
    monkeypatch.setattr(process.time, "sleep", lambda s: None)
    doc_id = up(client, H, p).json()[0]["document_id"]
    d = client.get(f"/api/v1/documents/{doc_id}", headers=H).json()
    assert d["status"] == "completed_with_errors" and d["pages_failed"] == 1
    monkeypatch.setattr(process, "process_page", real)
    calls.clear()
    r = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=H, json={"scope": "failed_only"})
    assert r.json()["pages"] == [2]
    d = client.get(f"/api/v1/documents/{doc_id}", headers=H).json()
    assert d["pages_failed"] == 0 and d["status"] in ("done", "needs_review")


def test_register_sheet_search_and_reconciliation(client, H, tmp_path):
    p, truth = make_pdf(tmp_path, 4, supplier_name="Northwind Traders Ltd", currency="USD")
    up(client, H, p)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Invoice No", "Supplier", "Invoice Date", "Total", "Currency"])
    ws.append([truth["invoice_number"], "Northwind Traders Ltd", truth["invoice_date"], float(truth["total"]) + 10, "USD"])
    ws.append(["GHOST-1", "Phantom Ltd", "2026-01-01", 5.0, "USD"])
    x = tmp_path / "ledger.xlsx"
    wb.save(x)
    led = up(client, H, x).json()[0]["document_id"]
    sheet_invs = client.get(f"/api/v1/invoices?document_id={led}", headers=H).json()
    assert len(sheet_invs) == 2
    run = client.post("/api/v1/reconciliations", headers=H, json={"kind": "ledger", "ledger_document_id": led,
                                                                   "invoice_document_ids": [up(client, H, p).json()[0]["document_id"]]}).json()
    cats = {i["category"] for i in run["items"]}
    assert {"amount_mismatch", "missing_in_invoices"} <= cats
    for mode in ("keyword", "hybrid"):
        res = client.get("/api/v1/search", headers=H, params={"q": truth["invoice_number"], "mode": mode}).json()
        assert any(r["invoice_number"] == truth["invoice_number"] for r in res["results"]), mode
    res = client.get("/api/v1/search", headers=H, params={"q": "", "supplier": "northwind"}).json()
    assert res["count"] >= 1


def test_malformed_llm_answer_gives_nulls_not_crash(client, H, tmp_path, monkeypatch):
    from app.pipeline.extract import providers
    monkeypatch.setattr(providers.MockProvider, "generate", lambda *a, **k: ("{not json", 10, 2))
    p, _ = make_pdf(tmp_path, 5)
    doc_id = up(client, H, p).json()[0]["document_id"]
    _, inv = first_invoice(client, H, doc_id)
    assert inv["status"] == "needs_review" and "EXTRACTION_FAILED" in {x["rule_code"] for x in inv["findings_list"]}


def test_csv_export_neutralizes_formulas(client, H, tmp_path):
    p, _ = make_pdf(tmp_path, 6, supplier_name="=HYPERLINK(evil)")
    up(client, H, p)
    body = client.get("/api/v1/invoices/export", headers=H).text
    assert "'=HYPERLINK" in body or "=HYPERLINK" not in body


def test_stale_approve_is_refused_and_last_approval_closes_document(client, H, tmp_path):
    p, _ = make_pdf(tmp_path, 31, printed_total="1.00")
    doc_id = up(client, H, p).json()[0]["document_id"]
    _, inv = first_invoice(client, H, doc_id)
    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=H, json={"version": inv["version"] + 5})
    assert r.status_code == 409
    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=H, json={"version": inv["version"]})
    assert r.status_code == 200
    assert client.get(f"/api/v1/documents/{doc_id}", headers=H).json()["status"] == "done"


def test_bad_ids_and_limits_are_client_errors(client, H):
    assert client.get("/api/v1/invoices/not-a-uuid", headers=H).status_code == 422
    assert client.get("/api/v1/documents/not-a-uuid", headers=H).status_code == 422
    assert client.get("/api/v1/documents?limit=0", headers=H).status_code == 200
    assert client.get("/api/v1/documents?cursor=abc", headers=H).status_code == 422
