"""Uploads a small demo batch through the running API: a clean PDF, a
rotated scan, a corrupted PDF, a multi-invoice PDF, a wrong total, a
ledger workbook and a CSV register. Then it signs in as the demo approver,
approves two clean invoices so the payments screen has work, and sends one
more invoice from a known supplier with new bank details."""
import os
import random
import time
from pathlib import Path

import httpx
import openpyxl
from faker import Faker

from eval import degrade, generator
from scripts.create_user import ensure_user

OUT = Path(os.environ.get("DEMO_DIR", "/data/storage/demo"))


def demo_ledger(invs):
    # small payments sheet with a bit of everything: two clean rows, one
    # number shared by the pdf and its scan, two wrong amounts and a ghost
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payments"
    ws.append(["Invoice No", "Invoice Date", "Supplier", "Total", "Currency"])
    for k, inv in enumerate(invs):
        total = float(inv["total"])
        if k == 3:
            total += 37.5
        ws.append([inv["invoice_number"], inv["invoice_date"], inv["supplier_name"], total, inv["currency"]])
    ws.append(["GHOST-9000", "2026-05-01", "Phantom Supplies Ltd", 199.0, "USD"])
    p = OUT / "ledger.xlsx"
    wb.save(p)
    return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(3)
    fake = Faker("en_GB")
    Faker.seed(3)  # the same demo every time, so running it twice adds nothing new
    invs = [generator.make(fake, rng, i, lay) for i, lay in enumerate(
        ["classic", "eu_vat", "wholesale", "receipt", "classic", "multipage", "credit_note", "classic"])]
    for inv in invs[:5]:
        inv["iban"] = generator.iban(rng)
    files = []
    for inv in invs[:4]:
        p = OUT / f"{inv['id']}.pdf"
        generator.render(inv, p)
        files.append(p)
    invs[4]["printed_total"] = str(generator.money(generator.Decimal(invs[4]["total"]) + 100))
    p = OUT / "wrong_total.pdf"
    generator.render(invs[4], p)
    files.append(p)
    files.append(degrade.write(files[0], OUT, "medium", "tiff", rng))
    m = OUT / "three_invoices.pdf"
    generator.render_many(invs[5:8], m)
    files.append(m)
    bad = OUT / "corrupted.pdf"
    bad.write_bytes(files[1].read_bytes()[:900])
    files.append(bad)
    files.append(demo_ledger(invs[:5]))
    csv = OUT / "register.csv"
    csv.write_text("Invoice No;Date;Supplier;Total;Currency\n" + "\n".join(
        f"{i['invoice_number']};{i['invoice_date']};{i['supplier_name']};{i['total'].replace('.', ',')};{i['currency']}" for i in invs[5:8]),
        encoding="cp1252")
    files.append(csv)

    ensure_user("nadia", "Nadia Rahman", "clerk", "demo-clerk")
    ensure_user("farhan", "Farhan Hossain", "approver", "demo-approver")

    api = os.environ.get("API_URL", "http://api:8000/api/v1")
    h = {"X-API-Key": os.environ.get("API_KEY", "local-dev-key")}
    ids = send(api, h, files)
    wait(api, h, ids)

    tok = httpx.post(f"{api}/auth/login", headers=h, json={"username": "farhan", "password": "demo-approver"}).json()["token"]
    boss = {**h, "Authorization": f"Bearer {tok}"}
    for name in ("inv0001.pdf", "inv0002.pdf"):
        doc = next(d for d in httpx.get(f"{api}/documents?limit=50", headers=h).json()["items"] if d["filename"] == name)
        inv = httpx.get(f"{api}/documents/{doc['id']}", headers=h).json()["invoices"][0]
        if inv["status"] != "needs_review":
            httpx.post(f"{api}/invoices/{inv['id']}/approve", headers=boss, json={})

    # same supplier as inv0001, a new invoice number and a different IBAN
    again = {**invs[1], "invoice_number": invs[1]["invoice_number"] + "-B", "iban": generator.iban(rng)}
    p = OUT / "new_bank_details.pdf"
    generator.render(again, p)
    wait(api, h, send(api, h, [p]))
    print("demo users: nadia / demo-clerk (clerk), farhan / demo-approver (approver)")


def send(api, h, files):
    handles = [("files", (p.name, open(p, "rb"))) for p in files]
    r = httpx.post(f"{api}/documents", files=handles, headers=h, timeout=300)
    for _, (_, fh) in handles:
        fh.close()
    for row in r.json():
        print(f"{row['filename']:28} {row['status']:10} {row.get('error_code') or ''}")
    return [row["document_id"] for row in r.json() if row.get("document_id")]


def wait(api, h, ids, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        left = [i for i in ids if httpx.get(f"{api}/documents/{i}?detail=false", headers=h).json()["status"]
                in ("queued", "processing", "finalizing")]
        if not left:
            return
        time.sleep(2)
    print(f"still processing after {timeout}s: {len(left)} documents")


if __name__ == "__main__":
    main()
