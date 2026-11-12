import random
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl
import pytest
from faker import Faker

from eval import generator

pytestmark = pytest.mark.usefixtures("db_ready")


def pdf(tmp_path: Path, seed: int, **over) -> tuple[Path, dict]:
    rng = random.Random(seed)
    inv = generator.make(Faker("en_GB"), rng, seed, over.pop("layout", "classic"))
    inv.update(over)
    p = tmp_path / f"f{seed}.pdf"
    generator.render(inv, p)
    return p, inv


def up(client, H, path, role=None):
    with open(path, "rb") as f:
        data = {"role": role} if role else None
        return client.post("/api/v1/documents", files=[("files", (path.name, f))], data=data, headers=H).json()[0]


def invoice(client, H, doc_id):
    d = client.get(f"/api/v1/documents/{doc_id}", headers=H).json()
    return client.get(f"/api/v1/invoices/{d['invoices'][0]['id']}", headers=H).json()


@pytest.fixture
def login_on():
    from app.core.config import get_settings
    s = get_settings()
    s.require_login = True
    yield
    s.require_login = False


@pytest.fixture
def users(db_ready):
    from scripts.create_user import ensure_user
    ensure_user("clerk1", "Clara Clerk", "clerk", "pw-clerk")
    ensure_user("boss1", "Bilal Boss", "approver", "pw-boss")
    ensure_user("boss2", "Rumana Boss", "approver", "pw-boss2")


def token(client, H, user, pw):
    r = client.post("/api/v1/auth/login", headers=H, json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {**H, "Authorization": f"Bearer {r.json()['token']}"}


def test_login_rejects_bad_password_and_changes_need_a_session(client, H, users, login_on, tmp_path):
    assert client.post("/api/v1/auth/login", headers=H, json={"username": "clerk1", "password": "nope"}).status_code == 401
    p, _ = pdf(tmp_path, 41)
    inv = invoice(client, H, up(client, H, p)["document_id"])
    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=H, json={})
    assert r.status_code == 401
    bad = {**H, "Authorization": "Bearer forged.token"}
    assert client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=bad, json={}).status_code == 401


def test_large_invoice_needs_an_approver_who_did_not_change_it(client, H, users, login_on, tmp_path):
    from app.core.config import get_settings
    get_settings().approval_limit = 10
    try:
        p, truth = pdf(tmp_path, 42)
        inv = invoice(client, H, up(client, H, p)["document_id"])
        clerk = token(client, H, "clerk1", "pw-clerk")
        assert client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=clerk, json={}).status_code == 403
        boss = token(client, H, "boss1", "pw-boss")
        r = client.patch(f"/api/v1/invoices/{inv['id']}", headers=boss, json={
            "version": inv["version"], "corrections": [{"field": "total", "value": truth["total"]}]})
        assert r.status_code == 200
        assert client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=boss, json={}).status_code == 403
        other = token(client, H, "boss2", "pw-boss2")
        r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=other, json={})
        assert r.status_code == 200 and r.json()["approved_by"] == "Rumana Boss"
        hist = client.get(f"/api/v1/invoices/{inv['id']}", headers=H).json()["corrections"]
        assert {"Bilal Boss", "Rumana Boss"} <= {c["corrected_by"] for c in hist}
    finally:
        get_settings().approval_limit = 10000


def test_supplier_memory_learns_a_label_from_one_correction(client, H, tmp_path):
    name = "Learning Label Traders Ltd"
    p1, t1 = pdf(tmp_path, 43, supplier_name=name, number_label="Our ref", invoice_number="ZX-55001")
    inv = invoice(client, H, up(client, H, p1)["document_id"])
    assert inv["invoice_number"] != "ZX-55001"
    r = client.patch(f"/api/v1/invoices/{inv['id']}", headers=H, json={
        "version": inv["version"], "corrections": [{"field": "invoice_number", "value": "ZX-55001"}]}).json()
    assert any("Our ref" in x for x in r["learned"])
    p2, _ = pdf(tmp_path, 44, supplier_name=name, number_label="Our ref", invoice_number="ZX-55002")
    inv2 = invoice(client, H, up(client, H, p2)["document_id"])
    assert inv2["invoice_number"] == "ZX-55002"
    f = inv2["fields"]["invoice_number"]
    assert f["source"] == "memory" and f["verified"] and f["bbox"]


