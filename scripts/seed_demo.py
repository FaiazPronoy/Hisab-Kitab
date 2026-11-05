"""Uploads a small demo batch through the running API: a clean PDF, a
rotated scan, a corrupted PDF, a multi-invoice PDF, a wrong total, a
ledger workbook and a CSV register."""
import os
import random
from pathlib import Path

import httpx
from faker import Faker

from eval import degrade, generator, sheets_gen

OUT = Path(os.environ.get("DEMO_DIR", "/data/storage/demo"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(3)
    fake = Faker("en_GB")
    invs = [generator.make(fake, rng, i, lay) for i, lay in enumerate(
        ["classic", "eu_vat", "wholesale", "receipt", "classic", "multipage", "credit_note", "classic"])]
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
    led = sheets_gen.ledger(invs[:5], OUT, rng)
    files.append(OUT / led["file"])
    csv = OUT / "register.csv"
    csv.write_text("Invoice No;Date;Supplier;Total;Currency\n" + "\n".join(
        f"{i['invoice_number']};{i['invoice_date']};{i['supplier_name']};{i['total'].replace('.', ',')};{i['currency']}" for i in invs[:4]),
        encoding="cp1252")
    files.append(csv)

    api = os.environ.get("API_URL", "http://api:8000/api/v1")
    h = {"X-API-Key": os.environ.get("API_KEY", "local-dev-key")}
    handles = [("files", (p.name, open(p, "rb"))) for p in files]
    r = httpx.post(f"{api}/documents", files=handles, headers=h, timeout=120)
    for _, (_, fh) in handles:
        fh.close()
    for row in r.json():
        print(f"{row['filename']:28} {row['status']:10} {row.get('error_code') or ''}")


if __name__ == "__main__":
    main()