def test_corrected_supplier_name_files_later_invoices_under_it(client, H, tmp_path):
    p1, _ = pdf(tmp_path, 45, supplier_name="Nortn Supplies Ltd")
    inv = invoice(client, H, up(client, H, p1)["document_id"])
    client.patch(f"/api/v1/invoices/{inv['id']}", headers=H, json={
        "version": inv["version"], "corrections": [{"field": "supplier_name", "value": "Norton Supplies Ltd"}]})
    p2, _ = pdf(tmp_path, 46, supplier_name="Nortn Supplies Ltd")
    inv2 = invoice(client, H, up(client, H, p2)["document_id"])
    from app.db.models import Invoice
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        assert db.get(Invoice, inv2["id"]).supplier_norm == db.get(Invoice, inv["id"]).supplier_norm


def test_changed_bank_details_are_stopped(client, H, tmp_path):
    rng = random.Random(5)
    name, iban = "Steady Bank Supplies Ltd", generator.iban(rng)
    for k in range(3):
        p, _ = pdf(tmp_path, 50 + k, supplier_name=name, iban=iban)
        inv = invoice(client, H, up(client, H, p)["document_id"])
        assert inv["bank_account"] == iban.replace(" ", "")
        if inv["status"] != "approved":
            client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=H, json={})
    p, _ = pdf(tmp_path, 53, supplier_name=name, iban=generator.iban(rng))
    inv = invoice(client, H, up(client, H, p)["document_id"])
    f = next(x for x in inv["findings_list"] if x["rule_code"] == "BANK_CHANGED")
    assert f["severity"] == "error" and inv["status"] == "needs_review"
    assert f["expected"].startswith("...") and iban.replace(" ", "")[-4:] in f["expected"]


def test_payment_file_is_valid_pain001_and_pays_once(client, H, tmp_path):
    rng = random.Random(9)
    ids = []
    for k in range(2):
        p, _ = pdf(tmp_path, 60 + k, iban=generator.iban(rng))
        inv = invoice(client, H, up(client, H, p)["document_id"])
        client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=H, json={})
        ids.append(inv["id"])
    ready = {x["id"] for x in client.get("/api/v1/payments/ready", headers=H).json()}
    assert set(ids) <= ready
    b = client.post("/api/v1/payments/batches", headers=H, json={"invoice_ids": ids, "format": "pain001"})
    assert b.status_code == 201, b.text
    xml = client.get(f"/api/v1/payments/batches/{b.json()['id']}/file", headers=H).text
    ns = {"p": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"}
    root = ET.fromstring(xml)
    txs = root.findall(".//p:CdtTrfTxInf", ns)
    assert len(txs) == 2 and root.find(".//p:GrpHdr/p:NbOfTxs", ns).text == "2"
    total = sum(float(t.find("p:Amt/p:InstdAmt", ns).text) for t in txs)
    assert abs(total - float(root.find(".//p:GrpHdr/p:CtrlSum", ns).text)) < 0.005
    again = client.post("/api/v1/payments/batches", headers=H, json={"invoice_ids": ids, "format": "csv"})
    assert again.status_code == 409
    inv = client.get(f"/api/v1/invoices/{ids[0]}", headers=H).json()
    r = client.patch(f"/api/v1/invoices/{ids[0]}", headers=H, json={
        "version": inv["version"], "corrections": [{"field": "total", "value": "1.00"}]})
    assert r.status_code == 409


def test_payment_file_needs_bank_details(client, H, tmp_path):
    p, _ = pdf(tmp_path, 70)
    inv = invoice(client, H, up(client, H, p)["document_id"])
    client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=H, json={})
    r = client.post("/api/v1/payments/batches", headers=H, json={"invoice_ids": [inv["id"]], "format": "pain001"})
    assert r.status_code == 422 and "bank account" in r.json()["detail"]


def sheet(tmp_path, name, title, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    ws.append(["Invoice No", "Invoice Date", "Supplier", "Total", "Currency"])
    for r in rows:
        ws.append(r)
    p = tmp_path / name
    wb.save(p)
    return p


def test_ledger_rows_are_not_reviewed_or_called_duplicates(client, H, tmp_path):
    rows = [["RL-1", "2026-01-02", "Role Test Ltd", 100.0, "GBP"], ["RL-2", "2026-01-03", "Role Test Ltd", 200.0, "GBP"]]
    reg = up(client, H, sheet(tmp_path, "register.xlsx", "Invoices", rows))
    led = up(client, H, sheet(tmp_path, "paid.xlsx", "Payments", rows))
    d = client.get(f"/api/v1/documents/{led['document_id']}", headers=H).json()
    assert d["role"] == "ledger" and {i["status"] for i in d["invoices"]} == {"ledger"}
    r = client.get(f"/api/v1/documents/{reg['document_id']}", headers=H).json()
    assert r["role"] == "invoices"
    for i in r["invoices"]:
        codes = {x["rule_code"] for x in client.get(f"/api/v1/invoices/{i['id']}", headers=H).json()["findings_list"]}
        assert not codes & {"DUP_INVOICE", "DUP_CONFLICT"}
    # the uploader can say what a sheet is, and change it later
    forced = up(client, H, sheet(tmp_path, "list.xlsx", "Sheet1", [["RL-9", "2026-01-04", "Role Test Ltd", 9.0, "GBP"]]), "ledger")
    assert client.get(f"/api/v1/documents/{forced['document_id']}", headers=H).json()["role"] == "ledger"
    back = client.patch(f"/api/v1/documents/{forced['document_id']}", headers=H, json={"role": "invoices"}).json()
    assert back["role"] == "invoices" and back["invoices"][0]["status"] != "ledger"


def test_compare_shows_differences_between_two_invoices(client, H, tmp_path):
    p, truth = pdf(tmp_path, 80)
    a = invoice(client, H, up(client, H, p)["document_id"])
    p2, _ = pdf(tmp_path, 80, printed_total="99999.99")
    p2 = p2.rename(tmp_path / "copy80.pdf")
    b = invoice(client, H, up(client, H, p2)["document_id"])
    r = client.get(f"/api/v1/compare?left={a['id']}&right={b['id']}", headers=H).json()
    assert r["left"]["id"] == a["id"] and any(i["field"] == "total" for i in r["items"])


def test_new_bank_details_need_an_approver(client, H, users, login_on, tmp_path):
    rng = random.Random(11)
    name, iban = "Careful Payee Ltd", generator.iban(rng)
    for k in range(2):
        p, _ = pdf(tmp_path, 90 + k, supplier_name=name, iban=iban)
        inv = invoice(client, H, up(client, H, p)["document_id"])
        boss = token(client, H, "boss1", "pw-boss")
        client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=boss, json={})
    p, _ = pdf(tmp_path, 92, supplier_name=name, iban=generator.iban(rng))
    inv = invoice(client, H, up(client, H, p)["document_id"])
    assert "BANK_CHANGED" in {x["rule_code"] for x in inv["findings_list"]}
    clerk = token(client, H, "clerk1", "pw-clerk")
    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=clerk, json={})
    assert r.status_code == 403 and "approver" in r.json()["detail"]


def test_payment_file_has_one_block_per_currency():
    import uuid
    from datetime import date
    from decimal import Decimal
    from types import SimpleNamespace

    from app.pipeline import payments as pay
    rng = random.Random(4)
    invs = [SimpleNamespace(id=uuid.uuid4(), invoice_number=f"N{k}", supplier_name="Sup\x07plier", total=Decimal(t),
                            currency=c, bank_account=generator.iban(rng).replace(" ", ""), due_date=None)
            for k, (t, c) in enumerate([("10.00", "EUR"), ("5.50", "GBP"), ("2.25", "EUR")])]
    root = ET.fromstring(pay.pain001(invs, uuid.uuid4(), date(2026, 12, 1)))
    ns = {"p": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"}
    blocks = {b.find("p:CdtTrfTxInf/p:Amt/p:InstdAmt", ns).get("Ccy"): b.find("p:CtrlSum", ns).text
              for b in root.findall(".//p:PmtInf", ns)}
    assert blocks == {"EUR": "12.25", "GBP": "5.50"}
    assert root.find(".//p:Cdtr/p:Nm", ns).text == "Supplier"


def test_iban_check_rejects_punctuation_and_bad_digits():
    from app.pipeline.extract.bank import iban_ok
    assert iban_ok("GB33 BUKB 2020 1555 5555 55")
    assert not iban_ok("GB33-BUKB-2020-1555-5555-55")
    assert not iban_ok("GB34BUKB20201555555555")
    assert not iban_ok("123456789012345678")


def test_invoices_are_matched_to_purchase_orders(client, H, tmp_path):
    ccy = "GBP"
    p, fits = pdf(tmp_path, 100, supplier_name="Order Match Ltd", po_number="PO-7001", currency=ccy)
    early = invoice(client, H, up(client, H, p)["document_id"])
    p0, _ = pdf(tmp_path, 104, supplier_name="Order Match Ltd", po_number="PO-7404", currency=ccy)
    stray = invoice(client, H, up(client, H, p0)["document_id"])
    assert not {x["rule_code"] for x in early["findings_list"]} & {"PO_UNKNOWN", "PO_OVER"}
    rows = [["PO-7001", "Order Match Ltd", float(fits["total"]), ccy],
            ["PO-7002", "Order Match Ltd", 10.0, ccy]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase orders"
    ws.append(["PO Number", "Supplier", "Amount", "Currency"])
    for r in rows:
        ws.append(r)
    path = tmp_path / "pos.xlsx"
    wb.save(path)
    d = client.get(f"/api/v1/documents/{up(client, H, path)['document_id']}", headers=H).json()
    assert d["role"] == "purchase_orders" and {i["status"] for i in d["invoices"]} == {"po"}
    # an invoice read before the POs arrived is checked again once they do
    again = client.get(f"/api/v1/invoices/{stray['id']}", headers=H).json()
    assert "PO_UNKNOWN" in {x["rule_code"] for x in again["findings_list"]}

    p2, _ = pdf(tmp_path, 101, supplier_name="Order Match Ltd", po_number="PO-7002", currency=ccy)
    over = invoice(client, H, up(client, H, p2)["document_id"])
    f = next(x for x in over["findings_list"] if x["rule_code"] == "PO_OVER")
    assert f["severity"] == "error" and over["status"] == "needs_review"
    p3, _ = pdf(tmp_path, 102, supplier_name="Order Match Ltd", po_number="PO-9999")
    unknown = invoice(client, H, up(client, H, p3)["document_id"])
    assert "PO_UNKNOWN" in {x["rule_code"] for x in unknown["findings_list"]}
    # a second invoice on the first PO now bills it twice
    p4, _ = pdf(tmp_path, 103, supplier_name="Order Match Ltd", po_number="PO-7001", currency=ccy)
    twice = invoice(client, H, up(client, H, p4)["document_id"])
    assert "PO_OVER" in {x["rule_code"] for x in twice["findings_list"]}


def test_a_later_duplicate_puts_the_first_document_back_in_review(client, H, tmp_path):
    p, _ = pdf(tmp_path, 110, supplier_name="Twice Sent Ltd")
    first = up(client, H, p)["document_id"]
    before = client.get(f"/api/v1/documents/{first}", headers=H).json()
    copy = p.read_bytes() + b"\n% resent"
    p2 = tmp_path / "resent.pdf"
    p2.write_bytes(copy)
    up(client, H, p2)
    after = client.get(f"/api/v1/documents/{first}", headers=H).json()
    assert before["invoices"][0]["status"] != "needs_review" or before["status"] == "needs_review"
    assert after["invoices"][0]["status"] == "needs_review" and after["status"] == "needs_review"
